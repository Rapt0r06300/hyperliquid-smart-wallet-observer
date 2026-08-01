"""Entrée CLI additive : `python -m hl_observer.mega_cablage [--from-logs DIR] [...]`.

Fully additive (n'édite pas cli.py) — même convention standalone que `python -m hl_observer.runtime.
persistent_poll_runner`. PAPER STRICT : dry-run only, `--no-dry-run` est refusé.
"""
from __future__ import annotations

import argparse
from typing import Any

from hl_observer.mega_cablage.runner import run_mega_cablage, format_mega_cablage_run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="hl_observer.mega_cablage",
        description="Runner paper du meta-cablage des pepites 201-300 (dry-run only, 0 ordre reel).")
    ap.add_argument("--from-logs", type=str, default=None,
                    help="Dossier ou fichier .jsonl d'evenements replay a rejouer.")
    ap.add_argument("--equity", type=float, default=1000.0, help="Notre equity de depart (USDC).")
    ap.add_argument("--notional-max", type=float, default=500.0, help="Plafond notional par ordre (USDC).")
    ap.add_argument("--fee-bps", type=float, default=4.5, help="Frais taker en bps.")
    ap.add_argument("--leader-equity", type=float, default=None,
                    help="Equity leader par defaut (modelisation) si absente des logs.")
    ap.add_argument("--no-dry-run", action="store_true", help="INTERDIT (paper only) : provoque un refus.")
    args = ap.parse_args(argv)

    if args.no_dry_run:
        print("mega-cablage refused: paper/dry-run only. Aucune execution reelle n'est possible.")
        return 2

    result = run_mega_cablage(from_logs=args.from_logs, notre_equity=args.equity,
                              notional_max=args.notional_max, fee_bps=args.fee_bps,
                              leader_equity_defaut=args.leader_equity, dry_run=True)
    print(format_mega_cablage_run(result))
    return 0


def _entrypoint() -> Any:
    raise SystemExit(main())


if __name__ == "__main__":
    _entrypoint()
