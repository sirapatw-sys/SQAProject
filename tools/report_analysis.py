#!/usr/bin/env python3
"""Reproduce the report's additional analyses without running generators or APIs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import analyze
import run

METHODS = ("hill_climbing", "avm", "gpt", "gemini")


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def normalized_path(value):
    return str(value).replace("\\", "/")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_value(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="results/workers")
    parser.add_argument("--output", default="docs/report_data")
    args = parser.parse_args()
    output = ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    raw = analyze.load_results(ROOT / args.input)
    rows, duplicates = analyze.deduplicate(raw)
    settings = json.loads((ROOT / "config/settings.json").read_text())
    with (ROOT / "config/cases.csv").open(encoding="utf-8", newline="") as handle:
        cases = sorted(
            [r for r in csv.DictReader(handle) if r.get("enabled", "").lower() == "true"],
            key=lambda r: (r["project"], int(r["bug_id"])),
        )
    expected = {
        (c["project"], int(c["bug_id"]), method, run_id)
        for c in cases for method, run_id, _ in run.task_ids(settings, list(METHODS))
    }
    observed = {analyze.identity(r) for r in rows}
    by_bug = defaultdict(dict)
    for r in rows:
        key = (r["project"], int(r["bug_id"]))
        if r["method"] in by_bug[key]:
            raise SystemExit("Subset analysis requires one run per method per bug.")
        by_bug[key][r["method"]] = r
    common_completed = {
        k for k, v in by_bug.items()
        if all(v.get(m, {}).get("status") == "completed" for m in METHODS)
    }
    common_valid = {
        k for k in common_completed
        if all(by_bug[k][m].get("valid_test") is True for m in METHODS)
    }
    analyze.summarize(rows, ("experiment_id", "method"), output / "summary_by_experiment.csv")
    for name, keys in (("common_completed", common_completed), ("common_valid", common_valid)):
        subset = [by_bug[k][m] for k in sorted(keys) for m in METHODS]
        analyze.summarize(subset, ("method",), output / f"summary_{name}.csv")
        analyze.summarize(subset, ("experiment_id", "method"), output / f"summary_{name}_by_experiment.csv")
        write_csv(output / f"cases_{name}.csv", ["project", "bug_id"],
                  [dict(project=k[0], bug_id=k[1]) for k in sorted(keys)])

    failures = []
    for method in METHODS:
        group = [r for r in rows if r["method"] == method]
        counts = Counter(r["status"] for r in group)
        result = dict(method=method, tasks=len(group), **{
            k: counts[k] for k in ("completed", "unsupported", "error", "paused_quota")
        })
        for name in ("fixed_compile_failed", "fixed_test_failed", "buggy_compile_failed",
                     "valid_but_error", "search_budget_exhausted", "more_tests_than_target_methods",
                     "more_than_five_tests", "zero_target_methods"):
            result[name] = 0
        for r in group:
            evaluation = r.get("evaluation") or {}
            fixed = evaluation.get("fixed") or {}
            buggy = evaluation.get("buggy") or {}
            if fixed.get("compile_success") is False:
                result["fixed_compile_failed"] += 1
            elif fixed.get("test_success") is False:
                result["fixed_test_failed"] += 1
            result["buggy_compile_failed"] += buggy.get("compile_success") is False
            result["valid_but_error"] += r.get("valid_test") is True and r["status"] == "error"
            result["search_budget_exhausted"] += (r.get("search") or {}).get("time_budget_exhausted") is True
            if r.get("target_method_count") is not None:
                result["zero_target_methods"] += r["target_method_count"] == 0
                result["more_tests_than_target_methods"] += analyze.test_count(r) > r["target_method_count"]
            result["more_than_five_tests"] += analyze.test_count(r) > 5
        durations = [float(r["duration_sec"]) for r in group
                     if r["status"] == "completed" and r.get("duration_sec") is not None]
        result["median_duration_sec"] = statistics.median(durations) if durations else None
        failures.append(result)
    write_csv(output / "failure_breakdown.csv", list(failures[0]), failures)

    errors = [{k: r.get(k) for k in ("project", "bug_id", "method", "worker", "experiment_id",
                                    "status", "valid_test", "fault_detected", "error")} |
              {"result_file": r["_path"]}
              for r in rows if r["status"] == "error"]
    write_csv(output / "error_tasks.csv",
              ["project", "bug_id", "method", "worker", "experiment_id", "status",
               "valid_test", "fault_detected", "error", "result_file"], errors)
    reasons = Counter((r["method"], r.get("error", "")) for r in rows if r["status"] == "unsupported")
    write_csv(output / "unsupported_reasons.csv", ["method", "reason", "tasks"],
              [dict(method=m, reason=reason, tasks=count) for (m, reason), count in sorted(reasons.items())])
    detected = {
        m: {k for k, v in by_bug.items()
            if v.get(m, {}).get("status") == "completed" and v[m].get("fault_detected") is True}
        for m in METHODS
    }
    union = set().union(*detected.values())
    detection_rows = []
    for key in sorted(union):
        item = dict(project=key[0], bug_id=key[1],
                    experiment_id=next(iter(by_bug[key].values()))["experiment_id"])
        item.update({m: int(key in detected[m]) for m in METHODS})
        item["methods_detecting"] = sum(item[m] for m in METHODS)
        detection_rows.append(item)
    write_csv(output / "detected_bugs.csv",
              ["project", "bug_id", "experiment_id", *METHODS, "methods_detecting"], detection_rows)

    refs = {k: {normalized_path(r[k]) for r in rows if r.get(k)}
            for k in ("generated_test", "prompt_file", "response_file")}
    missing_files = {k: sorted(p for p in paths if not (ROOT / p).is_file())
                     for k, paths in refs.items()}
    actual_java = {p.relative_to(ROOT).as_posix() for p in (ROOT / "generated_tests").rglob("*.java")}
    artifacts = {}
    for worker in sorted({r["worker"] for r in rows}):
        paths = [p for p in (ROOT / "generated_tests" / worker).rglob("*") if p.is_file()]
        artifacts[worker] = dict(
            java_files=sum(p.suffix == ".java" for p in paths),
            prompt_files=sum(p.name == "prompt.txt" for p in paths),
            response_files=sum(p.name == "response.txt" for p in paths),
        )
    case_index = {(c["project"], int(c["bug_id"])): i for i, c in enumerate(cases, 1)}
    worker_ranges = {}
    for worker in sorted({r["worker"] for r in rows}):
        indices = sorted({case_index[r["project"], int(r["bug_id"])] for r in rows if r["worker"] == worker})
        worker_ranges[worker] = dict(start=min(indices), end=max(indices), cases=len(indices),
                                    contiguous=indices == list(range(min(indices), max(indices) + 1)))
    audit = dict(
        raw_results=len(raw), unique_tasks=len(rows), expected_tasks=len(expected),
        missing_tasks=sorted(expected - observed), unexpected_tasks=sorted(observed - expected),
        duplicate_files=len(duplicates), bugs=len(by_bug),
        projects=dict(sorted(Counter(c["project"] for c in cases).items())),
        experiment_ids=dict(sorted(Counter(r.get("experiment_id") for r in rows).items())),
        git_commits=dict(Counter(r.get("git_commit") for r in rows)),
        current_experiment_id=run.experiment_id(),
        current_git_commit=git_value("rev-parse", "HEAD"),
        recorded_timestamp_utc_min=min(r.get("timestamp_utc", "") for r in rows),
        recorded_timestamp_utc_max=max(r.get("timestamp_utc", "") for r in rows),
        common_completed_cases=len(common_completed), common_valid_cases=len(common_valid),
        detected_union=len(union),
        detections_by_method={m: len(v) for m, v in detected.items()},
        exclusive_detections={m: len(v - set().union(*(s for n, s in detected.items() if n != m)))
                              for m, v in detected.items()},
        hc_avm_detection_overlap=len(detected["hill_climbing"] & detected["avm"]),
        referenced_artifact_counts={k: len(v) for k, v in refs.items()},
        missing_referenced_artifacts=missing_files,
        unreferenced_java_files=sorted(actual_java - refs["generated_test"]),
        worker_artifacts=artifacts, worker_ranges=worker_ranges,
        meta_files=len(list((ROOT / "results/meta").rglob("meta.json"))),
        log_files=len(list((ROOT / "logs").rglob("*.log"))),
        provider_models={m: dict(Counter((r.get("provider") or {}).get("model", "not_recorded")
                                        for r in rows if r["method"] == m)) for m in ("gpt", "gemini")},
        analysis_source_sha256={name: sha256(ROOT / name)
                                for name in ("analyze.py", "tools/report_analysis.py")},
        path_resolution="Convert backslashes to forward slashes for artifact lookup; preserve raw JSON.",
    )
    (output / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Analyzed {len(rows)} tasks; common completed={len(common_completed)}, common valid={len(common_valid)}")
    print(f"Experiment IDs: {', '.join(audit['experiment_ids'])}")
    print(f"Detected union={len(union)}; missing artifacts={sum(map(len, missing_files.values()))}")
    if expected != observed or duplicates or any(missing_files.values()):
        raise SystemExit("Audit found missing/unexpected tasks, duplicates, or missing referenced artifacts.")


if __name__ == "__main__":
    main()
