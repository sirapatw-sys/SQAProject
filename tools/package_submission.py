#!/usr/bin/env python3
"""Package the final experiment's existing evidence, source and documentation."""
from __future__ import annotations

import gzip
import hashlib
import json
import tarfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "submission"
ARCHIVE = OUTPUT / "sqa-final-submission.tar.gz"
MANIFEST = ROOT / "FILE_MANIFEST.sha256"
INVENTORY = ROOT / "SUBMISSION_INVENTORY.json"
SOURCE_DIRS = ("ai", "algorithms", "config", "docker", "harness", "prompts", "tests", "tools")
EVIDENCE_DIRS = ("docs", "results/workers", "results/meta", "results/summary", "generated_tests")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected_files():
    files = set(ROOT.glob("*.py")) | set(ROOT.glob("*.md"))
    files.update(ROOT / name for name in ("requirements.txt", ".env.example", ".gitignore"))
    for directory in SOURCE_DIRS:
        for path in (ROOT / directory).rglob("*"):
            if path.name == "Dockerfile" or path.suffix in {".py", ".java", ".json", ".csv", ".txt", ".yaml", ".jar"}:
                files.add(path)
    for directory in EVIDENCE_DIRS:
        files.update((ROOT / directory).rglob("*"))
    return sorted(
        (p for p in files if p.is_file() and not p.is_symlink()
         and p not in (MANIFEST, INVENTORY)
         and "__pycache__" not in p.parts and "classes" not in p.parts
         and p.suffix != ".pyc" and p.name != ".env"
         and not p.name.endswith((".bak", ".tmp", "_backup.csv", ":Zone.Identifier"))),
        key=lambda p: p.relative_to(ROOT).as_posix(),
    )


def check_credentials(files):
    # Compare against locally configured keys without printing or packaging them.
    env_path = ROOT / ".env"
    secrets = []
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in {"GPT_API_KEY", "GEMINI_API_KEY"}:
                value = value.strip().strip("\"'")
                if len(value) >= 12 and not value.startswith(("YOUR_", "your_")):
                    secrets.append(value.encode())
    if any(secret in path.read_bytes() for path in files for secret in secrets):
        raise SystemExit("A configured credential appears in a selected file; package creation aborted.")


def normalized_metadata(info):
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    info.mode = 0o644
    return info


def main():
    files = selected_files()
    check_credentials(files)
    categories = defaultdict(lambda: {"files": 0, "bytes": 0})
    for path in files:
        relative = path.relative_to(ROOT)
        category = relative.parts[0] if len(relative.parts) > 1 else "root_source_and_documents"
        categories[category]["files"] += 1
        categories[category]["bytes"] += path.stat().st_size
    inventory = dict(
        description="Final experiment payload before adding this inventory and FILE_MANIFEST.sha256.",
        payload_files=len(files), payload_bytes=sum(p.stat().st_size for p in files),
        categories=dict(sorted(categories.items())),
        raw_task_results=len(list((ROOT / "results/workers").rglob("*.json"))),
        generated_java_files=len(list((ROOT / "generated_tests").rglob("*.java"))),
        actual_prompt_files=len(list((ROOT / "generated_tests").rglob("prompt.txt"))),
        actual_response_files=len(list((ROOT / "generated_tests").rglob("response.txt"))),
        exclusions=[".env and credentials", ".git", ".venv", "__pycache__", ".work", "results/tmp",
                    "Windows download metadata and editor backups",
                    "compiled harness classes", "pilot/AI backups", "original duplicate worker bundles"],
    )
    INVENTORY.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    files.append(INVENTORY)
    files.sort(key=lambda p: p.relative_to(ROOT).as_posix())
    hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in files}
    MANIFEST.write_text("".join(f"{value}  {name}\n" for name, value in hashes.items()), encoding="utf-8")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT / "sqa-final-submission.tar.gz.tmp"
    with temporary.open("wb") as destination:
        with gzip.GzipFile(filename="", mode="wb", fileobj=destination, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in [*files, MANIFEST]:
                    archive.add(path, arcname=path.relative_to(ROOT).as_posix(),
                                recursive=False, filter=normalized_metadata)
    with tarfile.open(temporary, "r:gz") as archive:
        expected_names = set(hashes) | {MANIFEST.name}
        if set(archive.getnames()) != expected_names:
            raise SystemExit("Archive file inventory does not match the manifest.")
        for member in archive.getmembers():
            if member.name == MANIFEST.name:
                continue
            with archive.extractfile(member) as source:
                actual = hashlib.sha256(source.read()).hexdigest()
            if actual != hashes[member.name]:
                raise SystemExit(f"Archive integrity check failed: {member.name}")
    temporary.replace(ARCHIVE)
    checksum = ARCHIVE.with_name(ARCHIVE.name + ".sha256")
    checksum.write_text(f"{digest(ARCHIVE)}  {ARCHIVE.relative_to(ROOT).as_posix()}\n", encoding="utf-8")
    print(f"Packaged and verified {len(files) + 1:,} files; archive {ARCHIVE.stat().st_size / 1024 / 1024:.2f} MiB")
    print(ARCHIVE.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
