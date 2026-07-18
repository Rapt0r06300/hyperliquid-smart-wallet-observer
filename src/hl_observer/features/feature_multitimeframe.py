"""J4 — FEATURES MULTI-TIMEFRAME sans lookahead.

Aligner une feature LENTE (ex. 1h) sur une timeline RAPIDE (ex. 1m) : à l'instant t, on utilise la
DERNIÈRE valeur lente DÉJÀ CLÔTURÉE (ts <= t), jamais la barre en cours ni future. Même garde
point-in-time que le feature store. PAPER only.
"""
from __future__ import annotations

import bisect
from typing import Sequence


def aligner(serie_lente: Sequence[tuple[int, float]], timeline: Sequence[int]) -> list[float | None]:
    """`serie_lente` = [(ts_ms, valeur)] (barres clôturées). Pour chaque t de `timeline`, la dernière
    valeur lente avec ts <= t (None avant la 1re). Aucune lecture du futur."""
    lente = sorted((int(ts), float(v)) for ts, v in (serie_lente or []))
    ts_list = [ts for ts, _ in lente]
    out: list[float | None] = []
    for t in timeline or []:
        i = bisect.bisect_right(ts_list, int(t)) - 1
        out.append(lente[i][1] if i >= 0 else None)
    return out


__all__ = ["aligner"]
