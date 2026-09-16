#!/usr/bin/env python3
import argparse
import csv
from collections import defaultdict
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--members", type=int, required=True)
parser.add_argument("--inventory", default="config/inventory.csv")
parser.add_argument("--out", default="assignments")
args = parser.parse_args()

if args.members < 1:
    raise SystemExit("--members must be >= 1")

by_project = defaultdict(list)
with open(args.inventory, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        by_project[row["project"]].append(int(row["bug_id"]))

assignments = [[] for _ in range(args.members)]
cursor = 0

# Rotate across members within every project so that large projects are spread out.
for project in sorted(by_project):
    for bug_id in sorted(by_project[project]):
        idx = cursor % args.members
        assignments[idx].append((project, bug_id))
        cursor += 1

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)

for i, rows in enumerate(assignments, start=1):
    path = out / f"member_{i:02d}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["project", "bug_id"])
        w.writerows(rows)
    print(f"{path}: {len(rows)} bugs")
