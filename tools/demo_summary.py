#!/usr/bin/env python3
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "results/demo_summary/summary_by_method.csv")

if not path.exists():
    raise SystemExit(f"ไม่พบไฟล์: {path}")

with path.open(encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

def pct(value):
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value) * 100:.1f}%"
    except ValueError:
        return "-"

def sec(value):
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):.1f}s"
    except ValueError:
        return "-"

def yes_no(value):
    try:
        return "YES" if int(float(value or 0)) > 0 else "NO"
    except ValueError:
        return "NO"

headers = ["Method", "Valid", "Bug", "Branch Cov.", "Line Cov.", "Time"]
table = []
for r in rows:
    table.append([
        r.get("method", "-"),
        yes_no(r.get("valid_tests")),
        yes_no(r.get("bugs_detected")),
        pct(r.get("avg_branch_coverage")),
        pct(r.get("avg_line_coverage")),
        sec(r.get("avg_duration_sec")),
    ])

widths = [len(h) for h in headers]
for row in table:
    for i, value in enumerate(row):
        widths[i] = max(widths[i], len(str(value)))

def line(row):
    return "  ".join(str(v).ljust(widths[i]) for i, v in enumerate(row))

print("\n=== Demo Summary ===")
print(line(headers))
print("  ".join("-" * w for w in widths))
for row in table:
    print(line(row))
print()
