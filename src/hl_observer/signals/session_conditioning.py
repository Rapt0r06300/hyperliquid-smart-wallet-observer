"""G3 (article Punisher) — CONDITIONNEMENT par heure / session.

« US vs Asian hours, semaine vs week-end : la perf varie ENORMEMENT. » On expose le contexte
temporel (session, jour, week-end, heure UTC) pour conditionner un signal ou le carry. Un filtre
opt-in permet de n'autoriser que certaines sessions (ex. éviter la liquidité mince du week-end).

Ce module ne CREE pas d'edge : il permet de MESURER la perf par session et de FILTRER. Honnête :
quelle session est meilleure se valide sur données. PAPER only. UTC partout (pas d'ambiguïté locale).
"""
from __future__ import annotations

from datetime import datetime, timezone

# Sessions crypto approximatives en UTC (chevauchantes -> on prend la principale par heure).
SESSIONS = {"ASIE": range(0, 8), "EUROPE": range(8, 13), "US": range(13, 21), "SOIR": range(21, 24)}


def contexte_temporel(ts_ms: int) -> dict:
    d = datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=timezone.utc)
    h = d.hour
    session = next((nom for nom, plage in SESSIONS.items() if h in plage), "SOIR")
    jour = d.weekday()                                   # 0 = lundi ... 6 = dimanche
    return {"heure_utc": h, "session": session, "jour_semaine": jour,
            "weekend": jour >= 5, "heures_bureau": 8 <= h < 21}


def autorise_session(ts_ms: int, *, sessions_autorisees=None, autoriser_weekend: bool = True) -> bool:
    """Filtre OPT-IN. Par défaut True (on conditionne mais on ne bloque pas sans mesure).
    `sessions_autorisees` = set de sessions permises (None = toutes)."""
    ctx = contexte_temporel(ts_ms)
    if not autoriser_weekend and ctx["weekend"]:
        return False
    if sessions_autorisees is not None and ctx["session"] not in set(sessions_autorisees):
        return False
    return True


__all__ = ["SESSIONS", "contexte_temporel", "autorise_session"]
