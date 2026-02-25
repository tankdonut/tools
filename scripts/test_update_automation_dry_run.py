#!/usr/bin/env python3

import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
METADATA_FILE = ROOT / "tasks" / "metadata.yaml"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    print("==> Verifying update.automation --dry-run")

    if not METADATA_FILE.exists():
        print("ERROR: metadata.yaml not found")
        return 1

    original_hash = sha256(METADATA_FILE)

    branch_result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if branch_result.returncode != 0:
        print("ERROR: unable to determine current branch")
        print(branch_result.stderr)
        return 1

    original_branch = branch_result.stdout.strip()

    result = run(["uv", "run", "invoke", "update.automation", "--dry-run"])

    print(result.stdout)

    if result.returncode != 0:
        print("ERROR: dry-run exited non-zero")
        print(result.stderr)
        return 1

    new_hash = sha256(METADATA_FILE)
    if new_hash != original_hash:
        print("ERROR: metadata.yaml was modified during dry-run")
        return 1

    branch_result_after = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    new_branch = branch_result_after.stdout.strip()

    if new_branch != original_branch:
        print("ERROR: branch changed during dry-run")
        return 1

    print("Dry-run is side-effect free")
    return 0


if __name__ == "__main__":
    sys.exit(main())
