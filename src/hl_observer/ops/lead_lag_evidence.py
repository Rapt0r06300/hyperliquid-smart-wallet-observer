"""Build the official lead-lag shadow evidence from the durable local BBO tape."""
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from hl_observer.backtesting.lead_lag_shadow import (
    FRAIS_SLIPPAGE_BPS,
    HORIZONS_MS,
    MIN_CHOCS,
    SEUIL_CHOC_BPS,
    backtest,
    charger_tape,
    geler_config,
)


def _coins(value: str) -> list[str]:
    return sorted({item.strip().upper() for item in value.split(",") if item.strip()})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Mesure puis gele une preuve lead-lag versionnee. "
            "Recherche locale uniquement, aucune execution."
        )
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--coins", default="")
    parser.add_argument("--control-coins", default="DOGE,XRP")
    parser.add_argument("--minimum-events", type=int, default=MIN_CHOCS)
    parser.add_argument("--shock-bps", type=float, default=SEUIL_CHOC_BPS)
    parser.add_argument("--cost-bps", type=float, default=FRAIS_SLIPPAGE_BPS)
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="Ecrit aussi le contrat actif, PROMOTED uniquement si tous les controles passent.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    controls = _coins(args.control_coins)
    requested_coins = _coins(args.coins)
    tape_coins = sorted(charger_tape(root))
    coins = requested_coins or [coin for coin in tape_coins if coin not in controls]
    evidence = backtest(
        root,
        seuil_choc_bps=float(args.shock_bps),
        frais_slippage_bps=float(args.cost_bps),
        horizons_ms=HORIZONS_MS,
        coins_controle=tuple(controls),
        min_chocs=max(1, int(args.minimum_events)),
    )
    frozen = None
    if args.freeze:
        frozen = geler_config(
            root,
            coins=coins,
            coins_controle=controls,
            horizons_ms=HORIZONS_MS,
            seuil_choc_bps=float(args.shock_bps),
            frais_slippage_bps=float(args.cost_bps),
            minimum_events=max(1, int(args.minimum_events)),
            evidence=evidence,
        )
    payload = {
        "schema_version": 1,
        "analysis": evidence,
        "frozen_evidence": frozen,
        "coins": coins,
        "control_coins": controls,
        "local_data_only": True,
        "real_execution": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    status = (frozen or {}).get("promotion_status", evidence.get("statut", "UNKNOWN"))
    print(f"lead_lag_evidence={output} status={status}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
