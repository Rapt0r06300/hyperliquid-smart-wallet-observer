#!/usr/bin/env python3
"""Print a read-only inventory of explicitly supplied local evidence paths."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.backtesting.copy_vault_evidence_inventory import build_inventory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--path", dest="paths", action="append", required=True)
    args = parser.parse_args()
    try:
        report = build_inventory(args.repo_root, args.paths)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
