#!/usr/bin/env python3
"""Static firewall for GitHub-hosted-only canonical workflows."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

RUNNER = re.compile(r"(?im)^\s*runs-on:\s*(?:\[([^\]]+)\]|([^\n#]+))")
LEGACY_LFS_COMMANDS = (
    "gh workflow run clone-payload-lfs-mirror.yml",
    "mirror_releases_to_clone_lfs.py",
    "git lfs pull",
    "git lfs push",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".github/workflows")
    args = parser.parse_args()
    root = Path(args.root)
    violations = []
    lfs_violations = []
    for path in sorted(root.glob("*.y*ml")):
        if "lfs" in path.name.casefold():
            lfs_violations.append(str(path))
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in RUNNER.finditer(text):
            value = (match.group(1) or match.group(2) or "").lower()
            if "self-hosted" in value:
                violations.append(f"{path}:{text[:match.start()].count(chr(10)) + 1}")
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if any(command in stripped for command in LEGACY_LFS_COMMANDS):
                lfs_violations.append(f"{path}:{line_number}")
    if violations:
        raise SystemExit("SELF_HOSTED_RUNNER_FORBIDDEN: " + ", ".join(violations))
    if lfs_violations:
        raise SystemExit(
            "LEGACY_LFS_WORKFLOW_FORBIDDEN: " + ", ".join(lfs_violations)
        )
    print(f"GITHUB_HOSTED_WORKFLOWS_OK files={len(list(root.glob('*.y*ml')))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
