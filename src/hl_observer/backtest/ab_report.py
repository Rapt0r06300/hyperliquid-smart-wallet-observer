"""A/B backtest report (levier H, R1) — comparer deux variantes au profit factor.

Prend deux listes de PnL realises (ou deux ExperimentResult) et rend un verdict
honnete base sur le profit factor et le max drawdown. Pur, aucune donnee inventee,
aucune action reelle. On juge au profit factor, jamais au winrate brut.
"""

from __future__ import annotations

from hl_observer.backtest.experiment_runner import (
    BacktestSummary,
    summarize_decisions,
    summarize_pnl,
)

# Seuil d'amelioration minimal du profit factor pour declarer une variante gagnante.
DEFAULT_MIN_PF_UPLIFT = 0.05


def _pf(s: BacktestSummary) -> float:
    return s.profit_factor


def verdict(baseline: BacktestSummary, variant: BacktestSummary,
            *, min_pf_uplift: float = DEFAULT_MIN_PF_UPLIFT) -> str:
    """KEEP_VARIANT si la variante ameliore nettement le profit factor sans aggraver
    le drawdown ; KEEP_BASELINE si elle degrade ; NEUTRAL sinon."""
    pf_b, pf_v = _pf(baseline), _pf(variant)
    dd_worse = variant.max_drawdown > baseline.max_drawdown * 1.10
    if pf_v == float("inf") and pf_b != float("inf") and not dd_worse:
        return "KEEP_VARIANT"
    if pf_b == float("inf") and pf_v != float("inf"):
        return "KEEP_BASELINE"
    if pf_v >= pf_b + min_pf_uplift and not dd_worse:
        return "KEEP_VARIANT"
    if pf_v < pf_b - min_pf_uplift or dd_worse:
        return "KEEP_BASELINE"
    return "NEUTRAL"


def ab_compare_pnls(name_a: str, pnls_a, name_b: str, pnls_b,
                    *, min_pf_uplift: float = DEFAULT_MIN_PF_UPLIFT) -> dict:
    """Compare deux jeux de PnL realises (A=baseline, B=variante)."""
    sa = summarize_pnl(pnls_a)
    sb = summarize_pnl(pnls_b)
    return {
        "baseline": {"name": name_a, **sa.to_dict()},
        "variant": {"name": name_b, **sb.to_dict()},
        "profit_factor_delta": (
            float("inf") if (sb.profit_factor == float("inf") and sa.profit_factor != float("inf"))
            else (sb.profit_factor - sa.profit_factor
                  if sa.profit_factor != float("inf") and sb.profit_factor != float("inf")
                  else 0.0)
        ),
        "total_pnl_delta": round(sb.total_pnl - sa.total_pnl, 8),
        "verdict": verdict(sa, sb, min_pf_uplift=min_pf_uplift),
    }


def ab_compare_decisions(name_a: str, decisions_a, name_b: str, decisions_b,
                         *, pnl_key: str = "realized_pnl",
                         min_pf_uplift: float = DEFAULT_MIN_PF_UPLIFT) -> dict:
    """Compare deux ensembles de decisions (chacune portant un PnL realise)."""
    sa = summarize_decisions(decisions_a, pnl_key=pnl_key)
    sb = summarize_decisions(decisions_b, pnl_key=pnl_key)
    return {
        "baseline": {"name": name_a, **sa.to_dict()},
        "variant": {"name": name_b, **sb.to_dict()},
        "total_pnl_delta": round(sb.total_pnl - sa.total_pnl, 8),
        "verdict": verdict(sa, sb, min_pf_uplift=min_pf_uplift),
    }


__all__ = ["verdict", "ab_compare_pnls", "ab_compare_decisions", "DEFAULT_MIN_PF_UPLIFT"]
