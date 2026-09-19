#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".work"
RESULTS = ROOT / "results"
COMPOSE = ["docker", "compose", "--env-file", ".env", "-f", "docker/compose.yaml"]
SUPPORTED_ARG_TYPES = {
    "byte", "short", "int", "long", "float", "double", "boolean", "char", "java.lang.String"
}
_WORKER_READY = False


def load_dotenv() -> None:
    """Load the repository .env for direct d4j.py usage as well as run.py."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_settings() -> dict[str, Any]:
    return json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    """Atomically save a JSON checkpoint so an interrupted write cannot destroy prior progress."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def run(cmd: list[str], cwd: Path | None = None, timeout: int | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}\n{result.stdout}")
    return result


def defects4j_bin() -> str:
    load_dotenv()
    found = shutil.which("defects4j")
    if found:
        return found
    d4j_root = os.getenv("D4J_ROOT")
    if d4j_root:
        candidate = Path(d4j_root) / "framework/bin/defects4j"
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("defects4j not found on host PATH. Add Defects4J framework/bin to PATH.")


def ensure_worker() -> None:
    global _WORKER_READY
    load_dotenv()
    if _WORKER_READY:
        return
    if not (ROOT / ".env").exists():
        raise RuntimeError("Missing .env. Copy .env.example to .env and fill D4J_ROOT/UID/GID/API keys.")
    run(COMPOSE + ["up", "-d", "--build", "worker"], timeout=600)
    docker_exec("mkdir -p /workspace/harness/classes && javac -d /workspace/harness/classes /workspace/harness/CandidateRunner.java", timeout=120)
    _WORKER_READY = True


def docker_exec(command: str, timeout: int | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(COMPOSE + ["exec", "-T", "worker", "bash", "-lc", command], timeout=timeout, check=check)


def workspace(project: str, bug_id: int, version: str) -> Path:
    return WORK / f"{project}-{bug_id}{version}"


def container_workspace(project: str, bug_id: int, version: str) -> str:
    return f"/workspace/.work/{project}-{bug_id}{version}"


def checkout(project: str, bug_id: int, version: str) -> Path:
    """
    Checkout inside the Docker worker, not on the host.

    Some old Defects4J projects write absolute Defects4J dependency paths into
    their generated build files. A host checkout can therefore embed paths such
    as /home/<user>/defects4j, which do not exist inside the worker where the
    project is compiled. Container-side checkout keeps those paths rooted at
    /opt/defects4j consistently.

    The marker also prevents reusing older host-created workspaces after this
    fix is introduced.
    """
    ensure_worker()

    ws = workspace(project, bug_id, version)
    cws = container_workspace(project, bug_id, version)
    marker = ws / ".sqa_container_checkout"

    if (
        ws.exists()
        and (ws / ".defects4j.config").exists()
        and marker.exists()
    ):
        return ws

    q_cws = shlex.quote(cws)
    q_project = shlex.quote(project)
    q_version = shlex.quote(f"{bug_id}{version}")

    docker_exec(
        " && ".join([
            f"rm -rf {q_cws}",
            "mkdir -p /workspace/.work",
            f"defects4j checkout -p {q_project} -v {q_version} -w {q_cws}",
            f"touch {q_cws}/.sqa_container_checkout",
        ]),
        timeout=600,
    )

    if not (ws / ".defects4j.config").exists():
        raise RuntimeError(
            f"Defects4J checkout did not create .defects4j.config: {project}-{bug_id}{version}"
        )

    return ws


def compile_revision(project: str, bug_id: int, version: str) -> None:
    cws = container_workspace(project, bug_id, version)
    docker_exec(f'cd "{cws}" && defects4j compile', timeout=600)


def export_property(project: str, bug_id: int, version: str, prop: str) -> str:
    cws = container_workspace(project, bug_id, version)

    safe_prop = re.sub(r"[^A-Za-z0-9_.-]+", "_", prop)
    filename = f".sqa_export_{safe_prop}.txt"
    host_file = workspace(project, bug_id, version) / filename

    if host_file.exists():
        host_file.unlink()

    docker_exec(
        f'cd "{cws}" && defects4j export -p "{prop}" -o "{filename}"',
        timeout=120,
    )

    if not host_file.exists():
        raise RuntimeError(f"Defects4J export did not create output file for property: {prop}")

    value = host_file.read_text(encoding="utf-8", errors="replace").strip()
    try:
        host_file.unlink()
    except FileNotFoundError:
        pass
    return value


def parse_descriptor_type(desc: str, i: int) -> tuple[str, int]:
    primitive = {"B": "byte", "C": "char", "D": "double", "F": "float", "I": "int", "J": "long", "S": "short", "Z": "boolean", "V": "void"}
    c = desc[i]
    if c in primitive:
        return primitive[c], i + 1
    if c == "L":
        j = desc.index(";", i)
        return desc[i + 1:j].replace("/", "."), j + 1
    if c == "[":
        t, j = parse_descriptor_type(desc, i + 1)
        return t + "[]", j
    raise ValueError(f"Unsupported descriptor: {desc}")


def parse_method_descriptor(desc: str) -> tuple[list[str], str]:
    if not desc.startswith("("):
        raise ValueError(desc)
    i = 1
    args: list[str] = []
    while desc[i] != ")":
        t, i = parse_descriptor_type(desc, i)
        args.append(t)
    ret, _ = parse_descriptor_type(desc, i + 1)
    return args, ret


def javap(project: str, bug_id: int, version: str, class_name: str, cp_test: str) -> str:
    cws = container_workspace(project, bug_id, version)
    cmd = (
        f"cd {shlex.quote(cws)} && "
        f"javap -public -s "
        f"-classpath {shlex.quote(cp_test)} "
        f"{shlex.quote(class_name)}"
    )
    return docker_exec(cmd, timeout=120).stdout


def parse_public_api(javap_text: str, class_name: str) -> tuple[list[dict[str, Any]], str]:
    lines = javap_text.splitlines()
    methods: list[dict[str, Any]] = []
    pending: str | None = None
    simple = class_name.rsplit(".", 1)[-1]
    class_decl = ""
    for line in lines:
        s = line.strip()
        if (s.startswith("public ") or s.startswith("protected ")) and (" class " in s or " interface " in s):
            class_decl = s
        if s.startswith("public ") and "(" in s and s.endswith(";"):
            pending = s
            continue
        if pending and s.startswith("descriptor:"):
            descriptor = s.split(":", 1)[1].strip()
            before = pending.split("(", 1)[0].strip()
            name = before.split()[-1]
            if name == simple or name.endswith("." + simple):
                pending = None
                continue
            try:
                args, ret = parse_method_descriptor(descriptor)
            except Exception:
                pending = None
                continue
            methods.append({
                "name": name,
                "descriptor": descriptor,
                "parameter_types": args,
                "return_type": ret,
                "declaration": pending,
            })
            pending = None
    return methods, class_decl


def public_noarg_instantiable(javap_text: str, class_name: str, class_decl: str) -> bool:
    """True when CandidateRunner can construct the configured class with getConstructor()."""
    decl = class_decl.strip()
    if not decl.startswith("public ") or " interface " in f" {decl} " or " abstract " in f" {decl} ":
        return False
    simple = class_name.rsplit(".", 1)[-1]
    for raw in javap_text.splitlines():
        line = raw.strip()
        if not (line.startswith("public ") and line.endswith("();")):
            continue
        before = line.split("(", 1)[0].strip()
        name = before.split()[-1]
        if name == simple or name == class_name or name.endswith("." + simple):
            return True
    return False


def choose_target(project: str, bug_id: int, override: str) -> tuple[str, str]:
    if override.strip():
        return override.strip(), "cases.csv"
    modified = export_property(project, bug_id, "f", "classes.modified")
    candidates = [x.strip() for x in modified.splitlines() if x.strip()]
    if not candidates:
        raise RuntimeError("No target_class in cases.csv and Defects4J classes.modified is empty")
    return candidates[0], "defects4j_classes.modified"


def source_text(project: str, bug_id: int, target_class: str) -> tuple[str, str]:
    src_root = export_property(project, bug_id, "f", "dir.src.classes")
    # Nested classes live in the outer class source file (Outer$Inner -> Outer.java).
    source_class = target_class.split("$", 1)[0]
    rel = Path(src_root) / Path(*source_class.split(".")).with_suffix(".java")
    path = workspace(project, bug_id, "f") / rel
    if not path.exists():
        return "", str(rel)
    return path.read_text(encoding="utf-8", errors="replace"), str(rel)


def default_setup_value(type_name: str) -> Any:
    if type_name == "boolean":
        return False
    if type_name in {"byte", "short", "int", "long", "float", "double"}:
        return 0
    if type_name == "char":
        return "a"
    if type_name == "java.lang.String":
        return ""
    return None


def build_setup_actions(
    project: str,
    bug_id: int,
    fixed_cp: str,
    methods: list[dict[str, Any]],
    concrete_methods: list[dict[str, Any]],
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build a small, generic state-setup pool without trigger tests or patches.

    A setup action is a public instance void method whose arguments are either
    primitive/String defaults or exact public classes with a public no-arg
    constructor. This intentionally stays small and simple; it does not try to
    solve arbitrary object graphs.
    """
    max_actions = max(0, int(settings.get("stateful_max_setup_actions", 6)))
    max_params = max(0, int(settings.get("stateful_max_setup_parameters", 2)))
    if max_actions == 0:
        return []

    helper_cache: dict[str, bool] = {}

    def helper_is_instantiable(type_name: str) -> bool:
        if type_name in helper_cache:
            return helper_cache[type_name]
        if type_name.endswith("[]") or type_name in SUPPORTED_ARG_TYPES or type_name == "void":
            helper_cache[type_name] = False
            return False
        try:
            text = javap(project, bug_id, "f", type_name, fixed_cp)
            _, decl = parse_public_api(text, type_name)
            ok = public_noarg_instantiable(text, type_name, decl)
        except Exception:
            ok = False
        helper_cache[type_name] = ok
        return ok

    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for method in [*methods, *concrete_methods]:
        key = (method["name"], method["descriptor"])
        unique.setdefault(key, method)

    actions: list[dict[str, Any]] = []
    for method in unique.values():
        declaration = method.get("declaration", "")
        if method.get("return_type") != "void" or " static " in f" {declaration} ":
            continue
        param_types = list(method.get("parameter_types", []))
        if len(param_types) > max_params:
            continue

        arguments: list[dict[str, Any]] = []
        supported = True
        object_count = 0
        for type_name in param_types:
            if type_name in SUPPORTED_ARG_TYPES:
                arguments.append({"kind": "value", "type": type_name, "value": default_setup_value(type_name)})
            elif helper_is_instantiable(type_name):
                arguments.append({"kind": "new", "type": type_name})
                object_count += 1
            else:
                supported = False
                break
        if not supported:
            continue
        actions.append({
            "name": method["name"],
            "descriptor": method["descriptor"],
            "parameter_types": param_types,
            "arguments": arguments,
            "declaration": declaration,
            "object_argument_count": object_count,
        })

    # Object-wiring setters first, then zero/small primitive setup methods.
    actions.sort(key=lambda a: (-int(a["object_argument_count"]), len(a["parameter_types"]), a["name"], a["descriptor"]))
    return actions[:max_actions]


def build_setup_sequences(actions: list[dict[str, Any]], settings: dict[str, Any]) -> list[list[dict[str, Any]]]:
    max_steps = max(0, int(settings.get("stateful_max_setup_steps", 2)))
    max_sequences = max(1, int(settings.get("stateful_max_sequences", 12)))
    sequences: list[list[dict[str, Any]]] = [[]]
    if max_steps == 0 or not actions:
        return sequences

    for action in actions:
        if len(sequences) >= max_sequences:
            return sequences
        sequences.append([action])

    if max_steps >= 2:
        # Ordered pairs let simple state changes happen in either order, but the
        # hard cap prevents combinatorial growth.
        for first in actions:
            for second in actions:
                if first is second:
                    continue
                if len(sequences) >= max_sequences:
                    return sequences
                sequences.append([first, second])
    return sequences


def prepare_case(case: dict[str, str]) -> dict[str, Any]:
    project = case["project"].strip()
    bug_id = int(case["bug_id"])
    ensure_worker()
    for version in ("f", "b"):
        checkout(project, bug_id, version)
        compile_revision(project, bug_id, version)

    fixed_cp = export_property(project, bug_id, "f", "cp.test")
    buggy_cp = export_property(project, bug_id, "b", "cp.test")
    fixed_bin = export_property(project, bug_id, "f", "dir.bin.classes")
    buggy_bin = export_property(project, bug_id, "b", "dir.bin.classes")
    target_class, target_source = choose_target(project, bug_id, case.get("target_class", ""))
    concrete_class = case.get("concrete_class", "").strip() or target_class
    api_text = javap(project, bug_id, "f", target_class, fixed_cp)
    methods, class_decl = parse_public_api(api_text, target_class)
    requested_method = case.get("method", "").strip()
    eligible = [m for m in methods if all(t in SUPPORTED_ARG_TYPES for t in m["parameter_types"])]
    if requested_method:
        eligible = [m for m in eligible if m["name"] == requested_method]
    concrete_api_text = api_text if concrete_class == target_class else javap(project, bug_id, "f", concrete_class, fixed_cp)
    concrete_methods, concrete_decl = parse_public_api(concrete_api_text, concrete_class)
    concrete_instantiable = public_noarg_instantiable(concrete_api_text, concrete_class, concrete_decl)
    settings = load_settings()
    setup_actions = build_setup_actions(project, bug_id, fixed_cp, methods, concrete_methods, settings)
    setup_sequences = build_setup_sequences(setup_actions, settings)
    src, src_path = source_text(project, bug_id, target_class)

    meta = {
        "project": project,
        "bug_id": bug_id,
        "fixed_workspace": container_workspace(project, bug_id, "f"),
        "buggy_workspace": container_workspace(project, bug_id, "b"),
        "fixed_cp_test": fixed_cp,
        "buggy_cp_test": buggy_cp,
        "fixed_bin_classes": fixed_bin,
        "buggy_bin_classes": buggy_bin,
        "target_class": target_class,
        "target_selection_source": target_source,
        "concrete_class": concrete_class,
        "concrete_instantiable": concrete_instantiable,
        "class_declaration": class_decl,
        "concrete_class_declaration": concrete_decl,
        "public_api_text": api_text,
        "concrete_api_text": concrete_api_text,
        "eligible_methods": eligible,
        "setup_actions": setup_actions,
        "setup_sequences": setup_sequences,
        "source_path": src_path,
        "source_text": src,
    }
    out = RESULTS / "meta" / project / str(bug_id) / "meta.json"
    save_json(out, meta)
    return meta


def load_cases(path: Path | None = None) -> list[dict[str, str]]:
    path = path or ROOT / "config/cases.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"project", "bug_id", "target_class", "concrete_class", "method", "enabled"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"cases.csv is missing columns: {', '.join(sorted(missing))}")
        rows = list(reader)
    enabled = [r for r in rows if r.get("enabled", "true").strip().lower() not in {"false", "0", "no"}]
    seen: set[tuple[str, int]] = set()
    for row in enabled:
        key = (row["project"].strip(), int(row["bug_id"]))
        if key in seen:
            raise ValueError(f"Duplicate enabled case in cases.csv: {key[0]}-{key[1]}. Use one row per bug.")
        seen.add(key)
    return enabled


def build_inventory(out_path: Path) -> int:
    d4j = defects4j_bin()
    projects = [x.strip() for x in run([d4j, "pids"]).stdout.splitlines() if x.strip()]
    rows: list[dict[str, str]] = []
    for project in projects:
        bids = [x.strip() for x in run([d4j, "bids", "-p", project]).stdout.splitlines() if x.strip().isdigit()]
        for bid in bids:
            rows.append({
                "project": project,
                "bug_id": bid,
                "target_class": "",
                "concrete_class": "",
                "method": "",
                "enabled": "true",
            })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["project", "bug_id", "target_class", "concrete_class", "method", "enabled"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def check_environment() -> None:
    print(f"ROOT: {ROOT}")
    print(f"defects4j: {defects4j_bin()}")
    print(f"docker: {shutil.which('docker') or 'NOT FOUND'}")
    print(f".env: {'OK' if (ROOT/'.env').exists() else 'MISSING'}")
    if (ROOT / ".env").exists():
        ensure_worker()
        result = docker_exec("java -version 2>&1 | head -n 1 && defects4j version 2>&1 | head -n 1", check=False)
        print(result.stdout.strip())


def main() -> None:
    ap = argparse.ArgumentParser(description="Defects4J environment and case preparation")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    inv = sub.add_parser("inventory")
    inv.add_argument("--out", default="config/cases.csv")
    prep = sub.add_parser("prepare")
    prep.add_argument("--project", required=True)
    prep.add_argument("--bug", required=True, type=int)
    prep.add_argument("--target-class", default="")
    prep.add_argument("--concrete-class", default="")
    prep.add_argument("--method", default="")
    args = ap.parse_args()
    if args.command == "check":
        check_environment()
    elif args.command == "inventory":
        count = build_inventory(ROOT / args.out)
        print(f"Wrote {count} cases to {args.out}")
    else:
        meta = prepare_case({
            "project": args.project,
            "bug_id": str(args.bug),
            "target_class": args.target_class,
            "concrete_class": args.concrete_class,
            "method": args.method,
        })
        print(json.dumps({k: meta[k] for k in ("project", "bug_id", "target_class", "concrete_class", "target_selection_source")}, indent=2))
        print(f"Eligible methods: {len(meta['eligible_methods'])}")


if __name__ == "__main__":
    main()
