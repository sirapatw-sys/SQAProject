#!/usr/bin/env python3
import csv
import re
import subprocess
from pathlib import Path

OUT = Path("config/inventory.csv")

def cmd(args):
    p = subprocess.run(args, text=True, capture_output=True, check=True)
    return p.stdout.strip()

def tokens(text):
    # Works with newline- or whitespace-separated outputs.
    return [x for x in re.split(r"\s+", text.strip()) if x]

projects = tokens(cmd(["defects4j", "pids"]))
rows = []

for project in projects:
    bug_ids = tokens(cmd(["defects4j", "bids", "-p", project]))
    for bug_id in bug_ids:
        if bug_id.isdigit():
            rows.append((project, int(bug_id)))

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["project", "bug_id"])
    w.writerows(rows)

print(f"Wrote {len(rows)} active bug instances to {OUT}")
