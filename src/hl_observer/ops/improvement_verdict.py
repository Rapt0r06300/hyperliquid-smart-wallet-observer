"""AUD-146 — verdict CONSERVER / ANNULER par amelioration.

Apres avoir applique et mesure une amelioration (avant/apres), verdict binaire : CONSERVER si le
gain net depasse un seuil, sinon ANNULER (rollback). On ne garde jamais une "amelioration" qui
n'ameliore pas. Read-only.
"""
from __future__ import annotations

CONSERVER = "CONSERVER"
ANNULER = "ANNULER"


def verdict_amelioration(*, avant: float, apres: float, seuil: float = 0.0, sens: str = "hausse") -> dict:
    delta = round(float(apres) - float(avant), 8)
    gain = delta if sens == "hausse" else -delta
    verdict = CONSERVER if gain > float(seuil) else ANNULER
    return {"verdict": verdict, "delta": delta, "gain_net": round(gain, 8), "seuil": float(seuil),
            "rollback": verdict == ANNULER}


__all__ = ["verdict_amelioration", "CONSERVER", "ANNULER"]
