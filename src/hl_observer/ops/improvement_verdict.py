"""AUD-146 — verdict CONSERVER / ANNULER par amelioration.

Apres avoir applique et mesure une amelioration (avant/apres), verdict binaire : CONSERVER si le
gain net depasse un seuil, sinon ANNULER (rollback). On ne garde jamais une "amelioration" qui
n'ameliore pas. Read-only.
"""
from __future__ import annotations

CONSERVER = "CONSERVER"
ANNULER = "ANNULER"


def classify_relative_progress(*, avant: float, apres: float, sens: str = "hausse") -> dict:
    """Separate relative improvement from absolute profitability."""
    import math
    try:
        before = float(avant)
        after = float(apres)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "NON_NUMERIC_METRIC", "paper_read_only": True}
    if sens not in {"hausse", "baisse"}:
        return {"status": "UNMEASURABLE", "reason": "UNKNOWN_DIRECTION", "paper_read_only": True}
    if not math.isfinite(before) or not math.isfinite(after):
        return {"status": "UNMEASURABLE", "reason": "NON_FINITE_METRIC", "paper_read_only": True}
    delta = after - before
    gain = delta if sens == "hausse" else -delta
    return {
        "status": "PROVEN" if gain > 0 else "REJECTED",
        "relative_improvement": gain > 0,
        "delta": round(delta, 8),
        "gain": round(gain, 8),
        "absolute_profitability": "PROFITABLE" if after > 0 else "NOT_PROFITABLE",
        "promotion_allowed": False,
        "paper_read_only": True,
    }


def verdict_amelioration(*, avant: float, apres: float, seuil: float = 0.0, sens: str = "hausse") -> dict:
    delta = round(float(apres) - float(avant), 8)
    gain = delta if sens == "hausse" else -delta
    verdict = CONSERVER if gain > float(seuil) else ANNULER
    return {"verdict": verdict, "delta": delta, "gain_net": round(gain, 8), "seuil": float(seuil),
            "rollback": verdict == ANNULER}


__all__ = ["verdict_amelioration", "classify_relative_progress", "CONSERVER", "ANNULER"]
