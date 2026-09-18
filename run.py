#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import d4j
import evaluate
from algorithms import avm, hill_climbing
from ai import gemini, gpt

METHODS = ("hill_climbing", "avm", "gpt", "gemini")
_GIT_SENTINEL = object()
_GIT_COMMIT: str | None | object = _GIT_SENTINEL
_EXPERIMENT_ID: str | None = None


def load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def git_commit() -> str | None:
    global _GIT_COMMIT
    if _GIT_COMMIT is not _GIT_SENTINEL:
        return _GIT_COMMIT  # type: ignore[return-value]
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        value = r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        value = None
    _GIT_COMMIT = value
    return value


def experiment_id() -> str:
    """Hash code/config/prompt files so results from different experiment definitions are not silently merged."""
    global _EXPERIMENT_ID
    if _EXPERIMENT_ID is not None:
        return _EXPERIMENT_ID
    files = [
        "run.py", "d4j.py", "evaluate.py",
        "algorithms/hill_climbing.py", "algorithms/avm.py",
        "ai/gpt.py", "ai/gemini.py", "harness/CandidateRunner.java",
        "docker/Dockerfile", "docker/compose.yaml", "requirements.txt",
        "config/settings.json", "config/cases.csv", "prompts/unit_test_prompt.txt",
    ]
    h = hashlib.sha256()
    for name in files:
        path = ROOT / name
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    _EXPERIMENT_ID = h.hexdigest()[:16]
    return _EXPERIMENT_ID


def task_path(worker: str, case: dict[str, str], method: str, run_id: str) -> Path:
    return ROOT / "results/workers" / worker / case["project"] / str(case["bug_id"]) / method / f"{run_id}.json"


def permanent_done(path: Path) -> bool:
    """A checkpoint is reusable only for the current experiment definition."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (
            data.get("status") in {"completed", "unsupported"}
            and data.get("experiment_id") == experiment_id()
        )
    except Exception:
        return False


def save_result(path: Path, result: dict[str, Any]) -> None:
    d4j.save_json(path, result)


def task_ids(settings: dict[str, Any], methods: list[str]) -> list[tuple[str, str, int | None]]:
    out: list[tuple[str, str, int | None]] = []
    for method in methods:
        if method in {"hill_climbing", "avm"}:
            for seed in settings["seeds"]:
                out.append((method, f"seed_{seed}", int(seed)))
        else:
            for rep in range(1, int(settings["ai_repetitions"]) + 1):
                out.append((method, f"run_{rep}", rep))
    return out


def case_is_done(worker: str, case: dict[str, str], settings: dict[str, Any], methods: list[str]) -> bool:
    return all(permanent_done(task_path(worker, case, m, run_id)) for m, run_id, _ in task_ids(settings, methods))



def _find_matching_java_delimiter(text: str, start: int, opening: str, closing: str) -> int:
    """Find a matching Java delimiter while ignoring strings and comments."""
    if start < 0 or start >= len(text) or text[start] != opening:
        return -1
    depth = 0
    state = "code"
    i = start
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if ch == '"':
                state = "string"
            elif ch == "'":
                state = "char"
            elif ch == "/" and nxt == "/":
                state = "line_comment"
                i += 1
            elif ch == "/" and nxt == "*":
                state = "block_comment"
                i += 1
            elif ch == opening:
                depth += 1
            elif ch == closing:
                depth -= 1
                if depth == 0:
                    return i
        elif state in {"string", "char"}:
            if ch == "\\":
                i += 1
            elif (state == "string" and ch == '"') or (state == "char" and ch == "'"):
                state = "code"
        elif state == "line_comment" and ch == "\n":
            state = "code"
        elif state == "block_comment" and ch == "*" and nxt == "/":
            state = "code"
            i += 1
        i += 1
    return -1


def compact_source_for_prompt(meta: dict[str, Any], settings: dict[str, Any]) -> str:
    """
    Keep only source declarations for the selected target method names.
    All overloads of a selected name are retained so overloads are never lost.
    If extraction fails, fall back to the old bounded full source.
    """
    source = meta["source_text"]
    max_chars = int(settings.get("ai_source_max_chars", 50000))
    selected = meta["eligible_methods"][: int(settings["max_methods_per_case"])]

    names: list[str] = []
    for method in selected:
        declaration = str(method.get("declaration", ""))
        match = re.search(r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", declaration)
        if match and match.group(1) not in names:
            names.append(match.group(1))
    if not names:
        return source[:max_chars]

    ranges: list[tuple[int, int]] = []
    for name in names:
        for match in re.finditer(rf"\b{re.escape(name)}\s*\(", source):
            open_paren = source.find("(", match.start(), match.end())
            close_paren = _find_matching_java_delimiter(source, open_paren, "(", ")")
            if close_paren < 0:
                continue

            # Only accept a declaration. A normal call site does not have a
            # public/protected modifier since the previous statement/block.
            start = max(
                source.rfind(";", 0, match.start()),
                source.rfind("{", 0, match.start()),
                source.rfind("}", 0, match.start()),
            ) + 1
            prefix = source[start:match.start()]
            if not re.search(r"\b(?:public|protected)\b", prefix) or "=" in prefix:
                continue

            next_brace = source.find("{", close_paren + 1)
            next_semi = source.find(";", close_paren + 1)
            structural = min(x for x in (next_brace, next_semi) if x >= 0) if (next_brace >= 0 or next_semi >= 0) else -1
            if structural < 0:
                continue

            # Reject expressions whose next structural token only appears much
            # later; method declarations may only have whitespace/throws here.
            between = source[close_paren + 1:structural]
            if "=" in between:
                continue

            if source[structural] == ";":
                end = structural + 1
            else:
                end = _find_matching_java_delimiter(source, structural, "{", "}")
                if end < 0:
                    continue
                end += 1
            ranges.append((start, end))

    if not ranges:
        return source[:max_chars]

    ranges = sorted(set(ranges))
    package_imports = "\n".join(
        line for line in source.splitlines()
        if line.strip().startswith("package ") or line.strip().startswith("import ")
    )
    pieces = [
        "// Compact source: selected target methods (including overloads).",
        "// Public API sections elsewhere in this prompt list callable setup methods.",
    ]
    if package_imports:
        pieces.extend(["", package_imports])

    remaining = max_chars - len("\n".join(pieces))
    per_method = max(1000, min(8000, remaining // max(1, len(ranges))))
    marker = "\n// ... method source truncated for token budget ..."
    for index, (start, end) in enumerate(ranges, 1):
        label = f"// ---- selected method source {index} ----"
        snippet = source[start:end].strip()
        allowance = min(per_method, max_chars - len("\n".join(pieces)) - len(label) - 3)
        if allowance <= 0:
            break
        if len(snippet) > allowance:
            body_allowance = max(0, allowance - len(marker))
            snippet = snippet[:body_allowance] + marker
        pieces.extend(["", label, snippet])

    return "\n".join(pieces)

def build_prompt(meta: dict[str, Any], settings: dict[str, Any]) -> str:
    template = (ROOT / "prompts/unit_test_prompt.txt").read_text(encoding="utf-8")
    return template.format(
        project=meta["project"],
        bug_id=meta["bug_id"],
        target_class=meta["target_class"],
        concrete_class=meta["concrete_class"],
        prompt_version=settings["prompt_version"],
        public_api=meta["public_api_text"],
        concrete_api=meta.get("concrete_api_text", meta["public_api_text"]),
        selected_methods="\n".join(
            f"- {m['declaration']} descriptor={m['descriptor']}"
            for m in meta["eligible_methods"][: int(settings["max_methods_per_case"])]
        ) or "- none",
        source=compact_source_for_prompt(meta, settings),
    )


def generated_dir(worker: str, case: dict[str, str], method: str, run_id: str) -> Path:
    path = ROOT / "generated_tests" / worker / case["project"] / str(case["bug_id"]) / method / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def common_record(worker: str, case: dict[str, str], method: str, run_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "project": case["project"],
        "bug_id": int(case["bug_id"]),
        "method": method,
        "run_id": run_id,
        "worker": worker,
        "git_commit": git_commit(),
        "experiment_id": experiment_id(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "target_class": meta["target_class"],
        "concrete_class": meta["concrete_class"],
        "target_selection_source": meta["target_selection_source"],
    }


def run_algorithm(worker: str, case: dict[str, str], meta: dict[str, Any], method: str, run_id: str, seed: int, settings: dict[str, Any]) -> dict[str, Any]:
    record = common_record(worker, case, method, run_id, meta)
    record["seed"] = seed
    if not meta.get("concrete_instantiable", True):
        record.update({
            "status": "unsupported",
            "error": "Configured concrete_class is abstract/non-public or has no public no-arg constructor; fill concrete_class in config/cases.csv",
            "test_case_count": 0,
        })
        return record
    if not meta["eligible_methods"]:
        record.update({
            "status": "unsupported",
            "error": "No public methods with supported primitive/String arguments",
            "test_case_count": 0,
        })
        return record

    total_start = time.perf_counter()
    generation_start = time.perf_counter()
    generator = hill_climbing.generate if method == "hill_climbing" else avm.generate
    generated = generator(meta, seed, settings)
    record["search"] = generated
    if not generated["method_results"]:
        record.update({
            "status": "unsupported",
            "error": "No valid candidates. Check concrete_class/no-arg constructor or supported methods.",
            "test_case_count": 0,
            "generation_time_sec": time.perf_counter() - generation_start,
            "evaluation_time_sec": 0.0,
            "duration_sec": time.perf_counter() - total_start,
        })
        return record
    try:
        class_name, code = evaluate.emit_algorithm_test(meta, generated["method_results"], method, run_id)
    except Exception as exc:
        record.update({
            "status": "error",
            "error": f"emit_test: {exc}",
            "test_case_count": 0,
            "generation_time_sec": time.perf_counter() - generation_start,
            "evaluation_time_sec": 0.0,
            "duration_sec": time.perf_counter() - total_start,
        })
        return record
    out_dir = generated_dir(worker, case, method, run_id)
    java_path = out_dir / f"{class_name}.java"
    java_path.write_text(code, encoding="utf-8")
    record["test_case_count"] = evaluate.count_test_cases_from_java(code)
    record["generation_time_sec"] = time.perf_counter() - generation_start

    evaluation_start = time.perf_counter()
    try:
        evaluation = evaluate.evaluate_test(meta, java_path)
    except Exception as exc:
        record.update({
            "status": "error",
            "error": f"evaluate: {exc}",
            "generated_test": str(java_path.relative_to(ROOT)),
            "evaluation_time_sec": time.perf_counter() - evaluation_start,
            "duration_sec": time.perf_counter() - total_start,
        })
        return record
    record["evaluation_time_sec"] = time.perf_counter() - evaluation_start
    coverage = evaluation.get("coverage") or {}
    final_status = "completed" if (not evaluation["valid_test"] or coverage.get("success") is True) else "error"
    record.update({
        "status": final_status,
        "error": None if final_status == "completed" else "Final JaCoCo coverage was not collected successfully",
        "generated_test": str(java_path.relative_to(ROOT)),
        "valid_test": evaluation["valid_test"],
        "fault_detected": evaluation["fault_detected"],
        "coverage": evaluation.get("coverage"),
        "evaluation": evaluation,
        "duration_sec": time.perf_counter() - total_start,
    })
    return record

def run_ai(worker: str, case: dict[str, str], meta: dict[str, Any], method: str, run_id: str, repetition: int, settings: dict[str, Any]) -> dict[str, Any]:
    record = common_record(worker, case, method, run_id, meta)
    record["repetition"] = repetition
    record["prompt_version"] = settings["prompt_version"]
    total_start = time.perf_counter()
    generation_start = time.perf_counter()
    prompt = build_prompt(meta, settings)
    out_dir = generated_dir(worker, case, method, run_id)
    prompt_path = out_dir / "prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    provider = gpt.generate if method == "gpt" else gemini.generate
    response = provider(prompt, settings)
    record["provider"] = {k: v for k, v in response.items() if k != "text"}
    record["prompt_file"] = str(prompt_path.relative_to(ROOT))
    if response["status"] == "paused_quota":
        record.update({
            "status": "paused_quota",
            "error": response.get("error"),
            "test_case_count": 0,
            "generation_time_sec": time.perf_counter() - generation_start,
            "evaluation_time_sec": 0.0,
            "duration_sec": time.perf_counter() - total_start,
        })
        return record
    if response["status"] != "generated":
        record.update({
            "status": "error",
            "error": response.get("error", "AI generation failed"),
            "test_case_count": 0,
            "generation_time_sec": time.perf_counter() - generation_start,
            "evaluation_time_sec": 0.0,
            "duration_sec": time.perf_counter() - total_start,
        })
        return record
    response_path = out_dir / "response.txt"
    response_path.write_text(response["text"], encoding="utf-8")
    record["response_file"] = str(response_path.relative_to(ROOT))
    try:
        code = evaluate.extract_java_code(response["text"])
        class_name = evaluate.class_name_from_java(code)
        java_path = out_dir / f"{class_name}.java"
        java_path.write_text(code, encoding="utf-8")
        record["test_case_count"] = evaluate.count_test_cases_from_java(code)
        record["generation_time_sec"] = time.perf_counter() - generation_start
    except Exception as exc:
        record.update({
            "status": "error",
            "error": f"parse: {exc}",
            "test_case_count": 0,
            "generation_time_sec": time.perf_counter() - generation_start,
            "evaluation_time_sec": 0.0,
            "duration_sec": time.perf_counter() - total_start,
        })
        return record

    evaluation_start = time.perf_counter()
    try:
        evaluation = evaluate.evaluate_test(meta, java_path)
    except Exception as exc:
        record.update({
            "status": "error",
            "error": f"evaluate: {exc}",
            "generated_test": str(java_path.relative_to(ROOT)),
            "evaluation_time_sec": time.perf_counter() - evaluation_start,
            "duration_sec": time.perf_counter() - total_start,
        })
        return record
    record["evaluation_time_sec"] = time.perf_counter() - evaluation_start
    coverage = evaluation.get("coverage") or {}
    final_status = "completed" if (not evaluation["valid_test"] or coverage.get("success") is True) else "error"
    record.update({
        "status": final_status,
        "error": None if final_status == "completed" else "Final JaCoCo coverage was not collected successfully",
        "generated_test": str(java_path.relative_to(ROOT)),
        "valid_test": evaluation["valid_test"],
        "fault_detected": evaluation["fault_detected"],
        "coverage": evaluation.get("coverage"),
        "evaluation": evaluation,
        "duration_sec": time.perf_counter() - total_start,
    })
    return record

def parse_shard(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        left, right = value.split("/", 1)
        i, n = int(left), int(right)
    except Exception as exc:
        raise argparse.ArgumentTypeError("--shard must look like 1/3") from exc
    if n < 1 or i < 1 or i > n:
        raise argparse.ArgumentTypeError("--shard must satisfy 1 <= index <= total")
    return i, n


def parse_case_range(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        start_text, end_text = value.split("-", 1)
        start, end = int(start_text), int(end_text)
    except Exception as exc:
        raise argparse.ArgumentTypeError(
            "--case-range must look like 1-285"
        ) from exc

    if start < 1 or end < start:
        raise argparse.ArgumentTypeError(
            "--case-range must satisfy 1 <= start <= end"
        )

    return start, end


def select_cases(args: argparse.Namespace) -> list[dict[str, str]]:
    cases = sorted(d4j.load_cases(), key=lambda r: (r["project"], int(r["bug_id"])))

    case_range = parse_case_range(args.case_range)
    if case_range:
        start, end = case_range
        cases = cases[start - 1:end]

    if args.project:
        cases = [c for c in cases if c["project"] == args.project]
    if args.bug is not None:
        cases = [c for c in cases if int(c["bug_id"]) == args.bug]
    shard = parse_shard(args.shard)
    if shard:
        i, n = shard
        cases = [c for index, c in enumerate(cases) if index % n == i - 1]
    if args.limit:
        cases = cases[: args.limit]
    return cases


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Simple resumable Defects4J benchmark runner")
    ap.add_argument("--project")
    ap.add_argument("--bug", type=int)
    ap.add_argument("--all", action="store_true", help="Run all enabled rows in config/cases.csv")
    ap.add_argument("--shard", help="Split cases deterministically, e.g. 1/3")
    ap.add_argument(
        "--case-range",
        help="Run a 1-based inclusive range of enabled cases, e.g. 1-285",
    )
    ap.add_argument("--worker", default=safe_name(socket.gethostname()), help="Worker/member name stored with results")
    ap.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true", help="Rerun even completed checkpoints")
    args = ap.parse_args()
    if (
        not args.all
        and not args.project
        and args.bug is None
        and not args.shard
        and not args.case_range
    ):
        ap.error("Use --all, --project/--bug, --shard, or --case-range")

    settings = d4j.load_settings()
    cases = select_cases(args)
    if not cases:
        raise SystemExit("No enabled cases matched")
    worker = safe_name(args.worker)
    print(f"Worker={worker} cases={len(cases)} methods={','.join(args.methods)}")
    paused_providers: set[str] = set()
    if "gpt" in args.methods and (not os.getenv("GPT_API_KEY", "").strip() or not str(settings.get("gpt_model", "")).strip()):
        paused_providers.add("gpt")
        print("GPT deferred: GPT_API_KEY or config/settings.json gpt_model is not configured. Other methods will continue.")
    if "gemini" in args.methods and (not os.getenv("GEMINI_API_KEY", "").strip() or not str(settings.get("gemini_model", "")).strip()):
        paused_providers.add("gemini")
        print("Gemini deferred: GEMINI_API_KEY or config/settings.json gemini_model is not configured. Other methods will continue.")

    for c_index, case in enumerate(cases, 1):
        label = f"{case['project']}-{case['bug_id']}"
        if not args.force and case_is_done(worker, case, settings, args.methods):
            print(f"[{c_index}/{len(cases)}] {label}: already complete -> skip")
            continue
        print(f"[{c_index}/{len(cases)}] Preparing {label}")
        try:
            meta = d4j.prepare_case(case)
        except Exception as exc:
            print(f"  PREP ERROR: {exc}")
            for method, run_id, seed_or_rep in task_ids(settings, args.methods):
                path = task_path(worker, case, method, run_id)
                if not args.force and permanent_done(path):
                    continue
                result = {
                    "project": case["project"],
                    "bug_id": int(case["bug_id"]),
                    "method": method,
                    "run_id": run_id,
                    "worker": worker,
                    "git_commit": git_commit(),
                    "experiment_id": experiment_id(),
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "status": "error",
                    "error": f"prepare_case: {exc}",
                }
                if method in {"hill_climbing", "avm"}:
                    result["seed"] = int(seed_or_rep)
                else:
                    result["repetition"] = int(seed_or_rep)
                save_result(path, result)
            continue

        for method, run_id, seed_or_rep in task_ids(settings, args.methods):
            path = task_path(worker, case, method, run_id)
            if not args.force and permanent_done(path):
                print(f"  {method}/{run_id}: completed -> skip")
                continue
            if method in paused_providers:
                print(f"  {method}/{run_id}: deferred (quota paused this process)")
                continue
            print(f"  {method}/{run_id}: running")
            try:
                if method in {"hill_climbing", "avm"}:
                    result = run_algorithm(worker, case, meta, method, run_id, int(seed_or_rep), settings)
                else:
                    result = run_ai(worker, case, meta, method, run_id, int(seed_or_rep), settings)
            except KeyboardInterrupt:
                print("\nInterrupted. Existing checkpoints are safe; run the same command again to resume.")
                raise
            except Exception as exc:
                result = common_record(worker, case, method, run_id, meta)
                result.update({"status": "error", "error": str(exc)})
            save_result(path, result)
            print(f"    status={result.get('status')} valid={result.get('valid_test')} fault={result.get('fault_detected')}")
            if result.get("status") == "paused_quota" and method in {"gpt", "gemini"}:
                paused_providers.add(method)
                print(f"    {method} quota/rate limit persisted. Other methods continue; rerun later to resume {method}.")

    print("Done. Re-running the same command resumes from unfinished/error/quota-paused tasks.")


if __name__ == "__main__":
    main()
