#!/usr/bin/env python3

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = ROOT / ".work"
RESULT_ROOT = ROOT / "results" / "raw"

COMPOSE_BASE = [
    "docker",
    "compose",
    "--env-file",
    ".env",
    "-f",
    "docker/compose.yaml",
]


# ---------------------------------------------------------
# Command runner
# ---------------------------------------------------------

def run_command(cmd, cwd=None, timeout=None):
    print("\n$ " + " ".join(str(x) for x in cmd))

    started = time.time()

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )

        elapsed = round(time.time() - started, 3)

        if result.stdout:
            print(result.stdout, end="")

        return {
            "returncode": result.returncode,
            "output": result.stdout or "",
            "seconds": elapsed,
            "timeout": False,
        }

    except subprocess.TimeoutExpired as exc:
        elapsed = round(time.time() - started, 3)

        output = exc.stdout or ""

        if isinstance(output, bytes):
            output = output.decode(errors="replace")

        print(output)
        print("\n[TIMEOUT]")

        return {
            "returncode": None,
            "output": output,
            "seconds": elapsed,
            "timeout": True,
        }


# ---------------------------------------------------------
# Docker command inside checked-out Defects4J project
# ---------------------------------------------------------

def docker_in_workspace(workspace_name, command, timeout=900):
    container_workspace = f"/workspace/.work/{workspace_name}"

    shell_command = f"cd {container_workspace} && {command}"

    cmd = COMPOSE_BASE + [
        "run",
        "--rm",
        "worker",
        "bash",
        "-lc",
        shell_command,
    ]

    return run_command(
        cmd,
        cwd=ROOT,
        timeout=timeout,
    )


# ---------------------------------------------------------
# Files
# ---------------------------------------------------------

def write_log(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def read_text(path):
    if not path.exists():
        return None

    return path.read_text(
        encoding="utf-8",
        errors="replace",
    ).strip()


def read_lines(path):
    text = read_text(path)

    if not text:
        return []

    return [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------
# Defects4J metadata
# ---------------------------------------------------------

def export_property(
    workspace_name,
    property_name,
    metadata_dir,
):
    safe_filename = property_name.replace(".", "_") + ".txt"

    host_file = metadata_dir / safe_filename

    container_output = (
        f".d4j_metadata/{safe_filename}"
    )

    result = docker_in_workspace(
        workspace_name,
        (
            f"defects4j export "
            f"-p {property_name} "
            f"-o {container_output}"
        ),
        timeout=180,
    )

    return result, host_file


# ---------------------------------------------------------
# Parse developer test result
# ---------------------------------------------------------

def parse_failing_tests(output):
    match = re.search(
        r"Failing tests:\s*(\d+)",
        output,
    )

    if not match:
        return None

    return int(match.group(1))


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run baseline pipeline for one Defects4J bug."
    )

    parser.add_argument(
        "--project",
        required=True,
    )

    parser.add_argument(
        "--bug",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--version",
        choices=["b", "f"],
        default="f",
    )

    parser.add_argument(
        "--keep-workspace",
        action="store_true",
    )

    args = parser.parse_args()

    project = args.project
    bug_id = args.bug
    version = args.version

    revision = f"{bug_id}{version}"
    workspace_name = f"{project}-{revision}"

    workspace = WORK_ROOT / workspace_name

    result_dir = (
        RESULT_ROOT
        / project
        / str(bug_id)
        / "baseline"
        / version
    )

    result_file = result_dir / "result.json"

    log_dir = result_dir / "logs"
    stored_metadata_dir = result_dir / "metadata"

    workspace_metadata_dir = (
        workspace / ".d4j_metadata"
    )

    print("=" * 70)
    print(f"Project   : {project}")
    print(f"Bug       : {bug_id}")
    print(f"Revision  : {revision}")
    print(f"Workspace : {workspace}")
    print("=" * 70)

    record = {
        "project": project,
        "bug_id": bug_id,
        "version": version,
        "revision": revision,
        "status": "started",

        "timing": {
            "checkout_seconds": None,
            "compile_seconds": None,
            "test_seconds": None,
        },

        "test": {
            "failing_tests": None,
        },

        "metadata": {
            "src_classes": None,
            "src_tests": None,
            "bin_classes": None,
            "bin_tests": None,
            "modified_classes": [],
            "trigger_tests": [],
        },
    }

    # =====================================================
    # 1. Clean previous workspace
    # =====================================================

    if workspace.exists():
        print(f"\nRemoving old workspace: {workspace}")
        shutil.rmtree(workspace)

    # =====================================================
    # 2. Checkout on HOST
    # =====================================================

    checkout = run_command(
        [
            "defects4j",
            "checkout",
            "-p",
            project,
            "-v",
            revision,
            "-w",
            str(workspace),
        ],
        cwd=ROOT,
        timeout=900,
    )

    record["timing"]["checkout_seconds"] = checkout["seconds"]

    write_log(
        log_dir / "checkout.log",
        checkout["output"],
    )

    if checkout["returncode"] != 0:
        record["status"] = "checkout_failed"
        save_json(result_file, record)
        raise SystemExit(1)

    # =====================================================
    # 3. Compile in Docker
    # =====================================================

    compile_result = docker_in_workspace(
        workspace_name,
        "defects4j compile",
        timeout=900,
    )

    record["timing"]["compile_seconds"] = compile_result["seconds"]

    write_log(
        log_dir / "compile.log",
        compile_result["output"],
    )

    if compile_result["returncode"] != 0:
        record["status"] = "compile_failed"
        save_json(result_file, record)

        if not args.keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)

        raise SystemExit(1)

    # =====================================================
    # 4. Developer tests
    # =====================================================

    test_result = docker_in_workspace(
        workspace_name,
        "defects4j test",
        timeout=900,
    )

    record["timing"]["test_seconds"] = test_result["seconds"]

    failing_tests = parse_failing_tests(
        test_result["output"]
    )

    record["test"]["failing_tests"] = failing_tests

    write_log(
        log_dir / "test.log",
        test_result["output"],
    )

    # =====================================================
    # 5. Metadata
    # =====================================================

    workspace_metadata_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    properties = [
        "dir.src.classes",
        "dir.src.tests",
        "dir.bin.classes",
        "dir.bin.tests",
        "cp.compile",
        "cp.test",
        "classes.modified",
        "classes.relevant",
        "tests.trigger",
        "tests.relevant",
    ]

    exported_files = {}

    for prop in properties:
        print(f"\nExporting metadata: {prop}")

        result, host_file = export_property(
            workspace_name,
            prop,
            workspace_metadata_dir,
        )

        if result["returncode"] == 0:
            exported_files[prop] = host_file

    # =====================================================
    # 6. Copy metadata outside temporary workspace
    # =====================================================

    stored_metadata_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    for prop, src_file in exported_files.items():
        if not src_file.exists():
            continue

        destination = (
            stored_metadata_dir
            / src_file.name
        )

        shutil.copy2(
            src_file,
            destination,
        )

    # =====================================================
    # 7. Compact metadata for result.json
    # =====================================================

    def metadata_file(property_name):
        filename = property_name.replace(".", "_") + ".txt"
        return stored_metadata_dir / filename

    record["metadata"]["src_classes"] = read_text(
        metadata_file("dir.src.classes")
    )

    record["metadata"]["src_tests"] = read_text(
        metadata_file("dir.src.tests")
    )

    record["metadata"]["bin_classes"] = read_text(
        metadata_file("dir.bin.classes")
    )

    record["metadata"]["bin_tests"] = read_text(
        metadata_file("dir.bin.tests")
    )

    record["metadata"]["modified_classes"] = read_lines(
        metadata_file("classes.modified")
    )

    record["metadata"]["trigger_tests"] = read_lines(
        metadata_file("tests.trigger")
    )

    # =====================================================
    # 8. Final status
    # =====================================================

    if test_result["timeout"]:
        record["status"] = "test_timeout"

    elif test_result["returncode"] != 0:
        record["status"] = "test_command_failed"

    else:
        record["status"] = "success"

    save_json(
        result_file,
        record,
    )

    print("\n" + "=" * 70)
    print(f"Status : {record['status']}")
    print(f"Result : {result_file}")
    print("=" * 70)

    # =====================================================
    # 9. Cleanup
    # =====================================================

    if args.keep_workspace:
        print(f"\nWorkspace kept at: {workspace}")

    else:
        print(f"\nCleaning workspace: {workspace}")
        shutil.rmtree(
            workspace,
            ignore_errors=True,
        )


if __name__ == "__main__":
    main()  