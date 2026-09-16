#!/usr/bin/env python3
import shutil
import subprocess
import sys

COMMANDS = [
    ("java", ["java", "-version"]),
    ("git", ["git", "--version"]),
    ("svn", ["svn", "--version", "--quiet"]),
    ("perl", ["perl", "-v"]),
    ("defects4j", ["defects4j", "pids"]),
]

def run(cmd):
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        output = (p.stdout or p.stderr).strip().splitlines()
        preview = output[0] if output else ""
        return p.returncode == 0, preview
    except Exception as e:
        return False, str(e)

failed = False
for name, cmd in COMMANDS:
    path = shutil.which(cmd[0])
    if not path:
        print(f"[FAIL] {name}: command not found")
        failed = True
        continue
    ok, preview = run(cmd)
    mark = "OK" if ok else "FAIL"
    print(f"[{mark}] {name}: {preview}")
    failed = failed or not ok

if failed:
    sys.exit(1)

print("\nEnvironment check passed.")
