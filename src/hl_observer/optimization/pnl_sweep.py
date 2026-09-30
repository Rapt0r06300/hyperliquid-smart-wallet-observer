"""B2/B3 — Sweep générique branché au juge (profit factor). Pur.

`sweep(param_grid, scorer)` évalue chaque combinaison ; `scorer(config)` renvoie la
liste des PnL réalisés (via replay/backtest). On juge au profit factor, jamais au winrate.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import product

from hl_observer.backtest.experiment_runner import summarize_pnl


def sweep(param_grid: dict, scorer: Callable[[dict], list]) -> list[dict]:
    keys = list(param_grid)
    out: list[dict] = []
    for combo in product(*[list(param_grid[k]) for k in keys]):
        cfg = dict(zip(keys, combo))
        s = summarize_pnl(scorer(cfg) or [])
        out.append({
            "config": cfg,
            "profit_factor": s.profit_factor,
            "total_pnl": s.total_pnl,
            "trades": s.total_trades,
            "max_drawdown": s.max_drawdown,
        })
    return out


def best_by_profit_factor(results: list[dict]) -> dict | None:
    if not results:
        return None
    def _pf(r):
        pf = r.get("profit_factor", 0.0)
        return (1e9 if pf == float("inf") else pf, r.get("total_pnl", 0.0))
    return max(results, key=_pf)


# Grilles par défaut (points de départ ; les valeurs finales sortent d'un sweep sur logs réels)
EXIT_PARAM_GRID = {
    "trailing_bps": [20.0, 30.0, 40.0],
    "trailing_arm_bps": [40.0, 50.0, 60.0],
    "stop_loss_bps": [60.0, 80.0, 100.0],
    "take_profit_bps": [150.0, 250.0, 350.0],
    "breakeven_trigger_bps": [40.0, 60.0, 80.0],
}
ENTRY_PARAM_GRID = {
    "min_edge_bps": [20.0, 30.0, 40.0],
    "min_consensus": [1, 2, 3],
    "freshness_window_ms": [4000.0, 8000.0, 12000.0],
}

__all__ = ["sweep", "best_by_profit_factor", "EXIT_PARAM_GRID", "ENTRY_PARAM_GRID"]
