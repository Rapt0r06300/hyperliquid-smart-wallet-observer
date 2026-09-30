"""Fail-safe par défaut — pur, testé (IDEA-98). En cas de moindre doute sur les données, on renvoie
TOUJOURS NO_TRADE (deny-by-default). C'est le garde-fou d'ultime recours. Aucun ordre réel.
"""
from __future__ import annotations


def safe_default_decision(data_ok: bool, *, reason: str = "") -> dict:
    """Renvoie NO_TRADE si les données ne sont pas explicitement OK ; sinon autorise l'évaluation.
    Le défaut sûr est TOUJOURS de ne rien faire."""
    if not data_ok:
        return {"decision": "NO_TRADE", "reason": reason or "INSUFFICIENT_DATA_FAILSAFE"}
    return {"decision": "EVALUATE", "reason": "data_ok"}
