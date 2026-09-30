"""M1/M6/M7 — Entrée avancée : DCA (grille d'entrée), stop-follow leader en drawdown,
filtre de session/heure. Pur / paper.
"""

from __future__ import annotations


def dca_ladder(total_notional: float, n_entries: int, spacing_bps: float) -> list[tuple[float, float]]:
    """Grille d'entrée : n tranches espacées de spacing_bps. [(offset_bps, notional_slice)]."""
    if n_entries <= 0 or total_notional <= 0:
        return []
    slice_n = float(total_notional) / int(n_entries)
    return [(round(i * float(spacing_bps), 4), round(slice_n, 6)) for i in range(int(n_entries))]


def leader_drawdown_stop(leader_drawdown_pct: float, *, max_leader_dd_pct: float = 15.0) -> bool:
    """Vrai si on doit CESSER de suivre un leader qui se dégrade (drawdown récent)."""
    return float(leader_drawdown_pct) >= float(max_leader_dd_pct)


def session_allows(hour_utc: int, *, blocked_hours=()) -> bool:
    """Faux si l'heure (UTC) est dans les plages coupées (faible edge / spreads larges)."""
    blocked = {int(h) % 24 for h in blocked_hours}
    return (int(hour_utc) % 24) not in blocked


__all__ = ["dca_ladder", "leader_drawdown_stop", "session_allows"]
