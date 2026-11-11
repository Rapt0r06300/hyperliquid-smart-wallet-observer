"""Signaux Copy-Vault ÉVALUABLES : ceux qui disposent d'un carnet causal au moment du signal.

Un signal sans carnet observé juste avant lui ne peut produire aucun trade en replay (pas de prix
exécutable, donc refus). Deux conséquences mesurées le 2026-11-10 quand on l'ignorait :

* la découpe TRAIN / VALIDATION / OOS était faite sur TOUS les jours de signal (768 jours
  d'historique sans carnet + quelques jours avec) : TRAIN tombait entièrement dans la période
  sans carnet, et 133 676 jeux de paramètres ont été essayés sur une entrée structurellement vide ;
* le contrôle d'alignement reconstruisait la liste des horodatages de carnet pour chaque signal
  (coût quadratique, impraticable sur des centaines de milliers de signaux).

Ce module pur calcule l'alignement une fois, en temps quasi linéaire, et rend les horodatages des
signaux évaluables : c'est sur eux que la découpe temporelle doit porter. La règle ne dépend que
de la DISPONIBILITÉ des données (carnet reçu au plus tard au signal), jamais d'un résultat.
"""
from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from typing import Any

#: âge maximal du dernier carnet connu au moment du signal (même borne que le contrôle historique)
MAX_BOOK_AGE_MS = 30_000
DAY_MS = 86_400_000
#: Un jour ne sert de base à la découpe que s'il porte au moins ce nombre de signaux évaluables.
#: Mesuré le 2026-11-11 : une quinzaine de signaux isolés, étalés sur des jours d'octobre, suffisaient
#: à franchir le minimum de jours ; TRAIN ne contenait alors que ces signaux isolés et tous les
#: jours denses tombaient en VALIDATION / OOS (recherche de nouveau quasi vide, très lente).
MIN_SIGNALS_PER_DAY = 10


def evaluable_signals(
    metaorders: Sequence[Mapping[str, Any]],
    books: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    max_book_age_ms: int = MAX_BOOK_AGE_MS,
    min_signals_per_day: int | None = None,
) -> dict[str, Any]:
    """Horodatages des signaux ayant un carnet causal récent, et décomptes d'audit.

    ``timestamps`` : instants de signal évaluables des jours DENSES (au moins
    ``min_signals_per_day`` signaux évaluables) : c'est la base de la découpe temporelle.
    ``aligned_adds`` : nombre de signaux ``ADD`` évaluables, tous jours confondus (contrat
    historique du labo). ``summary`` : décomptes par action et par jour UTC, pour les rapports.
    """
    if min_signals_per_day is None:
        min_signals_per_day = MIN_SIGNALS_PER_DAY          # lu à l'appel : règle unique du module
    horloges: dict[str, list[int]] = {}
    for coin, rows in books.items():
        stamps = [int(row["ts_ms"]) for row in rows]
        if any(stamps[i] > stamps[i + 1] for i in range(len(stamps) - 1)):
            stamps.sort()
        horloges[str(coin)] = stamps
    timestamps: list[int] = []
    par_action: dict[str, int] = {}
    par_jour: dict[int, int] = {}
    aligned_adds = 0
    for row in metaorders:
        stamps = horloges.get(str(row.get("coin")))
        if not stamps:
            continue
        signal_ms = int(row["signal_ts_ms"])
        index = bisect.bisect_right(stamps, signal_ms) - 1
        if index < 0 or signal_ms - stamps[index] > max_book_age_ms:
            continue
        action = str(row.get("action") or "").upper()
        timestamps.append(signal_ms)
        par_action[action] = par_action.get(action, 0) + 1
        par_jour[signal_ms // DAY_MS] = par_jour.get(signal_ms // DAY_MS, 0) + 1
        if action == "ADD":
            aligned_adds += 1
    denses = {day for day, count in par_jour.items() if count >= int(min_signals_per_day)}
    return {
        "timestamps": [ts for ts in timestamps if ts // DAY_MS in denses],
        "aligned_adds": aligned_adds,
        "summary": {
            "signals": len(metaorders),
            "evaluable_signals": len(timestamps),
            "evaluable_by_action": dict(sorted(par_action.items())),
            "evaluable_utc_days": len(denses),
            "sparse_utc_days_excluded_from_split": len(par_jour) - len(denses),
            "evaluable_signals_per_utc_day": {str(day): count for day, count in sorted(par_jour.items())},
            "min_signals_per_day": int(min_signals_per_day),
            "max_book_age_ms": int(max_book_age_ms),
            "rule": "CAUSAL_BOOK_AT_OR_BEFORE_SIGNAL_WITHIN_MAX_AGE_ON_DENSE_DAYS",
        },
    }


__all__ = ["MAX_BOOK_AGE_MS", "MIN_SIGNALS_PER_DAY", "evaluable_signals"]
