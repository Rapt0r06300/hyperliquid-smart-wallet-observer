"""Export honest Copy-Vault, Lead-Lag, and Cross-Venue economic scoreboards."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.simulation.economic_family_scoreboard import export_scoreboards


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output")
    args = parser.parse_args()
    path = export_scoreboards(Path(args.root), args.output)
    payload = json.loads(path.read_text(encoding="utf-8"))
    print(path)
    for family, row in payload["families"].items():
        print(f"{family}: {row['verdict']} net_pnl_usd={row['net_pnl_usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
