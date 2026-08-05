"""AUD-114 — ALERTE quand TOUS les signaux d'un cycle sont sized a zero.

Si chaque signal candidat d'un cycle est dimensionne a zero (aucune position possible), rester
silencieux masque un probleme (sizing trop strict, capital nul, edge partout sous le minimum).
Alerte LOCALE (jamais une action externe). Distincte du diagnostic post-hoc ALL_SIGNALS_REFUSED :
ici c'est une alerte EN LIGNE sur le sizing du cycle courant. Read-only, paper.
"""
from __future__ import annotations

from typing import Any, Iterable

from hl_observer.alerts.local_alerts import LocalAlerts

KIND = "ALL_SIGNALS_SIZED_TO_ZERO"


def _taille(sig: Any) -> float:
    if isinstance(sig, dict):
        for k in ("notional_usd", "notional", "size_usd", "taille", "size"):
            if k in sig:
                try:
                    return float(sig[k])
                except (TypeError, ValueError):
                    return 0.0
        return 0.0
    for k in ("notional_usd", "notional", "size"):
        v = getattr(sig, k, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def evaluer_signaux_tous_a_zero(signaux: Iterable[Any], *, alerts: LocalAlerts | None = None,
                                now_ms: int | None = None) -> dict:
    """{tous_a_zero, n, n_non_nuls, alerte}. Emet une alerte ssi il y a AU MOINS un signal ET qu'ils
    sont TOUS sized a zero (un cycle vide n'est PAS une alerte)."""
    sigs = list(signaux)
    n = len(sigs)
    non_nuls = sum(1 for s in sigs if _taille(s) > 0.0)
    tous_a_zero = n > 0 and non_nuls == 0
    alerte = None
    if tous_a_zero and alerts is not None:
        alerte = alerts.raise_alert(
            kind=KIND,
            message="Les %d signaux du cycle sont tous sized a zero (aucune position possible)." % n,
            now_ms=now_ms)
    return {"tous_a_zero": tous_a_zero, "n": n, "n_non_nuls": non_nuls, "alerte": alerte}


__all__ = ["evaluer_signaux_tous_a_zero", "KIND"]
