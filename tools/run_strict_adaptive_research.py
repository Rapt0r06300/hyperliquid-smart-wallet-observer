"""Lance la recherche adaptative stricte Copy-Vault sur un replay local.

Cette commande est destinée au laboratoire autonome. Elle ne fait aucun appel
marché et n'émet aucun ordre. Le crible de sélection reste sur TRAIN seulement.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from hl_observer.backtesting.recherche_adaptative_stricte import (
    chercher_copy_strict,
    write_strict_report,
)


def _assert_safe_environment() -> None:
    active = []
    for name in ("HL_ENABLE_MAINNET_EXECUTION", "HL_ENABLE_TESTNET_EXECUTION", "REAL_MAINNET_TRADING"):
        if str(os.getenv(name, "0")).strip().casefold() in {"1", "true", "yes", "on", "oui"}:
            active.append(name)
    if active:
        raise RuntimeError("exécution interdite pendant la recherche stricte: " + ", ".join(active))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--budget-s", type=float, default=7_200.0)
    parser.add_argument("--max-essais", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        _assert_safe_environment()
        root = Path(args.root).resolve()
        result = chercher_copy_strict(
            root,
            budget_s=max(1.0, float(args.budget_s)),
            max_essais=args.max_essais,
            raffiner=True,
        )
        path = write_strict_report(root, result)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"STRICT_ADAPTIVE_NO_GO: {type(exc).__name__}: {exc}", flush=True)
        return 2
    print(
        "STRICT_ADAPTIVE_DONE "
        f"status={result.get('statut')} "
        f"promus={len(result.get('promus') or [])} "
        f"validation_rows_seen={(result.get('scout_audit') or {}).get('validation_rows_seen')} "
        f"report={path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
