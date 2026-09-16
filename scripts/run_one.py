#!/usr/bin/env python3

"""Future single-bug orchestrator.

This file is intentionally a stub in scaffold v0.1.
The next implementation step will make this command perform:

1. checkout selected Defects4J version
2. baseline compile/test
3. export metadata
4. choose target classes
5. invoke Hill Climbing
6. invoke AVM
7. invoke GPT
8. invoke Gemini
9. evaluate every generated suite with the same evaluator
10. write per-method JSON results
11. clean the temporary checkout

Do not implement batch execution until run_one is reliable.
"""

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--project", required=True)
parser.add_argument("--bug", required=True, type=int)
args = parser.parse_args()

raise SystemExit(
    f"run_one.py scaffold only: {args.project}-{args.bug}. "
    "Implement and validate the single-bug pipeline before full batch runs."
)
