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


# =========================================================
# Parse javap
# =========================================================

def parse_declaration(text):
    for raw in text.splitlines():
        line = raw.strip()

        if not line.endswith("{"):
            continue

        if (
            " class " in f" {line} "
            or " interface " in f" {line} "
            or " enum " in f" {line} "
        ):
            return line

    return None


def parse_class_info(text, class_name):
    declaration = parse_declaration(text)

    if not declaration:
        return None

    is_abstract = bool(
        re.search(r"\babstract\b", declaration)
    )

    is_interface = bool(
        re.search(r"\binterface\b", declaration)
    )

    superclass = None

    match = re.search(
        r"\bextends\s+([^\s,{]+)",
        declaration,
    )

    if match:
        superclass = match.group(1)

    constructors = []

    for raw in text.splitlines():
        line = raw.strip()

        if not line.endswith(";"):
            continue

        signature = line[:-1].strip()

        if "(" not in signature:
            continue

        before = signature.split("(", 1)[0]
        name = before.split()[-1]

        if name == class_name:
            constructors.append(signature)

    return {
        "class_name": class_name,
        "declaration": declaration,
        "superclass": superclass,
        "abstract": is_abstract,
        "interface": is_interface,
        "constructors": constructors,

        "directly_instantiable": (
            not is_abstract
            and not is_interface
            and len(constructors) > 0
        ),
    }


# =========================================================
# Helpers
# =========================================================

def constructor_parameter_count(signature):
    inside = (
        signature
        .split("(", 1)[1]
        .rsplit(")", 1)[0]
        .strip()
    )

    if not inside:
        return 0

    return len([
        p
        for p in inside.split(",")
        if p.strip()
    ])


def is_subclass_of(
    class_name,
    target_name,
    class_info,
):
    current = class_name
    visited = set()

    while current and current not in visited:
        visited.add(current)

        info = class_info.get(current)

        if not info:
            return False

        parent = info.get("superclass")

        if parent == target_name:
            return True

        current = parent

    return False


# =========================================================
# FAST batch javap
# =========================================================

def scan_classes_once(
    workspace_name,
    classpath,
    class_names,
):
    """
    ONE Docker container + ONE javap process
    for all requested classes.
    """

    container_workspace = (
        f"/workspace/.work/{workspace_name}"
    )

    class_args = " ".join(
        shlex.quote(name)
        for name in class_names
    )

    command = (
        f"cd {shlex.quote(container_workspace)} && "
        "javap "
        "-public "
        f"-classpath {shlex.quote(classpath)} "
        f"{class_args}"
    )

    cmd = COMPOSE_BASE + [
        "run",
        "--rm",
        "worker",
        "bash",
        "-lc",
        command,
    ]

    print(
        f"Scanning {len(class_names)} classes "
        "using one Docker container "
        "and one javap process..."
    )

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
    )

    if result.returncode != 0 and result.stderr:
        print(result.stderr)

    whole_output = result.stdout

    outputs = {}

    # Split javap output by class declarations.
    # Each section usually begins with:
    # Compiled from "Something.java"
    sections = re.split(
        r'(?=Compiled from ")',
        whole_output,
    )

    for section in sections:
        if not section.strip():
            continue

        declaration = parse_declaration(
            section
        )

        if not declaration:
            continue

        # Extract fully qualified class/interface name
        match = re.search(
            r'\b(?:class|interface|enum)\s+([^\s<{]+)',
            declaration,
        )

        if not match:
            continue

        detected_name = match.group(1)

        outputs[detected_name] = section

    return outputs


# =========================================================
# Main
# =========================================================

def main():
    parser = argparse.ArgumentParser()

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
    bug = args.bug
    version = args.version

    revision = f"{bug}{version}"
    workspace_name = f"{project}-{revision}"

    target_api_file = (
        RESULT_ROOT
        / project
        / str(bug)
        / "target_api"
        / version
        / "target_api.json"
    )

    metadata_dir = (
        RESULT_ROOT
        / project
        / str(bug)
        / "baseline"
        / version
        / "metadata"
    )

    relevant_file = (
        metadata_dir
        / "classes_relevant.txt"
    )

    cp_test_file = (
        metadata_dir
        / "cp_test.txt"
    )

    if not target_api_file.exists():
        raise SystemExit(
            f"Missing: {target_api_file}"
        )

    if not relevant_file.exists():
        raise SystemExit(
            f"Missing: {relevant_file}"
        )

    if not cp_test_file.exists():
        raise SystemExit(
            f"Missing: {cp_test_file}"
        )

    target_api = json.loads(
        target_api_file.read_text(
            encoding="utf-8"
        )
    )

    relevant_classes = [
        line.strip()
        for line in relevant_file.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    classpath = cp_test_file.read_text(
        encoding="utf-8"
    ).strip()

    target_names = [
        c["class_name"]
        for c in target_api["target_classes"]
        if c.get("success")
    ]

    classes_to_scan = sorted(
        set(
            relevant_classes
            + target_names
        )
    )

    # =====================================================
    # ONE Docker startup for all classes
    # =====================================================

    javap_outputs = scan_classes_once(
        workspace_name,
        classpath,
        classes_to_scan,
    )

    class_info = {}

    for class_name in classes_to_scan:

        text = javap_outputs.get(class_name)

        if not text:
            continue

        parsed = parse_class_info(
            text,
            class_name,
        )

        if parsed:
            class_info[class_name] = parsed

    # =====================================================
    # Resolve candidates
    # =====================================================

    result_targets = []

    for target_name in target_names:

        target_info = (
            class_info.get(target_name)
        )

        candidates = []

        if (
            target_info
            and target_info[
                "directly_instantiable"
            ]
        ):
            candidates.append({
                "class_name": target_name,
                "relationship": "target_itself",
                "constructors":
                    target_info["constructors"],
            })

        for class_name, info in class_info.items():

            if class_name == target_name:
                continue

            if not info[
                "directly_instantiable"
            ]:
                continue

            if not is_subclass_of(
                class_name,
                target_name,
                class_info,
            ):
                continue

            candidates.append({
                "class_name": class_name,
                "relationship": "subclass",
                "constructors":
                    info["constructors"],
            })

        for candidate in candidates:

            candidate[
                "minimum_constructor_parameters"
            ] = min(
                constructor_parameter_count(c)
                for c in candidate[
                    "constructors"
                ]
            )

        candidates.sort(
            key=lambda c: (
                c[
                    "minimum_constructor_parameters"
                ],
                c["class_name"],
            )
        )

        recommended = (
            candidates[0]
            if candidates
            else None
        )

        result_targets.append({
            "target_class": target_name,

            "target_abstract": (
                target_info["abstract"]
                if target_info
                else None
            ),

            "candidate_count":
                len(candidates),

            "recommended_candidate":
                recommended,

            "candidates":
                candidates,
        })

    # =====================================================
    # Save
    # =====================================================

    output = {
        "project": project,
        "bug_id": bug,
        "version": version,
        "revision": revision,

        "scan": {
            "classes_requested":
                len(classes_to_scan),

            "classes_analyzed":
                len(class_info),

            "docker_containers_started": 1,
        },

        "targets": result_targets,
    }

    output_dir = (
        RESULT_ROOT
        / project
        / str(bug)
        / "instantiation"
        / version
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = (
        output_dir
        / "instantiation.json"
    )

    output_file.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # =====================================================
    # Summary
    # =====================================================

    print("\n" + "=" * 70)

    print(
        f"Classes analyzed: "
        f"{len(class_info)}/"
        f"{len(classes_to_scan)}"
    )

    print(
        "Docker containers started: 1"
    )

    for target in result_targets:

        print("\nTarget:")
        print(
            target["target_class"]
        )

        print(
            "Candidates:",
            target["candidate_count"]
        )

        recommended = (
            target[
                "recommended_candidate"
            ]
        )

        if recommended:

            print(
                "Recommended:",
                recommended[
                    "class_name"
                ]
            )

            print(
                "Min constructor params:",
                recommended[
                    "minimum_constructor_parameters"
                ]
            )

        else:
            print("Recommended: NONE")

    print(
        f"\nSaved: {output_file}"
    )

    print("=" * 70)


if __name__ == "__main__":
    main()