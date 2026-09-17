#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def ratio(result: dict[str, Any], key: str) -> float | None:
    cov = result.get("coverage") or {}
    metric = cov.get(key) or {}
    value = metric.get("ratio")
    return float(value) if value is not None else None


def test_count(result: dict[str, Any]) -> int:
    try:
        return max(0, int(result.get("test_case_count") or 0))
    except (TypeError, ValueError):
        return 0


def per_test(value: float | int | None, count: int) -> float | None:
    if value is None or count <= 0:
        return None
    return float(value) / count


def load_results(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if all(k in data for k in ("project", "bug_id", "method", "status")):
            try:
                rel = str(path.relative_to(ROOT))
            except ValueError:
                rel = str(path)
            data["_path"] = rel
            rows.append(data)
    return rows


def identity(r: dict[str, Any]) -> tuple[Any, ...]:
    return (r.get("project"), int(r.get("bug_id")), r.get("method"), r.get("run_id"))


def deduplicate(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        grouped[identity(r)].append(r)
    selected = []
    duplicates = []
    rank = {"completed": 4, "unsupported": 3, "paused_quota": 2, "error": 1}
    for _, items in grouped.items():
        if len(items) > 1:
            duplicates.extend(items)
        best = max(items, key=lambda r: (rank.get(r.get("status"), 0), str(r.get("timestamp_utc", ""))))
        selected.append(best)
    return selected, duplicates


def write_duplicates(rows: list[dict[str, Any]], path: Path) -> None:
    fields = ["project", "bug_id", "method", "run_id", "worker", "experiment_id", "status", "timestamp_utc", "result_file"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in sorted(rows, key=lambda x: tuple(str(v) for v in identity(x)) + (str(x.get("worker")),)):
            w.writerow({
                "project": r.get("project"), "bug_id": r.get("bug_id"), "method": r.get("method"),
                "run_id": r.get("run_id"), "worker": r.get("worker"), "experiment_id": r.get("experiment_id"), "status": r.get("status"),
                "timestamp_utc": r.get("timestamp_utc"), "result_file": r.get("_path"),
            })


def write_all(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "project", "bug_id", "method", "run_id", "worker", "experiment_id", "status", "valid_test", "fault_detected",
        "test_case_count", "instruction_coverage", "branch_coverage", "line_coverage",
        "instruction_coverage_per_test", "branch_coverage_per_test", "line_coverage_per_test",
        "generation_time_sec", "evaluation_time_sec", "duration_sec",
        "generation_time_per_test", "evaluation_time_per_test", "duration_per_test",
        "target_class", "concrete_class", "target_selection_source", "git_commit", "generated_test", "error", "result_file"
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in sorted(rows, key=lambda x: tuple(str(v) for v in identity(x))):
            count = test_count(r)
            ins = ratio(r, "instruction")
            br = ratio(r, "branch")
            ln = ratio(r, "line")
            gen = r.get("generation_time_sec")
            ev = r.get("evaluation_time_sec")
            dur = r.get("duration_sec")
            w.writerow({
                "project": r.get("project"), "bug_id": r.get("bug_id"), "method": r.get("method"),
                "run_id": r.get("run_id"), "worker": r.get("worker"), "experiment_id": r.get("experiment_id"), "status": r.get("status"),
                "valid_test": r.get("valid_test"), "fault_detected": r.get("fault_detected"),
                "test_case_count": count,
                "instruction_coverage": ins, "branch_coverage": br, "line_coverage": ln,
                "instruction_coverage_per_test": per_test(ins, count),
                "branch_coverage_per_test": per_test(br, count),
                "line_coverage_per_test": per_test(ln, count),
                "generation_time_sec": gen, "evaluation_time_sec": ev, "duration_sec": dur,
                "generation_time_per_test": per_test(gen, count),
                "evaluation_time_per_test": per_test(ev, count),
                "duration_per_test": per_test(dur, count),
                "target_class": r.get("target_class"), "concrete_class": r.get("concrete_class"),
                "target_selection_source": r.get("target_selection_source"), "git_commit": r.get("git_commit"),
                "generated_test": r.get("generated_test"), "error": r.get("error"), "result_file": r.get("_path"),
            })


def average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(rows: list[dict[str, Any]], group_keys: tuple[str, ...], path: Path) -> None:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[tuple(r.get(k) for k in group_keys)].append(r)
    fields = list(group_keys) + [
        "tasks", "completed", "valid_tests", "generated_test_cases", "valid_test_cases",
        "fault_detecting_runs", "unique_bugs", "bugs_detected", "valid_rate", "bug_detection_rate",
        "avg_test_cases", "avg_instruction_coverage", "avg_branch_coverage", "avg_line_coverage",
        "avg_instruction_coverage_per_test", "avg_branch_coverage_per_test", "avg_line_coverage_per_test",
        "avg_generation_time_sec", "avg_evaluation_time_sec", "avg_duration_sec",
        "avg_generation_time_per_test", "avg_evaluation_time_per_test", "avg_duration_per_test"
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for key, items in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
            completed = [x for x in items if x.get("status") == "completed"]
            valid = [x for x in completed if x.get("valid_test") is True]
            fault_runs = [x for x in completed if x.get("fault_detected") is True]
            unique_bugs = {(x.get("project"), int(x.get("bug_id"))) for x in items}
            detected_bugs = {(x.get("project"), int(x.get("bug_id"))) for x in fault_runs}

            counts_all = [test_count(x) for x in items]
            counts_completed = [test_count(x) for x in completed]
            generated_test_cases = sum(counts_all)
            valid_test_cases = sum(test_count(x) for x in valid)

            ins = [x for x in (ratio(r, "instruction") for r in valid) if x is not None]
            br = [x for x in (ratio(r, "branch") for r in valid) if x is not None]
            ln = [x for x in (ratio(r, "line") for r in valid) if x is not None]

            ins_per_test = [x for x in (per_test(ratio(r, "instruction"), test_count(r)) for r in valid) if x is not None]
            br_per_test = [x for x in (per_test(ratio(r, "branch"), test_count(r)) for r in valid) if x is not None]
            ln_per_test = [x for x in (per_test(ratio(r, "line"), test_count(r)) for r in valid) if x is not None]

            generation_times = [float(r["generation_time_sec"]) for r in completed if r.get("generation_time_sec") is not None]
            evaluation_times = [float(r["evaluation_time_sec"]) for r in completed if r.get("evaluation_time_sec") is not None]
            durations = [float(r["duration_sec"]) for r in completed if r.get("duration_sec") is not None]

            generation_per_test = [x for x in (per_test(r.get("generation_time_sec"), test_count(r)) for r in completed) if x is not None]
            evaluation_per_test = [x for x in (per_test(r.get("evaluation_time_sec"), test_count(r)) for r in completed) if x is not None]
            duration_per_test = [x for x in (per_test(r.get("duration_sec"), test_count(r)) for r in completed) if x is not None]

            row = {k: v for k, v in zip(group_keys, key)}
            row.update({
                "tasks": len(items), "completed": len(completed), "valid_tests": len(valid),
                "generated_test_cases": generated_test_cases, "valid_test_cases": valid_test_cases,
                "fault_detecting_runs": len(fault_runs), "unique_bugs": len(unique_bugs),
                "bugs_detected": len(detected_bugs),
                "valid_rate": len(valid) / len(completed) if completed else None,
                "bug_detection_rate": len(detected_bugs) / len(unique_bugs) if unique_bugs else None,
                "avg_test_cases": average([float(x) for x in counts_completed]) if counts_completed else None,
                "avg_instruction_coverage": average(ins), "avg_branch_coverage": average(br),
                "avg_line_coverage": average(ln),
                "avg_instruction_coverage_per_test": average(ins_per_test),
                "avg_branch_coverage_per_test": average(br_per_test),
                "avg_line_coverage_per_test": average(ln_per_test),
                "avg_generation_time_sec": average(generation_times),
                "avg_evaluation_time_sec": average(evaluation_times),
                "avg_duration_sec": average(durations),
                "avg_generation_time_per_test": average(generation_per_test),
                "avg_evaluation_time_per_test": average(evaluation_per_test),
                "avg_duration_per_test": average(duration_per_test),
            })
            w.writerow(row)


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge result JSON from all members and create CSV summaries")
    ap.add_argument("--input", default="results/workers")
    ap.add_argument("--output", default="results/summary")
    args = ap.parse_args()
    input_root = ROOT / args.input
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    raw = load_results(input_root)
    experiment_ids = sorted({str(r.get("experiment_id")) for r in raw if r.get("experiment_id")})
    missing_experiment_id = [r for r in raw if not r.get("experiment_id")]
    if experiment_ids and missing_experiment_id:
        raise SystemExit("Some result files are missing experiment_id while others have one. Do not mix old and new benchmark results.")
    if len(experiment_ids) > 1:
        raise SystemExit(
            "Refusing to mix results from different experiment definitions: " + ", ".join(experiment_ids) +
            ". Re-run with matching code/config before combining results."
        )
    rows, duplicates = deduplicate(raw)
    write_all(rows, out / "all_results.csv")
    summarize(rows, ("method",), out / "summary_by_method.csv")
    summarize(rows, ("project", "method"), out / "summary_by_project.csv")
    write_duplicates(duplicates, out / "duplicate_tasks.csv")
    print(f"Loaded {len(raw)} result files; analyzing {len(rows)} unique tasks")
    if duplicates:
        print(f"WARNING: duplicate task results detected ({len(duplicates)} files). See {out/'duplicate_tasks.csv'}")
    print(out / "all_results.csv")
    print(out / "summary_by_method.csv")
    print(out / "summary_by_project.csv")


if __name__ == "__main__":
    main()
