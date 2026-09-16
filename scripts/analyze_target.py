#!/usr/bin/env python3

import argparse
import json
import re
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = ROOT / "results" / "raw"

COMPOSE_BASE = [
    "docker",
    "compose",
    "--env-file",
    ".env",
    "-f",
    "docker/compose.yaml",
]


def run_docker(workspace_name, command, timeout=300):
    container_workspace = f"/workspace/.work/{workspace_name}"

    shell_command = (
        f"cd {shlex.quote(container_workspace)} && "
        f"{command}"
    )

    cmd = COMPOSE_BASE + [
        "run",
        "--rm",
        "worker",
        "bash",
        "-lc",
        shell_command,
    ]

    print("\n$ " + " ".join(cmd))

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )

    if result.stderr:
        print(result.stderr, end="")

    return result


def safe_filename(class_name):
    return (
        class_name
        .replace(".", "_")
        .replace("$", "_")
    )


def parse_javap(text, class_name):
    lines = [
        line.rstrip()
        for line in text.splitlines()
        if line.strip()
    ]

    declaration = None

    for line in lines:
        stripped = line.strip()

        if (
            " class " in f" {stripped} "
            or " interface " in f" {stripped} "
            or " enum " in f" {stripped} "
        ):
            if stripped.endswith("{"):
                declaration = stripped
                break

    is_abstract = False
    is_interface = False
    is_enum = False

    if declaration:
        is_abstract = bool(
            re.search(r"\babstract\b", declaration)
        )

        is_interface = bool(
            re.search(r"\binterface\b", declaration)
        )

        is_enum = bool(
            re.search(r"\benum\b", declaration)
        )

    members = []

    current_member = None

    for raw_line in lines:
        line = raw_line.strip()

        if line == declaration:
            continue

        if line in ("{", "}"):
            continue

        if line.startswith("Compiled from"):
            continue

        # javap -s prints descriptor on the line after a member.
        if line.startswith("descriptor:"):
            if current_member is not None:
                current_member["descriptor"] = (
                    line.split(":", 1)[1].strip()
                )

            continue

        # Public API declaration lines normally end with ;
        if not line.endswith(";"):
            continue

        signature = line[:-1].strip()

        # Method / constructor
        if "(" in signature and ")" in signature:

            before_paren = signature.split("(", 1)[0]

            member_name = before_paren.split()[-1]

            if member_name == class_name:
                kind = "constructor"
            else:
                kind = "method"

            current_member = {
                "kind": kind,
                "name": member_name,
                "signature": signature,
                "descriptor": None,
            }

            members.append(current_member)

        # Public field
        else:
            parts = signature.split()

            member_name = (
                parts[-1]
                if parts
                else None
            )

            current_member = {
                "kind": "field",
                "name": member_name,
                "signature": signature,
                "descriptor": None,
            }

            members.append(current_member)

    constructors = [
        m for m in members
        if m["kind"] == "constructor"
    ]

    methods = [
        m for m in members
        if m["kind"] == "method"
    ]

    fields = [
        m for m in members
        if m["kind"] == "field"
    ]

    return {
        "class_name": class_name,
        "declaration": declaration,

        "class_properties": {
            "abstract": is_abstract,
            "interface": is_interface,
            "enum": is_enum,

            "directly_instantiable": (
                not is_abstract
                and not is_interface
            ),
        },

        "constructor_count": len(constructors),
        "method_count": len(methods),
        "field_count": len(fields),

        "constructors": constructors,
        "methods": methods,
        "fields": fields,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Defects4J target public API using javap."
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
        default="b",
    )

    args = parser.parse_args()

    project = args.project
    bug_id = args.bug
    version = args.version

    revision = f"{bug_id}{version}"
    workspace_name = f"{project}-{revision}"

    target_file = (
        RESULT_ROOT
        / project
        / str(bug_id)
        / "target"
        / f"{version}.json"
    )

    baseline_metadata_dir = (
        RESULT_ROOT
        / project
        / str(bug_id)
        / "baseline"
        / version
        / "metadata"
    )

    cp_test_file = (
        baseline_metadata_dir
        / "cp_test.txt"
    )

    cp_compile_file = (
        baseline_metadata_dir
        / "cp_compile.txt"
    )

    if not target_file.exists():
        raise SystemExit(
            f"Target description not found: {target_file}"
        )

    # Prefer test classpath because it usually contains:
    # production classes + test classes + JUnit/dependencies.
    if cp_test_file.exists():
        classpath = cp_test_file.read_text(
            encoding="utf-8"
        ).strip()

        classpath_source = "cp.test"

    elif cp_compile_file.exists():
        classpath = cp_compile_file.read_text(
            encoding="utf-8"
        ).strip()

        classpath_source = "cp.compile"

    else:
        raise SystemExit(
            "Neither cp_test.txt nor cp_compile.txt exists."
        )

    target = json.loads(
        target_file.read_text(
            encoding="utf-8"
        )
    )

    output_dir = (
        RESULT_ROOT
        / project
        / str(bug_id)
        / "target_api"
        / version
    )

    raw_dir = output_dir / "javap"

    raw_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    classes = []

    for item in target["pilot_targets"]:

        if not item["exists"]:
            continue

        class_name = item["class_name"]

        print("\n" + "=" * 70)
        print(f"Analyzing: {class_name}")
        print("=" * 70)

        command = (
            "javap "
            "-public "
            "-s "
            f"-classpath {shlex.quote(classpath)} "
            f"{shlex.quote(class_name)}"
        )

        result = run_docker(
            workspace_name,
            command,
        )

        raw_file = (
            raw_dir
            / f"{safe_filename(class_name)}.txt"
        )

        raw_file.write_text(
            result.stdout,
            encoding="utf-8",
        )

        if result.returncode != 0:
            print(
                f"[FAILED] javap for {class_name}"
            )

            classes.append({
                "class_name": class_name,
                "success": False,
                "error": result.stderr,
            })

            continue

        parsed = parse_javap(
            result.stdout,
            class_name,
        )

        parsed["success"] = True
        parsed["source_file"] = item["source_file"]
        parsed["source_sha256"] = item["sha256"]

        classes.append(parsed)

        print(
            f"abstract={parsed['class_properties']['abstract']}, "
            f"constructors={parsed['constructor_count']}, "
            f"methods={parsed['method_count']}"
        )

    api_description = {
        "project": project,
        "bug_id": bug_id,
        "version": version,
        "revision": revision,

        "classpath_source": classpath_source,

        "target_classes": classes,
    }

    output_file = (
        output_dir
        / "target_api.json"
    )

    output_file.write_text(
        json.dumps(
            api_description,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("\n" + "=" * 70)
    print("Target API analysis complete")
    print(f"Result: {output_file}")
    print("=" * 70)


if __name__ == "__main__":
    main()