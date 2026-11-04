"""BIAIS DE SELECTION de la recherche de scenarios -- trouve dans le code le 2026-07-12.

LE BUG
------
`search()` faisait :

    scored.sort(key=net_total_usd sur TRAIN, reverse=True)   # tri par PnL train
    for sc in scored[:top_k]:                                 # on garde les 40 PREMIERS
        ... evaluer sur TEST ...

Sur des millions de scenarios, **les 40 meilleurs sur train SONT, par construction, les 40 qui
sur-ajustent le plus** : ce sont ceux qui ont le mieux epouse le bruit. On les envoie au test,
ils echouent, et on conclut "data-limited".

**Une config au PnL train MEDIOCRE mais au comportement ROBUSTE n'atteint JAMAIS le test set.**

Ca suffit a expliquer `robust_count = 0` -- sans lookahead, sans manque de donnees.

CE QUE CE MODULE APPORTE
------------------------
1. `worst_coin_net()` -- le net du PIRE MARCHE, pas la somme.
   Une config qui fait +300 $ sur un memecoin et -5 $ sur les 231 autres a une SOMME excellente
   et un PIRE MARCHE mauvais. La somme la retient ; le pire marche la rejette. (MINIMAX.)

2. `select_for_test()` -- n'envoie plus au test SEULEMENT les champions du train :
     - le top-K par somme       (l'ancien comportement, conserve pour COMPARER)
     - le top-K par PIRE MARCHE (le critere robuste)
     - un echantillon STRATIFIE sur toute la distribution (le CONTROLE : si une config
       mediocre-sur-train survit au test aussi bien qu'un champion, alors le classement
       par train ne selectionne RIEN d'utile -- et c'est un resultat en soi)

On ne SUPPRIME pas l'ancien chemin : on le MESURE contre le nouveau. Si les deux donnent
`robust_count = 0`, le verdict "data-limited" se renforce. S'ils different, on avait tort.

REPLAY-only. Aucun ordre, aucun ledger, aucune promesse de PnL.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "worst_coin_net",
    "coin_breakdown",
    "select_for_test",
    "SelectionReport",
    "bootstrap_day_position_intervals",
    "bootstrap_blocs_journees_positions",
]

MIN_TRADES_PAR_COIN = 5  # sous ce seuil, un coin n'est pas une preuve -- c'est du bruit


def coin_breakdown(by_coin, *, min_trades_par_coin: int = MIN_TRADES_PAR_COIN) -> dict:
    """Net par coin, en ne gardant que les coins avec assez de trades pour signifier quelque chose."""
    retenus = {}
    ignores = {}
    for coin, pnls in (by_coin or {}).items():
        if len(pnls) >= int(min_trades_par_coin):
            retenus[coin] = round(sum(pnls), 4)
        else:
            ignores[coin] = len(pnls)
    return {"nets": retenus, "coins_retenus": len(retenus), "coins_ignores": ignores}


def worst_coin_net(by_coin, *, min_trades_par_coin: int = MIN_TRADES_PAR_COIN) -> float | None:
    """Le net du PIRE marche (MINIMAX). None si aucun coin n'a assez de trades.

    None n'est PAS 0 : c'est "on ne sait pas". Un scenario sans preuve par coin ne doit pas
    etre classe comme s'il valait zero -- deny-by-default.
    """
    nets = coin_breakdown(by_coin, min_trades_par_coin=min_trades_par_coin)["nets"]
    if not nets:
        return None
    return min(nets.values())


class SelectionReport(dict):
    """Rapport de selection : QUI a ete envoye au test, et POURQUOI."""


def _idx_stratifie(n: int, k: int) -> list[int]:
    """k indices repartis UNIFORMEMENT sur [0, n) -- le controle.

    Deterministe (pas de random) : rejouable a l'identique, comme tout le reste du replay.
    """
    if n <= 0 or k <= 0:
        return []
    if k >= n:
        return list(range(n))
    pas = n / float(k)
    return sorted({min(n - 1, int(i * pas)) for i in range(k)})


def select_for_test(scored, *, top_k: int = 40, worst_by_scenario=None,
                    controle_k: int = 20) -> SelectionReport:
    """Choisit les scenarios a evaluer sur le TEST -- sans le biais de selection.

    `scored`            : liste [(scenario, rapport_train)] DEJA triee par net train decroissant.
    `worst_by_scenario` : dict {id(scenario) -> net du pire coin} (ou None si non calcule).
    `controle_k`        : taille de l'echantillon stratifie (le controle).

    Rend : {"a_tester": [scenarios], "origine": {id: ["top_net", "top_worst", "controle"]}, ...}
    Un meme scenario peut avoir PLUSIEURS origines -- on garde toutes ses etiquettes.
    """
    scored = list(scored or [])
    n = len(scored)
    origine: dict[int, list[str]] = {}

    def _marquer(i: int, tag: str) -> None:
        origine.setdefault(i, [])
        if tag not in origine[i]:
            origine[i].append(tag)

    # 1) l'ANCIEN comportement : les champions du train (conserve pour comparaison)
    for i in range(min(max(1, int(top_k)), n)):
        _marquer(i, "top_net")

    # 2) le critere ROBUSTE : les meilleurs sur le PIRE marche (MINIMAX)
    if worst_by_scenario:
        avec_worst = [
            (i, worst_by_scenario.get(id(sc)))
            for i, (sc, _rep) in enumerate(scored)
            if worst_by_scenario.get(id(sc)) is not None
        ]
        avec_worst.sort(key=lambda t: t[1], reverse=True)
        for i, _w in avec_worst[: max(1, int(top_k))]:
            _marquer(i, "top_worst")

    # 3) le CONTROLE : un echantillon uniforme de TOUTE la distribution train.
    #    Si des configs mediocres-sur-train survivent au test aussi bien que les champions,
    #    alors le classement par train ne selectionne rien d'utile. C'est un resultat.
    for i in _idx_stratifie(n, int(controle_k)):
        _marquer(i, "controle")

    indices = sorted(origine)
    return SelectionReport({
        "a_tester": [scored[i][0] for i in indices],
        "origines": [origine[i] for i in indices],
        "n_scores": n,
        "n_a_tester": len(indices),
        "n_top_net": sum(1 for v in origine.values() if "top_net" in v),
        "n_top_worst": sum(1 for v in origine.values() if "top_worst" in v),
        "n_controle": sum(1 for v in origine.values() if "controle" in v),
        "note": (
            "top_net = ancien comportement (biais de selection : les champions du train sont "
            "les plus sur-ajustes). top_worst = MINIMAX par coin. controle = echantillon "
            "stratifie -- si le controle survit autant que top_net, le tri par train ne "
            "selectionne rien."
        ),
    })


def bootstrap_day_position_intervals(
    observations: Sequence[Mapping[str, Any]] | Mapping[Any, Mapping[Any, Any]],
    *,
    value_field: str = "net_usd",
    day_field: str = "day_id",
    position_field: str = "position_id",
    n: int = 2000,
    confidence: float = 0.95,
    seed: int = 7,
) -> dict[str, Any]:
    """Hierarchical bootstrap by day and position, preserving episode concentration.

    Rows may be supplied as ``{day: {position: value}}`` or as mappings with
    ``day_field``, ``position_field`` and ``value_field``. Repeated rows for one
    position are aggregated before resampling, so position fragments cannot
    inflate the apparent sample size. Days are sampled with replacement and each
    sampled day resamples its own positions with replacement. The statistic is
    the equally-day-weighted mean of position values. Invalid or missing data
    return ``UNMEASURABLE``; no zero or fabricated observation is inserted.
    """
    base: dict[str, Any] = {
        "status": "UNMEASURABLE",
        "verdict": "INSUFFISANT",
        "reason": None,
        "n_rows": 0,
        "n_days": 0,
        "n_positions": 0,
        "n_bootstrap": 0,
        "confidence": confidence,
        "statistic": "day_equal_mean",
        "observed_mean": None,
        "bootstrap_mean": None,
        "bootstrap_std": None,
        "ci_low": None,
        "ci_high": None,
        "real_execution": False,
    }
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        base["reason"] = "n_bootstrap_invalide"
        return base
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        base["reason"] = "confidence_invalide"
        return base
    confidence = float(confidence)
    base["confidence"] = confidence
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        base["reason"] = "confidence_invalide"
        return base
    if not isinstance(seed, int) or isinstance(seed, bool):
        base["reason"] = "seed_invalide"
        return base

    rows: list[dict[str, Any]] = []
    if isinstance(observations, Mapping):
        for day, positions in observations.items():
            if not isinstance(positions, Mapping):
                base["reason"] = "positions_invalide"
                return base
            for position, value in positions.items():
                rows.append({day_field: day, position_field: position, value_field: value})
    elif isinstance(observations, Sequence) and not isinstance(observations, (str, bytes)):
        rows = list(observations)
    else:
        base["reason"] = "observations_invalide"
        return base

    base["n_rows"] = len(rows)
    grouped: dict[Any, dict[Any, float]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            base["reason"] = "ligne_invalide"
            return base
        if day_field not in row or position_field not in row or value_field not in row:
            base["reason"] = "champ_manquant"
            return base
        day = row[day_field]
        position = row[position_field]
        value = row[value_field]
        if day is None or position is None or isinstance(value, bool):
            base["reason"] = "identifiant_ou_valeur_invalide"
            return base
        try:
            hash((day, position))
            numeric = float(value)
        except (TypeError, ValueError):
            base["reason"] = "identifiant_ou_valeur_invalide"
            return base
        if not math.isfinite(numeric):
            base["reason"] = "valeur_non_finie"
            return base
        grouped.setdefault(day, {})[position] = grouped.setdefault(day, {}).get(position, 0.0) + numeric

    position_count = sum(len(positions) for positions in grouped.values())
    base["n_days"] = len(grouped)
    base["n_positions"] = position_count
    if len(grouped) < 2 or position_count < 2:
        base["reason"] = "concentration_insuffisante"
        return base
    day_means = {
        day: statistics.fmean(positions.values()) for day, positions in grouped.items()
    }
    base["observed_mean"] = statistics.fmean(day_means.values())
    rng = random.Random(seed)
    days = list(grouped)
    bootstrap_means: list[float] = []
    for _ in range(n):
        sampled_days = [rng.choice(days) for _ in days]
        sampled_day_means: list[float] = []
        for day in sampled_days:
            positions = list(grouped[day].values())
            sampled_positions = [rng.choice(positions) for _ in positions]
            sampled_day_means.append(statistics.fmean(sampled_positions))
        bootstrap_means.append(statistics.fmean(sampled_day_means))

    ordered = sorted(bootstrap_means)

    def quantile(q: float) -> float:
        offset = (len(ordered) - 1) * q
        lower = math.floor(offset)
        upper = math.ceil(offset)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (offset - lower)

    alpha = (1.0 - confidence) / 2.0
    base.update(
        status="PROVEN",
        verdict="MESURE_STATISTIQUE",
        n_bootstrap=n,
        bootstrap_mean=statistics.fmean(bootstrap_means),
        bootstrap_std=statistics.pstdev(bootstrap_means),
        ci_low=quantile(alpha),
        ci_high=quantile(1.0 - alpha),
    )
    return base


def bootstrap_blocs_journees_positions(observations: Sequence[Mapping[str, Any]] | Mapping[Any, Mapping[Any, Any]], **kwargs: Any) -> dict[str, Any]:
    """French alias for ``bootstrap_day_position_intervals``."""
    return bootstrap_day_position_intervals(observations, **kwargs)
