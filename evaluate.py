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
from construction import encode_plan

ROOT = Path(__file__).resolve().parent
TMP = ROOT / "results/tmp"
AGENT = "/workspace/tools/jacoco/jacocoagent.jar"
CLI = "/workspace/tools/jacoco/jacococli.jar"
JUNIT4_CP = (
    "/opt/defects4j/framework/projects/lib/"
    "junit-4.12-hamcrest-1.3.jar"
)
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
        elif arg.get("kind") == "plan":
            fields.append("P:" + encode_plan(arg["plan"]))
        else:
            raise ValueError(f"Unsupported setup argument: {arg}")
    raw = "\t".join(fields)
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def parse_runner_output(text: str) -> dict[str, Any]:
    data: dict[str, str] = {}

    allowed_keys = {
        "STATUS",
        "RETURN_TYPE",
        "RETURN_KIND",
        "RETURN_B64",
        "ARRAY_COMPONENT_TYPE",
        "ARRAY_LENGTH",
        "STATE_METHOD",
        "STATE_RETURN_TYPE",
        "STATE_KIND",
        "STATE_VALUE_B64",
        "EXCEPTION_CLASS",
        "EXCEPTION_MESSAGE_B64",
        "ERROR_CLASS",
        "ERROR_MESSAGE_B64",
    }

    for line in text.splitlines():
        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        if key in allowed_keys or re.fullmatch(
            r"ARRAY_ITEM_\d+_B64",
            key,
        ):
            data[key] = value

    status = data.get("STATUS", "ERROR")
    out: dict[str, Any] = {
        "status": status.lower()
    }

    if status == "OK":
        out["return_type"] = data.get(
            "RETURN_TYPE",
            "",
        )
        out["return_kind"] = data.get(
            "RETURN_KIND",
            "",
        )

        raw = data.get("RETURN_B64", "")
        out["return_value"] = (
            base64.b64decode(raw).decode(
                "utf-8",
                errors="replace",
            )
            if raw
            else ""
        )

        if out["return_kind"] == "ARRAY":
            try:
                array_length = int(
                    data.get("ARRAY_LENGTH", "0")
                )
            except ValueError:
                array_length = 0

            array_values = []

            for index in range(array_length):
                encoded = data.get(
                    f"ARRAY_ITEM_{index}_B64",
                    "",
                )

                array_values.append(
                    base64.b64decode(encoded).decode(
                        "utf-8",
                        errors="replace",
                    )
                    if encoded
                    else ""
                )

            out["array_component_type"] = data.get(
                "ARRAY_COMPONENT_TYPE",
                "",
            )
            out["array_values"] = array_values

        if out["return_kind"] == "VOID_STATE":
            out["state_method"] = data.get(
                "STATE_METHOD",
                "",
            )
            out["state_return_type"] = data.get(
                "STATE_RETURN_TYPE",
                "",
            )
            out["state_kind"] = data.get(
                "STATE_KIND",
                "",
            )

            state_raw = data.get(
                "STATE_VALUE_B64",
                "",
            )
            out["state_value"] = (
                base64.b64decode(state_raw).decode(
                    "utf-8",
                    errors="replace",
                )
                if state_raw
                else ""
            )

    elif status == "EXCEPTION":
        out["exception_class"] = data.get(
            "EXCEPTION_CLASS",
            "",
        )

        raw = data.get(
            "EXCEPTION_MESSAGE_B64",
            "",
        )
        out["exception_message"] = (
            base64.b64decode(raw).decode(
                "utf-8",
                errors="replace",
            )
            if raw
            else ""
        )

    else:
        out["error_class"] = data.get(
            "ERROR_CLASS",
            "",
        )

        raw = data.get(
            "ERROR_MESSAGE_B64",
            "",
        )
        out["error_message"] = (
            base64.b64decode(raw).decode(
                "utf-8",
                errors="replace",
            )
            if raw
            else ""
        )

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

    setup_specs = [
        encode_setup_step(action)
        for action in setup_actions
    ]
    construction_plan = meta.get("construction_plan")
    if construction_plan:
        runner_args = [
            "--plan",
            encode_plan(construction_plan),
            meta["concrete_class"],
            method["name"],
            ",".join(types),
            str(len(setup_specs)),
            *setup_specs,
            *[b64(value) for value in values],
        ]
    else:
        constructor = meta.get("receiver_constructor") or {
            "parameter_types": [],
            "values": [],
        }
        constructor_types = list(constructor.get("parameter_types", []))
        constructor_values = list(constructor.get("values", []))
        if len(constructor_types) != len(constructor_values):
            raise ValueError("Receiver constructor type/value count mismatch")
        runner_args = [
            meta["concrete_class"],
            ",".join(constructor_types),
            str(len(constructor_types)),
            method["name"],
            ",".join(types),
            str(len(setup_specs)),
            *[b64(value) for value in constructor_values],
            *setup_specs,
            *[b64(value) for value in values],
        ]
    quoted_args = " ".join(shlex.quote(x) for x in runner_args)
    inner_timeout = max(1, int(math.ceil(float(timeout))))
    command = (
        f'cd {shlex.quote(ws)} && rm -f {shlex.quote(exec_container)} {shlex.quote(csv_container)} && '
        f'timeout --signal=TERM --kill-after=1s {inner_timeout}s '
        f'java -javaagent:{AGENT}=destfile={shlex.quote(exec_container)} '
        f'-cp {shlex.quote("/workspace/harness/classes:" + cp)} CandidateRunner {quoted_args}; rc=$?; '
        f'if [ -s {shlex.quote(exec_container)} ]; then '
        f'java -jar {CLI} report {shlex.quote(exec_container)} --classfiles {shlex.quote(bin_classes)} --csv {shlex.quote(csv_container)} >/dev/null 2>&1 || true; fi; '
        'exit $rc'
    )
    start = time.perf_counter()
    result = d4j.docker_exec(command, timeout=float(timeout) + 2.0, check=False)
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

    boxed = {
        "java.lang.Byte": "byte",
        "java.lang.Short": "short",
        "java.lang.Integer": "int",
        "java.lang.Long": "long",
        "java.lang.Float": "float",
        "java.lang.Double": "double",
        "java.lang.Boolean": "boolean",
        "java.lang.Character": "char",
    }
    if type_name in boxed:
        return java_literal(boxed[type_name], value)

    if type_name == "java.lang.Comparable":
        string_literal = (
            '"'
            + _escape_java(str(value), '"')
            + '"'
        )
        return f"(java.lang.Comparable){string_literal}"

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

def array_assert(
    return_type: str,
    observed_values: list[str],
    expression: str,
) -> str:
    if not return_type.endswith("[]"):
        raise ValueError(
            f"Expected an array return type: {return_type}"
        )

    component_type = return_type[:-2]

    supported_components = {
        "byte",
        "short",
        "int",
        "long",
        "float",
        "double",
        "boolean",
        "char",
    }

    if component_type not in supported_components:
        raise ValueError(
            "Unsupported array component type: "
            f"{component_type}"
        )

    values = ", ".join(
        java_literal(component_type, value)
        for value in observed_values
    )

    expected = (
        f"new {component_type}[] "
        f"{{{values}}}"
    )

    if component_type == "float":
        return (
            f"assertArrayEquals("
            f"{expected}, {expression}, 0.000001f);"
        )

    if component_type == "double":
        return (
            f"assertArrayEquals("
            f"{expected}, {expression}, 1.0e-9);"
        )

    return (
        f"assertArrayEquals("
        f"{expected}, {expression});"
    )

def java_source_type(type_name: str) -> str:
    """Convert a JVM binary nested-class name to Java source notation."""
    return type_name.replace("$", ".")


def construction_java_expression(plan: dict[str, Any]) -> str:
    strategy = plan.get("strategy")
    type_name = str(plan.get("type", ""))
    if strategy == "literal":
        return java_literal(str(plan.get("value_type", type_name)), plan.get("value"))
    if strategy == "empty_array":
        dimensions = 0
        base = type_name
        while base.endswith("[]"):
            dimensions += 1
            base = base[:-2]
        if dimensions == 0:
            raise ValueError(f"Invalid array construction type: {type_name}")
        return f"new {java_source_type(base)}[0]" + "[]" * (dimensions - 1)
    if strategy == "enum_first":
        return f"{java_source_type(type_name)}.values()[0]"

    arguments = ", ".join(
        construction_java_expression(child)
        for child in plan.get("arguments", [])
    )
    owner = java_source_type(str(plan.get("class_name", type_name)))
    if strategy == "constructor":
        binary_owner = str(plan.get("class_name", type_name))
        parameter_types = list(plan.get("parameter_types", []))
        children = list(plan.get("arguments", []))
        if "$" in binary_owner:
            enclosing = binary_owner.rsplit("$", 1)[0]
            if parameter_types and parameter_types[0] == enclosing and children:
                enclosing_expression = construction_java_expression(children[0])
                inner_simple = binary_owner.rsplit("$", 1)[1].replace("$", ".")
                inner_arguments = ", ".join(
                    construction_java_expression(child) for child in children[1:]
                )
                return f"{enclosing_expression}.new {inner_simple}({inner_arguments})"
        return f"new {owner}({arguments})"
    if strategy == "static_factory":
        return f"{owner}.{plan['method_name']}({arguments})"
    if strategy == "static_field":
        return f"{owner}.{plan['field_name']}"
    raise ValueError(f"Unsupported construction strategy: {strategy}")

def receiver_java_line(meta: dict[str, Any]) -> str:
    construction_plan = meta.get("construction_plan")
    if construction_plan:
        class_name = java_source_type(meta["concrete_class"])
        return f"    {class_name} obj = {construction_java_expression(construction_plan)};"

    constructor = meta.get("receiver_constructor") or {
        "parameter_types": [],
        "values": [],
    }

    parameter_types = list(
        constructor.get("parameter_types", [])
    )

    values = list(
        constructor.get("values", [])
    )

    if len(parameter_types) != len(values):
        raise ValueError(
            "Receiver constructor type/value count mismatch"
        )

    arguments = ", ".join(
        java_literal(type_name, value)
        for type_name, value in zip(
            parameter_types,
            values,
        )
    )

    class_name = java_source_type(
        meta["concrete_class"]
    )

    return (
        f"    {class_name} obj = "
        f"new {class_name}({arguments});"
    )

def setup_java_lines(action: dict[str, Any], receiver: str = "obj") -> list[str]:
    args: list[str] = []
    for arg in action.get("arguments", []):
        if arg.get("kind") == "new":
            args.append(f"new {java_source_type(str(arg['type']))}()")
        elif arg.get("kind") == "value":
            args.append(java_literal(str(arg["type"]), arg.get("value")))
        elif arg.get("kind") == "plan":
            args.append(construction_java_expression(arg["plan"]))
        else:
            raise ValueError(f"Unsupported setup argument: {arg}")
    return [f"    {receiver}.{action['name']}({', '.join(args)});"]

def setup_has_fresh_object_arguments(setup_actions: list[dict[str, Any]],) -> bool:
    return any(
        argument.get("kind") in {"new", "plan"}
        for action in setup_actions
        for argument in action.get("arguments", [])
    )

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
            lines.append(receiver_java_line(meta))
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
        lines.append(receiver_java_line(meta))
        for action in setup_actions:
            lines.extend(setup_java_lines(action))
        kind = oracle.get("return_kind")
        if kind == "VOID":
            lines.append(f"    {expression};")
        elif kind == "VOID_STATE":
            lines.append(f"    {expression};")
            state_expression = (
                f"obj.{oracle['state_method']}()"
            )

            if oracle.get("state_kind") == "NULL":
                lines.append(
                    f"    assertNull({state_expression});"
                )
            else:
                lines.append(
                    "    "
                    + scalar_assert(
                        oracle["state_return_type"],
                        oracle.get("state_value", ""),
                        state_expression,
                    )
                )
        elif kind == "NULL":
            lines.append(
                f"    assertNull({expression});"
            )
        elif kind == "SAME_RECEIVER":
            lines.append(
                f"    assertSame(obj, {expression});"
            )
        elif kind == "ARRAY":
            if setup_has_fresh_object_arguments(
                setup_actions
            ):
                lines.append(
                    f"    assertNotNull({expression});"
                )
            else:
                lines.append(
                    "    "
                    + array_assert(
                        method["return_type"],
                        oracle.get("array_values", []),
                        expression,
                    )
                )
        elif kind == "OBJECT":
            lines.append(
                f"    assertNotNull({expression});"
            )
        elif kind == "SCALAR":
            lines.append(
                "    "
                + scalar_assert(
                    method["return_type"],
                    oracle.get("return_value", ""),
                    expression,
                )
            )
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


def _remaining_timeout(deadline: float | None, cap: float) -> float:
    if deadline is None:
        return cap
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("algorithm case time budget exhausted")
    return max(0.25, min(cap, remaining))


def _compile_and_run(
    meta: dict[str, Any],
    source_container: str,
    class_name: str,
    version: str,
    with_coverage: bool,
    deadline: float | None = None,
) -> dict[str, Any]:
    project_cp = (meta["fixed_cp_test"] if version == "f" else meta["buggy_cp_test"])
    # Generated tests use JUnit 4 even when the Defects4J project itself uses
    # JUnit 3. Put JUnit 4 first so org.junit.Test and Assert resolve correctly.
    cp = f"{JUNIT4_CP}:{project_cp}"
    ws = meta["fixed_workspace"] if version == "f" else meta["buggy_workspace"]
    bin_classes = meta["fixed_bin_classes"] if version == "f" else meta["buggy_bin_classes"]
    token = hashlib.sha1(f"{source_container}:{version}:{time.time_ns()}".encode()).hexdigest()[:12]
    out_dir = f"/workspace/results/tmp/test_{token}_classes"
    exec_path = f"/workspace/results/tmp/test_{token}.exec"
    csv_path = f"/workspace/results/tmp/test_{token}.csv"
    csv_host = TMP / f"test_{token}.csv"
    classfiles = resolve_bin(ws, bin_classes)
    compile_cmd = f'cd {shlex.quote(ws)} && rm -rf {shlex.quote(out_dir)} && mkdir -p {shlex.quote(out_dir)} && javac -cp {shlex.quote(cp)} -d {shlex.quote(out_dir)} {shlex.quote(source_container)}'
    cr = d4j.docker_exec(
        compile_cmd,
        timeout=_remaining_timeout(deadline, 120),
        check=False,
    )
    if cr.returncode != 0:
        return {"compile_success": False, "test_success": False, "returncode": cr.returncode, "output_tail": cr.stdout.splitlines()[-50:], "coverage": None}
    java = "java "
    if with_coverage:
        java += f"-javaagent:{AGENT}=destfile={shlex.quote(exec_path)} "
    java += f'-cp {shlex.quote(out_dir + ":" + cp)} org.junit.runner.JUnitCore {shlex.quote(class_name)}'
    rr = d4j.docker_exec(
        f'cd {shlex.quote(ws)} && rm -f {shlex.quote(exec_path)} {shlex.quote(csv_path)} && {java}',
        timeout=_remaining_timeout(deadline, float(d4j.load_settings()["test_timeout_sec"])),
        check=False,
    )
    coverage = None
    if with_coverage:
        d4j.docker_exec(
            f'if [ -s {shlex.quote(exec_path)} ]; then java -jar {CLI} report {shlex.quote(exec_path)} --classfiles {shlex.quote(classfiles)} --csv {shlex.quote(csv_path)} >/dev/null 2>&1; fi',
            timeout=_remaining_timeout(deadline, 120),
            check=False,
        )
        coverage = coverage_from_csv(csv_host, meta["target_class"])
    d4j.docker_exec(
        f'rm -rf {shlex.quote(out_dir)} {shlex.quote(exec_path)} {shlex.quote(csv_path)}',
        timeout=_remaining_timeout(deadline, 15),
        check=False,
    )
    return {
        "compile_success": True,
        "test_success": rr.returncode == 0,
        "returncode": rr.returncode,
        "output_tail": rr.stdout.splitlines()[-50:],
        "coverage": coverage,
    }


def evaluate_test(
    meta: dict[str, Any],
    java_path: Path,
    deadline: float | None = None,
) -> dict[str, Any]:
    ensure_jacoco()
    code = java_path.read_text(encoding="utf-8")
    class_name = qualified_class_name_from_java(code)
    try:
        rel = java_path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        raise ValueError("Generated Java file must be inside the benchmark repository")
    source_container = "/workspace/" + rel.as_posix()
    fixed = _compile_and_run(meta, source_container, class_name, "f", True, deadline)
    if not fixed["compile_success"] or not fixed["test_success"]:
        return {
            "valid_test": False,
            "fault_detected": False,
            "fixed": fixed,
            "buggy": None,
            "coverage": fixed.get("coverage"),
        }
    buggy = _compile_and_run(meta, source_container, class_name, "b", False, deadline)
    fault = bool(buggy["compile_success"] and not buggy["test_success"])
    return {
        "valid_test": True,
        "fault_detected": fault,
        "fixed": fixed,
        "buggy": buggy,
        "coverage": fixed.get("coverage"),
    }
