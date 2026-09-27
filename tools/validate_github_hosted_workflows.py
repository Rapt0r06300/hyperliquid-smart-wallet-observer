#!/usr/bin/env python3
"""Static firewall for GitHub-hosted-only canonical workflows."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

RUNNER = re.compile(r"(?im)^\s*runs-on:\s*(?:\[([^\]]+)\]|([^\n#]+))")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".github/workflows")
    args = parser.parse_args()
    root = Path(args.root)
    violations = []
    for path in sorted(root.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in RUNNER.finditer(text):
            value = (match.group(1) or match.group(2) or "").lower()
            if "self-hosted" in value:
                violations.append(f"{path}:{text[:match.start()].count(chr(10)) + 1}")
    if violations:
        raise SystemExit("SELF_HOSTED_RUNNER_FORBIDDEN: " + ", ".join(violations))
    print(f"GITHUB_HOSTED_WORKFLOWS_OK files={len(list(root.glob('*.y*ml')))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
