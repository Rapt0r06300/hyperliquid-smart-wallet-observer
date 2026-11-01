#!/usr/bin/env python3
"""Read-only CLI for validating the canonical H-T95 restoration snapshot."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hl_observer.backtesting.copy_vault_snapshot_contract import (  # noqa: E402
    PROVEN,
    verify_snapshot_contract,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSON restoration snapshot to validate")
    args = parser.parse_args(argv)
    try:
        snapshot = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "NOT_PROVEN", "invalid": [str(exc)]}, sort_keys=True))
        return 1
    report = verify_snapshot_contract(snapshot)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == PROVEN else 2


if __name__ == "__main__":
    raise SystemExit(main())
