"""Intelligence prédictive de l'activité des leaders — idées #82-90.

Fonctions PURES (0 réseau, testables) qui prédisent l'activité à venir d'un leader à partir
de l'historique de ses fills, pour prioriser les slots rares (WS) vers ceux qui vont trader.

- `debit_ewma` : débit lissé (fills/min) avec demi-vie → réactif sans bruit.
- `profil_horaire` : activité par heure-de-journée (UTC) → prioriser aux heures actives.
- `momentum` : accélération récente vs base → détecter un réveil.
- `predire_fenetre` : fills attendus sur la prochaine fenêtre (EWMA × facteur horaire × momentum).
- `classer_leaders` : tri décroissant par score prédit.

PAPER / lecture seule. Aucune décision d'ordre — uniquement de l'allocation d'attention.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

MINUTE_MS = 60_000


def debit_ewma(timestamps_ms: Sequence[int], *, now_ms: int, demi_vie_min: float = 10.0) -> float:
    """Débit lissé (fills/min) : chaque fill pèse 0.5**(age_min/demi_vie)."""
    if not timestamps_ms or demi_vie_min <= 0:
        return 0.0
    lam = math.log(2) / demi_vie_min
    poids = 0.0
    for ts in timestamps_ms:
        age_min = max(0.0, (now_ms - ts) / MINUTE_MS)
        poids += math.exp(-lam * age_min)
    # normalise par la "masse" d'une fenêtre d'1 demi-vie → fills/min effectifs
    return poids / demi_vie_min


def profil_horaire(timestamps_ms: Iterable[int]) -> dict[int, int]:
    """Nombre de fills par heure-de-journée UTC (0..23)."""
    prof: dict[int, int] = {}
    for ts in timestamps_ms:
        h = int((ts // 3_600_000) % 24)
        prof[h] = prof.get(h, 0) + 1
    return prof


def facteur_horaire(prof: Mapping[int, int], heure_utc: int) -> float:
    """Poids [~0.5..2] de l'heure courante vs la moyenne horaire (1.0 = moyen)."""
    if not prof:
        return 1.0
    total = sum(prof.values())
    moyenne = total / 24.0
    if moyenne <= 0:
        return 1.0
    val = prof.get(int(heure_utc) % 24, 0)
    return max(0.25, min(3.0, val / moyenne))


def momentum(timestamps_ms: Sequence[int], *, now_ms: int,
             fenetre_courte_min: float = 5.0, fenetre_base_min: float = 30.0) -> float:
    """Ratio débit récent / débit de base (>1 = accélération)."""
    court = debit_ewma(timestamps_ms, now_ms=now_ms, demi_vie_min=fenetre_courte_min)
    base = debit_ewma(timestamps_ms, now_ms=now_ms, demi_vie_min=fenetre_base_min)
    if base <= 1e-9:
        return 1.0 if court <= 1e-9 else 2.0
    return max(0.1, min(5.0, court / base))


def predire_fenetre(timestamps_ms: Sequence[int], *, now_ms: int, heure_utc: int | None = None,
                    fenetre_min: float = 15.0) -> float:
    """Fills attendus sur la prochaine `fenetre_min` minutes."""
    ewma = debit_ewma(timestamps_ms, now_ms=now_ms)
    prof = profil_horaire(timestamps_ms)
    h = heure_utc if heure_utc is not None else int((now_ms // 3_600_000) % 24)
    fh = facteur_horaire(prof, h)
    mo = momentum(timestamps_ms, now_ms=now_ms)
    return max(0.0, ewma * fenetre_min * fh * mo)


def classer_leaders(historiques: Mapping[str, Sequence[int]], *, now_ms: int,
                    heure_utc: int | None = None, fenetre_min: float = 15.0) -> list[tuple[str, float]]:
    """(leader, fills_prevus) triés décroissant — les premiers méritent les slots WS."""
    scores = [(lead, predire_fenetre(ts, now_ms=now_ms, heure_utc=heure_utc, fenetre_min=fenetre_min))
              for lead, ts in historiques.items()]
    scores.sort(key=lambda p: (-p[1], p[0]))
    return scores
