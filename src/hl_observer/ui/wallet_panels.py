"""Wallet panels (V12, repo 07): red-flags + copyability, evidence-based, honest empty state."""

from __future__ import annotations


def build_red_flags_panel(stats: dict | None) -> dict:
    if not stats:
        return {"red_flags": [], "empty": True}      # requires data, never invents flags
    flags: list[str] = []
    if float(stats.get("one_big_win_share", 0.0)) > 0.5:
        flags.append("ONE_BIG_WIN_RISK")
    if float(stats.get("max_drawdown_pct", 0.0)) > 30.0:
        flags.append("HIGH_DRAWDOWN_RISK")
    if float(stats.get("pnl_concentration", 0.0)) > 0.35:
        flags.append("PNL_CONCENTRATION_RISK")
    if int(stats.get("recent_fills", 0)) == 0:
        flags.append("INACTIVE_WALLET")
    return {"red_flags": flags, "empty": False}


def build_copyability_panel(*, copyability_score: float | None, evidence_refs: list[str]) -> dict:
    if copyability_score is None:
        return {"copyability_score": None, "empty": True, "evidence_refs": list(evidence_refs or [])}
    return {
        "copyability_score": round(float(copyability_score), 4),
        "evidence_refs": list(evidence_refs or []),
        "empty": False,
    }


__all__ = ["build_red_flags_panel", "build_copyability_panel"]
