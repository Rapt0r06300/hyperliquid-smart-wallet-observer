#!/usr/bin/env python3
"""Audit the three local paper economic campaigns from their raw ledgers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hl_observer.simulation.economic_proof_audit import (  # noqa: E402
    audit_reports,
    write_audit,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument(
        "--require-objectives",
        action="store_true",
        help="return non-zero unless all three +4 USD objectives are proven",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    audit = audit_reports(root)
    json_path, markdown_path = write_audit(root, audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"AUDIT_JSON={json_path}")
    print(f"AUDIT_MARKDOWN={markdown_path}")
    if audit["missing_families"] or not audit["all_ledgers_valid"]:
        return 2
    if args.require_objectives and not audit["all_objectives_met"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
