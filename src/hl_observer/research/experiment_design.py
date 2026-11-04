"""[AUD-175/177/212] Plans d'experiences : plan factoriel complet, suite basse-discrepance
(Halton, quasi-Monte-Carlo, space-filling, alternative deterministe a Sobol), successive halving
multi-fidelite, et classement par gain d'information. Deterministe, stdlib pure, 0 reseau."""
from __future__ import annotations

import math
from itertools import product
from typing import Any, Callable, Mapping, Sequence

_PREMIERS = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)


def plan_factoriel(niveaux_par_facteur: Mapping[str, Sequence]) -> list[dict]:
    """Plan factoriel COMPLET : produit cartesien de tous les niveaux (ordre stable, deterministe)."""
    noms = list(niveaux_par_facteur.keys())
    combos = product(*(list(niveaux_par_facteur[n]) for n in noms))
    return [dict(zip(noms, c)) for c in combos]


def _halton(index: int, base: int) -> float:
    f, r, i = 1.0, 0.0, index
    while i > 0:
        f /= base
        r += f * (i % base)
        i //= base
    return r


def suite_basse_discrepance(dim: int, n: int, *, debut: int = 1) -> list[tuple]:
    """Suite de Halton en dimension `dim` (quasi-MC space-filling). Remplit [0,1)^dim bien plus
    uniformement qu'un tirage pseudo-aleatoire -> meilleure couverture d'espace a budget egal."""
    if dim < 1 or dim > len(_PREMIERS):
        raise ValueError("dim doit etre entre 1 et %d" % len(_PREMIERS))
    return [tuple(_halton(debut + k, _PREMIERS[d]) for d in range(dim)) for k in range(n)]


def successive_halving(configs: Sequence, evaluer: Callable[[object, int], float], *,
                       budget_init: int = 1, facteur: int = 2, budget_max: int | None = None) -> list:
    """Multi-fidelite : evalue toutes les configs a petit budget, garde le meilleur 1/facteur,
    multiplie le budget par `facteur`, recommence. Rend les survivants (meilleur d'abord)."""
    if facteur < 2:
        raise ValueError("facteur >= 2")
    survivants = list(configs)
    budget = max(1, int(budget_init))
    while len(survivants) > 1:
        notes = [(c, float(evaluer(c, budget))) for c in survivants]
        notes.sort(key=lambda t: t[1], reverse=True)
        garde = max(1, len(notes) // facteur)
        survivants = [c for c, _ in notes[:garde]]
        if budget_max is not None and budget >= budget_max:
            break
        budget *= facteur
    return survivants


def classer_par_information_gain(candidats: Sequence[Mapping]) -> list[dict]:
    """Ordonne les candidats par GAIN D'INFORMATION attendu decroissant : tester d'abord ce qui
    reduit le plus l'incertitude. Proxy = incertitude/variance fournie."""
    enrichis = []
    for i, c in enumerate(candidats):
        incert = float(c.get("incertitude", c.get("variance", 0.0)))
        enrichis.append({**dict(c), "rang": 0, "information_gain": incert, "_i": i})
    enrichis.sort(key=lambda d: (-d["information_gain"], d["_i"]))
    for r, d in enumerate(enrichis, 1):
        d["rang"] = r
        d.pop("_i", None)
    return enrichis


def shift_signal_times_as_negative_control(
    rows: Sequence[Mapping[str, Any]],
    *,
    shift_ms: int,
    signal_ts_field: str = "signal_ts_ms",
    outcome_ts_field: str = "outcome_ts_ms",
    episode_id_field: str = "episode_id",
) -> dict[str, Any]:
    """Create a future-shifted signal control without certifying it.

    The original rows are copied read-only. A positive shift is applied only to
    signal timestamps. The control is ``REJECTED`` when shifted signals are at or
    after their observed outcome, and ``UNMEASURABLE`` when the shift never
    crosses an outcome (it is then not a genuine future control). It can never
    return ``PROVEN`` and does not alter any outcome or PnL value.
    """
    result: dict[str, Any] = {
        "status": "UNMEASURABLE",
        "verdict": "NEGATIVE_CONTROL",
        "reason": None,
        "shift_ms": shift_ms,
        "n_rows": len(rows or []),
        "n_future_shifted": 0,
        "proven": False,
        "real_execution": False,
        "shifted_rows": [],
    }
    if isinstance(shift_ms, bool) or not isinstance(shift_ms, int) or shift_ms <= 0:
        result["reason"] = "shift_invalide"
        return result
    seen: set[str] = set()
    shifted: list[dict[str, Any]] = []
    future_count = 0
    for row in list(rows or []):
        if not isinstance(row, Mapping):
            result["reason"] = "ligne_invalide"
            return result
        if any(field not in row for field in (episode_id_field, signal_ts_field, outcome_ts_field)):
            result["reason"] = "champ_manquant"
            return result
        episode_id = row[episode_id_field]
        signal_ts = row[signal_ts_field]
        outcome_ts = row[outcome_ts_field]
        if episode_id is None or isinstance(episode_id, (list, dict, set)):
            result["reason"] = "episode_invalide"
            return result
        episode_key = str(episode_id)
        if not episode_key or episode_key in seen:
            result["reason"] = "episode_duplique"
            return result
        seen.add(episode_key)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in (signal_ts, outcome_ts)):
            result["reason"] = "timestamp_invalide"
            return result
        shifted_ts = signal_ts + shift_ms
        is_future = shifted_ts >= outcome_ts
        if is_future:
            future_count += 1
        shifted_row = dict(row)
        shifted_row[signal_ts_field] = shifted_ts
        shifted_row["negative_control"] = True
        shifted_row["causal_eligible"] = False
        shifted_row["future_signal_vs_outcome"] = is_future
        shifted.append(shifted_row)
    result["shifted_rows"] = shifted
    result["n_future_shifted"] = future_count
    if not shifted:
        result["reason"] = "aucune_ligne"
    elif future_count == 0:
        result["reason"] = "shift_ne_deplace_aucun_signal_dans_le_futur"
    elif future_count == len(shifted):
        result.update(status="REJECTED", reason="signal_futur_non_causal")
    else:
        result.update(status="REJECTED", reason="controle_partiellement_non_causal")
    return result


def decaler_signaux_controle_negatif(rows: Sequence[Mapping[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """French alias for ``shift_signal_times_as_negative_control``."""
    return shift_signal_times_as_negative_control(rows, **kwargs)


def signal_shift_negative_control_receipt(rows: Sequence[Mapping[str, Any]], *, shift_ms: int) -> dict[str, Any]:
    """ECO-166 receipt: a future shift is explicitly rejected, never promoted."""
    result = shift_signal_times_as_negative_control(rows, shift_ms=shift_ms)
    if result.get("status") == "REJECTED" and result.get("n_future_shifted", 0) > 0:
        result["status"] = "PROVEN"
        result["verdict"] = "FUTURE_SIGNAL_REJECTED"
    result.update(contract="ECO-166-negative-control", paper_read_only=True, promotion="DISABLED_UNTIL_REVIEW")
    return result


def frozen_dataset_ablation_receipt(
    baseline_rows: Sequence[Mapping[str, Any]],
    ablation_rows: Sequence[Mapping[str, Any]],
    *,
    dataset_hash_field: str = "dataset_hash",
    cutoff_field: str = "cutoff_ms",
) -> dict[str, Any]:
    """ECO-167: ablations are comparable only on one immutable dataset/cutoff."""
    rows = list(baseline_rows or []) + list(ablation_rows or [])
    hashes = {str(row.get(dataset_hash_field) or "") for row in rows if isinstance(row, Mapping)}
    cutoffs = {row.get(cutoff_field) for row in rows if isinstance(row, Mapping)}
    valid = bool(rows) and len(rows) == len([row for row in rows if isinstance(row, Mapping)]) and len(hashes) == 1 and "" not in hashes and len(cutoffs) == 1
    return {
        "status": "PROVEN" if valid else "UNMEASURABLE",
        "verdict": "FROZEN_DATASET_ABLATION" if valid else "DATASET_FREEZE_INVALID",
        "dataset_hash": next(iter(hashes)) if valid else None,
        "cutoff_ms": next(iter(cutoffs)) if valid else None,
        "baseline_rows": len(baseline_rows or []), "ablation_rows": len(ablation_rows or []),
        "paper_read_only": True, "real_execution": False,
    }


def neighbor_parameter_plateau_receipt(
    results: Sequence[Mapping[str, Any]],
    *,
    parameter_fields: Sequence[str],
    metric_field: str = "net_pnl_bps",
    tolerance: float = 0.05,
) -> dict[str, Any]:
    """ECO-168: require adjacent parameter points near the best score."""
    if not parameter_fields or tolerance < 0:
        return {"status": "UNMEASURABLE", "reason": "invalid_plateau_contract", "paper_read_only": True}
    parsed: list[tuple[dict[str, Any], float]] = []
    for row in results or ():
        if not isinstance(row, Mapping):
            return {"status": "UNMEASURABLE", "reason": "invalid_row", "paper_read_only": True}
        try:
            metric = float(row.get(metric_field))
        except (TypeError, ValueError):
            return {"status": "UNMEASURABLE", "reason": "missing_metric", "paper_read_only": True}
        if not math.isfinite(metric) or any(field not in row for field in parameter_fields):
            return {"status": "UNMEASURABLE", "reason": "invalid_parameter_point", "paper_read_only": True}
        parsed.append((dict(row), metric))
    if len(parsed) < 3:
        return {"status": "MORE_DATA", "reason": "need_neighbor_points", "paper_read_only": True}
    best = max(metric for _, metric in parsed)
    scale = max(abs(best), 1.0)
    near = [row for row, metric in parsed if abs(metric - best) <= scale * tolerance]
    neighbor_pairs = 0
    for left, _ in parsed:
        for right, _ in parsed:
            distance = sum(left[field] != right[field] for field in parameter_fields)
            if distance == 1 and left in near and right in near:
                neighbor_pairs += 1
    status = "PROVEN" if neighbor_pairs >= 2 else "MORE_DATA"
    return {
        "status": status, "verdict": "NEIGHBOR_PARAMETER_PLATEAU" if status == "PROVEN" else "NO_PLATEAU",
        "best_metric": best, "near_best_points": len(near), "neighbor_pairs": neighbor_pairs,
        "tolerance": tolerance, "paper_read_only": True, "real_execution": False,
    }
