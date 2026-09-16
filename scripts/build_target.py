#!/usr/bin/env python3

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = ROOT / ".work"
RESULT_ROOT = ROOT / "results" / "raw"


def sha256_file(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)

            if not chunk:
                break

            h.update(chunk)

    return h.hexdigest()


def class_to_java_path(class_name):
    """
    org.example.Foo -> org/example/Foo.java

    If Defects4J reports an inner class such as:
    org.example.Foo$Bar

    the actual source file is still:
    org/example/Foo.java
    """

    outer_class = class_name.split("$")[0]

    return Path(
        *outer_class.split(".")
    ).with_suffix(".java")


def main():
    parser = argparse.ArgumentParser(
        description="Build target description for one Defects4J bug."
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

    workspace = WORK_ROOT / workspace_name

    baseline_file = (
        RESULT_ROOT
        / project
        / str(bug_id)
        / "baseline"
        / version
        / "result.json"
    )

    target_dir = (
        RESULT_ROOT
        / project
        / str(bug_id)
        / "target"
    )

    target_file = (
        target_dir
        / f"{version}.json"
    )

    # ---------------------------------------------
    # Validate inputs
    # ---------------------------------------------

    if not baseline_file.exists():
        raise SystemExit(
            f"Baseline result not found: {baseline_file}"
        )

    if not workspace.exists():
        raise SystemExit(
            f"Workspace not found: {workspace}\n"
            "Run run_one.py with --keep-workspace first."
        )

    baseline = json.loads(
        baseline_file.read_text(
            encoding="utf-8"
        )
    )

    metadata = baseline["metadata"]

    src_dir = metadata["src_classes"]
    modified_classes = metadata["modified_classes"]
    trigger_tests = metadata["trigger_tests"]

    if not src_dir:
        raise SystemExit(
            "dir.src.classes is missing."
        )

    source_root = workspace / src_dir

    if not source_root.exists():
        raise SystemExit(
            f"Source root not found: {source_root}"
        )

    # ---------------------------------------------
    # Resolve classes -> source files
    # ---------------------------------------------

    targets = []

    for class_name in modified_classes:
        java_relative = class_to_java_path(
            class_name
        )

        source_file = (
            source_root
            / java_relative
        )

        entry = {
            "class_name": class_name,
            "source_file": str(
                Path(src_dir)
                / java_relative
            ),
            "exists": source_file.exists(),
            "sha256": None,
            "size_bytes": None,
            "line_count": None,
        }

        if source_file.exists():
            entry["sha256"] = sha256_file(
                source_file
            )

            entry["size_bytes"] = (
                source_file.stat().st_size
            )

            text = source_file.read_text(
                encoding="utf-8",
                errors="replace",
            )

            entry["line_count"] = (
                len(text.splitlines())
            )

        targets.append(entry)

    # ---------------------------------------------
    # Build description
    # ---------------------------------------------

    target_description = {
        "project": project,
        "bug_id": bug_id,
        "version": version,
        "revision": revision,

        "workspace": str(workspace),

        "project_layout": {
            "src_classes": metadata["src_classes"],
            "src_tests": metadata["src_tests"],
            "bin_classes": metadata["bin_classes"],
            "bin_tests": metadata["bin_tests"],
        },

        # IMPORTANT:
        # These are Defects4J ground-truth metadata.
        # Do not automatically expose them to generators
        # in the final benchmark protocol.
        "ground_truth": {
            "modified_classes": modified_classes,
            "trigger_tests": trigger_tests,
        },

        "pilot_targets": targets,
    }

    target_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    target_file.write_text(
        json.dumps(
            target_description,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # ---------------------------------------------
    # Summary
    # ---------------------------------------------

    print("=" * 70)
    print(f"Project       : {project}")
    print(f"Bug           : {bug_id}")
    print(f"Revision      : {revision}")
    print(f"Source root   : {source_root}")
    print(f"Target classes: {len(targets)}")

    for target in targets:
        mark = "OK" if target["exists"] else "MISSING"

        print(
            f"[{mark}] "
            f"{target['class_name']} "
            f"-> {target['source_file']}"
        )

    print(f"\nTarget description saved to:")
    print(target_file)
    print("=" * 70)


if __name__ == "__main__":
    main()