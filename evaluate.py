#!/usr/bin/env python3
from __future__ import annotations

import base64
import csv
import hashlib
import json
import math
import os
import re
import shlex
import time
from pathlib import Path
from typing import Any

import d4j

ROOT = Path(__file__).resolve().parent
TMP = ROOT / "results/tmp"
AGENT = "/workspace/tools/jacoco/jacocoagent.jar"
CLI = "/workspace/tools/jacoco/jacococli.jar"
JACOCO_URL = "https://repo1.maven.org/maven2/org/jacoco/org.jacoco.cli/0.8.13/org.jacoco.cli-0.8.13-nodeps.jar"
JACOCO_AGENT_URL = "https://repo1.maven.org/maven2/org/jacoco/org.jacoco.agent/0.8.13/org.jacoco.agent-0.8.13-runtime.jar"
_JACOCO_READY = False


def ensure_jacoco() -> None:
    global _JACOCO_READY
    if _JACOCO_READY:
        return
    cmd = (
        "mkdir -p /workspace/tools/jacoco && "
        f"if [ ! -s {CLI} ]; then curl -fsSL {shlex.quote(JACOCO_URL)} -o {CLI}; fi && "
        f"if [ ! -s {AGENT} ]; then curl -fsSL {shlex.quote(JACOCO_AGENT_URL)} -o {AGENT}; fi && "
        f"test -s {CLI} && test -s {AGENT}"
    )
    d4j.docker_exec(cmd, timeout=180)
    _JACOCO_READY = True


def b64(value: Any) -> str:
    if value is None:
        value = "__NULL__"
    return base64.b64encode(str(value).encode("utf-8")).decode("ascii")


def encode_setup_step(action: dict[str, Any]) -> str:
    fields = [action["name"], ",".join(action.get("parameter_types", []))]
    for arg in action.get("arguments", []):
        if arg.get("kind") == "new":
            fields.append("N:" + str(arg["type"]))
        elif arg.get("kind") == "value":
            fields.append("V:" + b64(arg.get("value")))
        else:
            raise ValueError(f"Unsupported setup argument: {arg}")
    raw = "\t".join(fields)
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def parse_runner_output(text: str) -> dict[str, Any]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k in {
                "STATUS", "RETURN_TYPE", "RETURN_KIND", "RETURN_B64",
                "EXCEPTION_CLASS", "EXCEPTION_MESSAGE_B64", "ERROR_CLASS", "ERROR_MESSAGE_B64"
            }:
                data[k] = v
    status = data.get("STATUS", "ERROR")
    out: dict[str, Any] = {"status": status.lower()}
    if status == "OK":
        out["return_type"] = data.get("RETURN_TYPE", "")
        out["return_kind"] = data.get("RETURN_KIND", "")
        raw = data.get("RETURN_B64", "")
        out["return_value"] = base64.b64decode(raw).decode("utf-8", errors="replace") if raw else ""
    elif status == "EXCEPTION":
        out["exception_class"] = data.get("EXCEPTION_CLASS", "")
        raw = data.get("EXCEPTION_MESSAGE_B64", "")
        out["exception_message"] = base64.b64decode(raw).decode("utf-8", errors="replace") if raw else ""
    else:
        out["error_class"] = data.get("ERROR_CLASS", "")
        raw = data.get("ERROR_MESSAGE_B64", "")
        out["error_message"] = base64.b64decode(raw).decode("utf-8", errors="replace") if raw else ""
    return out


def resolve_bin(workspace: str, bin_classes: str) -> str:
    return bin_classes if bin_classes.startswith("/") else f"{workspace}/{bin_classes}"


def coverage_from_csv(path: Path, target_class: str) -> dict[str, Any]:
    if not path.exists():
        return {"success": False}
    package, simple = target_class.rsplit(".", 1) if "." in target_class else ("", target_class)
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            row_package = row.get("PACKAGE", "").replace("/", ".")
            row_class = row.get("CLASS", "")
            if row_package == package and row_class in {simple, simple.replace("$", ".")} :
                result: dict[str, Any] = {"success": True}
                for key, prefix in (("INSTRUCTION", "instruction"), ("BRANCH", "branch"), ("LINE", "line")):
                    covered = int(row[f"{key}_COVERED"])
                    missed = int(row[f"{key}_MISSED"])
                    total = covered + missed
                    result[prefix] = {
                        "covered": covered,
                        "missed": missed,
                        "ratio": covered / total if total else 0.0,
                    }
                return result
    return {"success": False}


def search_candidate(
    meta: dict[str, Any],
    method: dict[str, Any],
    values: list[Any],
    setup_actions: list[dict[str, Any]] | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Run one candidate on fixed revision with an optional bounded state setup sequence."""
    ensure_jacoco()
    timeout = timeout or d4j.load_settings()["candidate_timeout_sec"]
    setup_actions = setup_actions or []
    signature = json.dumps(
        [meta["project"], meta["bug_id"], method["name"], method["descriptor"], setup_actions, values],
        sort_keys=True,
    )
    token = hashlib.sha1((signature + f":{os.getpid()}").encode("utf-8")).hexdigest()[:16]
    exec_host = TMP / f"search_{token}.exec"
    csv_host = TMP / f"search_{token}.csv"
    TMP.mkdir(parents=True, exist_ok=True)
    exec_container = f"/workspace/results/tmp/{exec_host.name}"
    csv_container = f"/workspace/results/tmp/{csv_host.name}"
    cp = meta["fixed_cp_test"]
    ws = meta["fixed_workspace"]
    bin_classes = resolve_bin(ws, meta["fixed_bin_classes"])
    types = method["parameter_types"]
    setup_specs = [encode_setup_step(action) for action in setup_actions]
    runner_args = [
        meta["concrete_class"], method["name"], ",".join(types), str(len(setup_specs)),
        *setup_specs, *[b64(v) for v in values],
    ]
    quoted_args = " ".join(shlex.quote(x) for x in runner_args)
    command = (
        f'cd {shlex.quote(ws)} && rm -f {shlex.quote(exec_container)} {shlex.quote(csv_container)} && '
        f'java -javaagent:{AGENT}=destfile={shlex.quote(exec_container)} '
        f'-cp {shlex.quote("/workspace/harness/classes:" + cp)} CandidateRunner {quoted_args}; rc=$?; '
        f'if [ -s {shlex.quote(exec_container)} ]; then '
        f'java -jar {CLI} report {shlex.quote(exec_container)} --classfiles {shlex.quote(bin_classes)} --csv {shlex.quote(csv_container)} >/dev/null 2>&1 || true; fi; '
        'exit $rc'
    )
    start = time.perf_counter()
    result = d4j.docker_exec(command, timeout=timeout, check=False)
    elapsed = time.perf_counter() - start
    oracle = parse_runner_output(result.stdout)
    coverage = coverage_from_csv(csv_host, meta["target_class"])
    branch = coverage.get("branch", {}).get("ratio", 0.0) if coverage.get("success") else 0.0
    instruction = coverage.get("instruction", {}).get("ratio", 0.0) if coverage.get("success") else 0.0
    # Branch coverage dominates; instruction coverage breaks plateaus.
    fitness = branch + instruction * 0.001
    for p in (exec_host, csv_host):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    return {
        "ok": result.returncode == 0 and oracle.get("status") in {"ok", "exception"},
        "returncode": result.returncode,
        "fitness": fitness,
        "coverage": coverage,
        "oracle": oracle,
        "seconds": elapsed,
        "runner_output_tail": result.stdout.splitlines()[-20:],
    }


def _escape_java(value: str, quote: str) -> str:
    out: list[str] = []
    escapes = {"\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r", "\\": "\\\\"}
    for ch in value:
        if ch == quote:
            out.append("\\" + quote)
        elif ch in escapes:
            out.append(escapes[ch])
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append("\\%03o" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def java_literal(type_name: str, value: Any) -> str:
    if type_name == "boolean":
        return "true" if bool(value) else "false"
    if type_name == "byte":
        return f"(byte){int(value)}"
    if type_name == "short":
        return f"(short){int(value)}"
    if type_name == "int":
        return str(int(value))
    if type_name == "long":
        return f"{int(value)}L"
    if type_name == "float":
        v = float(value)
        if math.isnan(v): return "Float.NaN"
        if math.isinf(v): return "Float.POSITIVE_INFINITY" if v > 0 else "Float.NEGATIVE_INFINITY"
        return f"{repr(v)}f"
    if type_name == "double":
        v = float(value)
        if math.isnan(v): return "Double.NaN"
        if math.isinf(v): return "Double.POSITIVE_INFINITY" if v > 0 else "Double.NEGATIVE_INFINITY"
        return repr(v)
    if type_name == "char":
        text = str(value)
        ch = text[0] if text else "\0"
        return "'" + _escape_java(ch, "'") + "'"
    if type_name == "java.lang.String":
        return '"' + _escape_java(str(value), '"') + '"'
    return "null"


def scalar_assert(return_type: str, observed: str, expression: str) -> str:
    if return_type == "boolean":
        return f"assert{'True' if observed.lower() == 'true' else 'False'}({expression});"
    if return_type in {"byte", "short", "int"}:
        return f"assertEquals({int(observed)}, {expression});"
    if return_type == "long":
        return f"assertEquals({int(observed)}L, {expression});"
    if return_type == "float":
        return f"assertEquals({java_literal('float', float(observed))}, {expression}, 0.000001f);"
    if return_type == "double":
        return f"assertEquals({java_literal('double', float(observed))}, {expression}, 1.0e-9);"
    if return_type == "char":
        return f"assertEquals({java_literal('char', observed)}, {expression});"
    if return_type == "java.lang.String":
        return f"assertEquals({java_literal('java.lang.String', observed)}, {expression});"
    escaped = java_literal("java.lang.String", observed)
    return f"assertEquals({escaped}, String.valueOf({expression}));"


def java_source_type(type_name: str) -> str:
    """Convert a JVM binary nested-class name to Java source notation."""
    return type_name.replace("$", ".")


def setup_java_lines(action: dict[str, Any], receiver: str = "obj") -> list[str]:
    args: list[str] = []
    for arg in action.get("arguments", []):
        if arg.get("kind") == "new":
            args.append(f"new {java_source_type(str(arg['type']))}()")
        elif arg.get("kind") == "value":
            args.append(java_literal(str(arg["type"]), arg.get("value")))
        else:
            raise ValueError(f"Unsupported setup argument: {arg}")
    return [f"    {receiver}.{action['name']}({', '.join(args)});"]


def emit_algorithm_test(meta: dict[str, Any], method_results: list[dict[str, Any]], algorithm: str, run_id: str) -> tuple[str, str]:
    safe_alg = re.sub(r"[^A-Za-z0-9_]", "_", algorithm)
    cls = f"Generated_{safe_alg}_{meta['project']}_{meta['bug_id']}_{run_id}".replace("-", "_")
    lines = [
        "import org.junit.Test;",
        "import static org.junit.Assert.*;",
        "",
        f"public class {cls} {{",
    ]
    count = 0
    for item in method_results:
        method = item["method"]
        values = item["values"]
        oracle = item["oracle"]
        setup_actions = item.get("setup_actions", [])
        if oracle.get("status") not in {"ok", "exception"}:
            continue
        count += 1
        args = ", ".join(java_literal(t, v) for t, v in zip(method["parameter_types"], values))
        expression = f"obj.{method['name']}({args})"
        test_name = re.sub(r"[^A-Za-z0-9_]", "_", f"test_{method['name']}_{count}")
        if oracle["status"] == "exception" and oracle.get("exception_class"):
            expected_class = java_literal("java.lang.String", oracle["exception_class"])
            lines.append("  @Test")
            lines.append(f"  public void {test_name}() throws Exception {{")
            lines.append(f"    {java_source_type(meta['concrete_class'])} obj = new {java_source_type(meta['concrete_class'])}();")
            for action in setup_actions:
                lines.extend(setup_java_lines(action))
            lines.append("    Throwable caught = null;")
            lines.append("    try {")
            lines.append(f"      {expression};")
            lines.append("    } catch (Throwable t) {")
            lines.append("      caught = t;")
            lines.append("    }")
            lines.append("    assertNotNull(\"Expected an exception\", caught);")
            lines.append(f"    assertEquals({expected_class}, caught.getClass().getName());")
            lines.append("  }")
            continue
        lines.append("  @Test")
        lines.append(f"  public void {test_name}() throws Exception {{")
        lines.append(f"    {java_source_type(meta['concrete_class'])} obj = new {java_source_type(meta['concrete_class'])}();")
        for action in setup_actions:
            lines.extend(setup_java_lines(action))
        kind = oracle.get("return_kind")
        if kind == "VOID":
            lines.append(f"    {expression};")
        elif kind == "NULL":
            lines.append(f"    assertNull({expression});")
        elif kind == "OBJECT":
            lines.append(f"    assertNotNull({expression});")
        elif kind == "SCALAR":
            lines.append("    " + scalar_assert(method["return_type"], oracle.get("return_value", ""), expression))
        else:
            lines.append(f"    {expression};")
        lines.append("  }")
    lines.append("}")
    if count == 0:
        raise RuntimeError("No valid candidate behaviors were available to emit a JUnit test")
    return cls, "\n".join(lines) + "\n"


def extract_java_code(text: str) -> str:
    match = re.search(r"```java\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip() + "\n"
    match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip() + "\n"
    return text.strip() + "\n"


def count_test_cases_from_java(code: str) -> int:
    """Count JUnit 4 test methods in one generated Java test class."""
    return len(re.findall(r"(?m)^\s*@(?:org\.junit\.)?Test\b", code))


def class_name_from_java(code: str) -> str:
    match = re.search(r"\bpublic\s+class\s+([A-Za-z_$][A-Za-z0-9_$]*)", code)
    if not match:
        match = re.search(r"\bclass\s+([A-Za-z_$][A-Za-z0-9_$]*)", code)
    if not match:
        raise ValueError("Could not find Java class name")
    return match.group(1)


def qualified_class_name_from_java(code: str) -> str:
    simple = class_name_from_java(code)
    package = re.search(r"(?m)^\s*package\s+([A-Za-z_$][A-Za-z0-9_$.]*)\s*;", code)
    return f"{package.group(1)}.{simple}" if package else simple


def _compile_and_run(meta: dict[str, Any], source_container: str, class_name: str, version: str, with_coverage: bool) -> dict[str, Any]:
    cp = meta["fixed_cp_test"] if version == "f" else meta["buggy_cp_test"]
    ws = meta["fixed_workspace"] if version == "f" else meta["buggy_workspace"]
    bin_classes = meta["fixed_bin_classes"] if version == "f" else meta["buggy_bin_classes"]
    token = hashlib.sha1(f"{source_container}:{version}:{time.time_ns()}".encode()).hexdigest()[:12]
    out_dir = f"/workspace/results/tmp/test_{token}_classes"
    exec_path = f"/workspace/results/tmp/test_{token}.exec"
    csv_path = f"/workspace/results/tmp/test_{token}.csv"
    csv_host = TMP / f"test_{token}.csv"
    classfiles = resolve_bin(ws, bin_classes)
    compile_cmd = f'cd {shlex.quote(ws)} && rm -rf {shlex.quote(out_dir)} && mkdir -p {shlex.quote(out_dir)} && javac -cp {shlex.quote(cp)} -d {shlex.quote(out_dir)} {shlex.quote(source_container)}'
    cr = d4j.docker_exec(compile_cmd, timeout=120, check=False)
    if cr.returncode != 0:
        return {"compile_success": False, "test_success": False, "returncode": cr.returncode, "output_tail": cr.stdout.splitlines()[-50:], "coverage": None}
    java = "java "
    if with_coverage:
        java += f"-javaagent:{AGENT}=destfile={shlex.quote(exec_path)} "
    java += f'-cp {shlex.quote(out_dir + ":" + cp)} org.junit.runner.JUnitCore {shlex.quote(class_name)}'
    rr = d4j.docker_exec(f'cd {shlex.quote(ws)} && rm -f {shlex.quote(exec_path)} {shlex.quote(csv_path)} && {java}', timeout=d4j.load_settings()["test_timeout_sec"], check=False)
    coverage = None
    if with_coverage:
        d4j.docker_exec(
            f'if [ -s {shlex.quote(exec_path)} ]; then java -jar {CLI} report {shlex.quote(exec_path)} --classfiles {shlex.quote(classfiles)} --csv {shlex.quote(csv_path)} >/dev/null 2>&1; fi',
            timeout=120,
            check=False,
        )
        coverage = coverage_from_csv(csv_host, meta["target_class"])
    d4j.docker_exec(f'rm -rf {shlex.quote(out_dir)} {shlex.quote(exec_path)} {shlex.quote(csv_path)}', check=False)
    return {
        "compile_success": True,
        "test_success": rr.returncode == 0,
        "returncode": rr.returncode,
        "output_tail": rr.stdout.splitlines()[-50:],
        "coverage": coverage,
    }


def evaluate_test(meta: dict[str, Any], java_path: Path) -> dict[str, Any]:
    ensure_jacoco()
    code = java_path.read_text(encoding="utf-8")
    class_name = qualified_class_name_from_java(code)
    try:
        rel = java_path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        raise ValueError("Generated Java file must be inside the benchmark repository")
    source_container = "/workspace/" + rel.as_posix()
    fixed = _compile_and_run(meta, source_container, class_name, "f", True)
    if not fixed["compile_success"] or not fixed["test_success"]:
        return {
            "valid_test": False,
            "fault_detected": False,
            "fixed": fixed,
            "buggy": None,
            "coverage": fixed.get("coverage"),
        }
    buggy = _compile_and_run(meta, source_container, class_name, "b", False)
    fault = bool(buggy["compile_success"] and not buggy["test_success"])
    return {
        "valid_test": True,
        "fault_detected": fault,
        "fixed": fixed,
        "buggy": buggy,
        "coverage": fixed.get("coverage"),
    }
