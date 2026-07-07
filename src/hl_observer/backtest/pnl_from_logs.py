"""R1 (câblage réel) — juge PnL sur les logs de simulation réels.

Lit `simulation_decisions_append_only.jsonl` (ledger append-only), extrait le PnL
net réalisé par trade clos, et rend profit factor / drawdown / expectancy via
summarize_pnl. Peut comparer deux logs (A/B). Robuste aux lignes malformées
(tronquées). Read-only : ne modifie jamais les logs, n'émet aucun ordre.

Usage : python -m hl_observer.backtest.pnl_from_logs <chemin.jsonl> [<chemin_variant.jsonl>]
"""

from __future__ import annotations

import json
import sys

from hl_observer.backtest.ab_report import ab_compare_pnls
from hl_observer.backtest.experiment_runner import summarize_pnl

DEFAULT_PNL_KEY = "estimated_net_pnl_usdc"
_CLOSE_HINTS = ("CLOSE", "REDUCE", "EXIT")


def _is_closed_trade(row: dict, pnl_key: str) -> bool:
    if row.get("exit_method"):
        return True
    pat = str(row.get("paper_action_type") or row.get("bot_replay_action") or "").upper()
    if any(h in pat for h in _CLOSE_HINTS):
        return True
    v = row.get(pnl_key)
    return v not in (None, 0, 0.0)


def load_realized_pnls(path: str, *, pnl_key: str = DEFAULT_PNL_KEY, close_only: bool = True) -> list[float]:
    pnls: list[float] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue  # ligne tronquée/malformée -> ignorée (jamais inventée)
            if not isinstance(row, dict):
                continue
            if close_only and not _is_closed_trade(row, pnl_key):
                continue
            v = row.get(pnl_key)
            if v is None:
                continue
            try:
                pnls.append(float(v))
            except (TypeError, ValueError):
                continue
    return pnls


def summarize_log(path: str, *, pnl_key: str = DEFAULT_PNL_KEY) -> dict:
    return summarize_pnl(load_realized_pnls(path, pnl_key=pnl_key)).to_dict()


def ab_logs(baseline_path: str, variant_path: str, *, pnl_key: str = DEFAULT_PNL_KEY) -> dict:
    return ab_compare_pnls(
        baseline_path, load_realized_pnls(baseline_path, pnl_key=pnl_key),
        variant_path, load_realized_pnls(variant_path, pnl_key=pnl_key),
    )


def _main(argv: list[str]) -> int:
    if not argv:
        print("usage: pnl_from_logs <log.jsonl> [<variant.jsonl>]")
        return 2
    if len(argv) == 1:
        print(json.dumps(summarize_log(argv[0]), indent=2))
    else:
        print(json.dumps(ab_logs(argv[0], argv[1]), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))


__all__ = ["load_realized_pnls", "summarize_log", "ab_logs", "DEFAULT_PNL_KEY"]
