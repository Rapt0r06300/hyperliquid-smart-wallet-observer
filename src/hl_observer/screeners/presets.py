"""Screener presets (V12, repo 08): named, read-only filter sets for the shortlist UI.

Presets are *thresholds only* — they tighten/loosen what shows up; they never place a
trade and never lower a safety gate below its floor.
"""

from __future__ import annotations

_PRESETS: dict[str, dict] = {
    "fresh_liquid":  {"max_signal_age_ms": 45_000, "min_liquidity_score": 0.30, "min_edge_bps": 12.0},
    "smart_money":   {"min_quality": 65.0, "min_profit_factor": 1.8, "max_one_big_win_share": 0.4},
    "conservative":  {"max_signal_age_ms": 20_000, "min_liquidity_score": 0.45, "min_edge_bps": 22.0},
    "active_now":    {"min_recent_fills": 5, "max_last_fill_age_ms": 600_000},
}


def list_presets() -> list[str]:
    return list(_PRESETS)


def get_preset(name: str) -> dict:
    if name not in _PRESETS:
        raise KeyError(f"unknown screener preset: {name}")
    return dict(_PRESETS[name])


__all__ = ["list_presets", "get_preset"]
