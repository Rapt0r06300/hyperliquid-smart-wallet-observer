#!/usr/bin/env python3
"""Read-only validator for H-T115/H-T170 causal receipts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hl_observer.backtesting.copy_vault_closure_gate import (  # noqa: E402
    PROVEN,
    validate_l4_pairing_receipt,
    validate_live_ws_causal_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=("H-T115", "H-T170"), required=True)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    try:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 1
    validator = (
        validate_l4_pairing_receipt
        if args.task == "H-T115"
        else validate_live_ws_causal_receipt
    )
    report = validator(receipt)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["status"] == PROVEN else 2


if __name__ == "__main__":
    raise SystemExit(main())
