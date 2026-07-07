"""C6 — Rapport de sélectivité : moins de trades + meilleur profit factor ?"""

from __future__ import annotations

from hl_observer.backtest.experiment_runner import summarize_pnl


def selectivity_report(baseline_pnls, variant_pnls) -> dict:
    b = summarize_pnl(baseline_pnls)
    v = summarize_pnl(variant_pnls)
    pf_b = b.profit_factor if b.profit_factor != float("inf") else 1e9
    pf_v = v.profit_factor if v.profit_factor != float("inf") else 1e9
    return {
        "baseline_trades": b.total_trades,
        "variant_trades": v.total_trades,
        "trades_delta": v.total_trades - b.total_trades,
        "baseline_profit_factor": b.profit_factor,
        "variant_profit_factor": v.profit_factor,
        "more_selective": v.total_trades < b.total_trades,
        "better_profit_factor": pf_v > pf_b,
        "verdict": ("SELECTIVITY_HELPS" if (v.total_trades <= b.total_trades and pf_v > pf_b)
                    else "NO_IMPROVEMENT"),
    }


__all__ = ["selectivity_report"]
