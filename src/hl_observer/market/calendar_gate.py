"""GAP DATA/MARKET — Calendrier de marché: resserrer les gates aux mauvais moments.

La volatilité et la liquidité ont des patterns: week-end illiquide, chevauchement
de sessions, fenêtres macro (FOMC/CPI). On ne bloque pas aveuglément — on RESSERRE
les gates (facteur ≥ 1.0 sur l'edge requis) pendant les fenêtres risquées. Pur,
déterministe (l'heure UTC est fournie). Les événements macro sont injectés (liste
read-only), jamais devinés.
"""

from __future__ import annotations


def is_weekend(utc_weekday: int) -> bool:
    """0=lundi .. 6=dimanche. Samedi/dimanche = week-end crypto (liquidité plus fine)."""
    return int(utc_weekday) >= 5


def session_of(utc_hour: int) -> str:
    h = int(utc_hour) % 24
    if 0 <= h < 7:
        return "ASIA"
    if 7 <= h < 13:
        return "EUROPE"
    if 13 <= h < 21:
        return "US"
    return "OFF_HOURS"


def in_macro_window(now_ms: int, macro_events_ms: list[int], *, window_min: float = 30.0) -> bool:
    """Dans ±window_min d'un événement macro connu (FOMC/CPI, liste injectée)."""
    w = int(window_min * 60_000)
    return any(abs(int(now_ms) - int(ev)) <= w for ev in (macro_events_ms or []))


def gate_tightening_factor(
    *, utc_weekday: int, utc_hour: int, now_ms: int, macro_events_ms: list[int] | None = None,
    weekend_mult: float = 1.3, off_hours_mult: float = 1.15, macro_mult: float = 1.5,
) -> dict:
    """Facteur multiplicatif (≥1.0) à appliquer à l'edge MINIMUM requis."""
    reasons = []
    factor = 1.0
    if is_weekend(utc_weekday):
        factor *= weekend_mult; reasons.append("WEEKEND_THIN_LIQUIDITY")
    if session_of(utc_hour) == "OFF_HOURS":
        factor *= off_hours_mult; reasons.append("OFF_HOURS_SESSION")
    if in_macro_window(now_ms, macro_events_ms or []):
        factor *= macro_mult; reasons.append("MACRO_EVENT_WINDOW")
    return {
        "tightening_factor": round(factor, 4),
        "reasons": reasons if reasons else ["NORMAL_WINDOW"],
        "session": session_of(utc_hour),
        "tightened": factor > 1.0,
    }


def adjusted_min_edge_bps(base_min_edge_bps: float, tightening: dict) -> float:
    return round(float(base_min_edge_bps) * float(tightening.get("tightening_factor", 1.0)), 4)


__all__ = ["is_weekend", "session_of", "in_macro_window", "gate_tightening_factor", "adjusted_min_edge_bps"]
