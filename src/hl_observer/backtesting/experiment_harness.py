"""Harnais d'expérience standard (IMPROVE-13) + contrôle aléatoire (IMPROVE-11) + gate 'edge réel'
(IMPROVE-12). Toute nouvelle idée passe par là : entraîner sur le train, sélectionner en OOS,
comparer au HASARD, et n'être promue que si elle passe un critère décidé À L'AVANCE. Aucun ordre.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from statistics import median
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from hl_observer.backtesting import edge_predictor as ep
from hl_observer.backtesting.quant_methods import block_bootstrap


def run_experiment(x_train, y_train, x_test, nets_test, *, seed: int = 0, epochs: int = 120,
                   n_random: int = 30) -> dict:
    """Entraîne un logreg sur (x_train,y_train), sélectionne les trades prédits gagnants du test,
    et compare le net de cette sélection au net de sélections ALÉATOIRES de même taille."""
    mean, std = ep.fit_standardizer(x_train)
    w, b = ep.fit_logreg(ep.apply_standardizer(x_train, mean, std), y_train, epochs=epochs)
    prob = ep.predict_proba(ep.apply_standardizer(x_test, mean, std), w, b)
    sel_idx = [i for i in range(len(nets_test)) if prob[i] > 0.5]
    k = len(sel_idx)
    model_net = sum(nets_test[i] for i in sel_idx)
    rnd = []
    if 0 < k < len(nets_test):
        for s in range(int(n_random)):
            g = random.Random(seed + s)
            pick = g.sample(range(len(nets_test)), k)
            rnd.append(sum(nets_test[i] for i in pick))
    return {
        "selected": k,
        "model_net": round(model_net, 2),
        "random_net_median": round(median(rnd), 2) if rnd else 0.0,
        "random_net_max": round(max(rnd), 2) if rnd else 0.0,
        "beats_random": bool(rnd and model_net > max(rnd)),
    }


def mc_p5(nets, *, block: int = 10, n: int = 2000, seed: int = 7) -> float:
    """5e percentile du net total par bootstrap par blocs (borne basse honnête)."""
    dist = block_bootstrap(nets, block=block, n=n, seed=seed)
    if not dist:
        return 0.0
    dist.sort()
    return dist[max(0, int(0.05 * len(dist)))]


def promotion_gate(net_oos: float, trades: int, *, beats_random: bool, mc_p5_value: float,
                   min_trades: int = 30) -> dict:
    """Critère 'edge réel' FIXÉ À L'AVANCE : net>0 OOS ET bat le hasard ET p5 Monte-Carlo>0 ET
    assez de trades. Sans ce garde-fou, on finit toujours par couronner un mirage."""
    reasons = []
    if net_oos <= 0:
        reasons.append("NET_OOS_NOT_POSITIVE")
    if not beats_random:
        reasons.append("DOES_NOT_BEAT_RANDOM")
    if mc_p5_value <= 0:
        reasons.append("MC_P5_NOT_POSITIVE")
    if (trades or 0) < min_trades:
        reasons.append("TOO_FEW_TRADES")
    return {"promote": len(reasons) == 0, "reasons": reasons}


def _canonical_dataset_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return json.dumps(
        [dict(row) for row in rows],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def freeze_ablation_dataset(
    rows: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    episode_id_field: str = "episode_id",
    cutoff_ms: int | None = None,
) -> dict[str, Any]:
    """Freeze and hash one immutable episode set for every later ablation.

    The caller must provide the SAFE manifest hash, which must equal the canonical
    hash of the supplied rows. Missing, duplicate or non-mapping episodes fail
    closed. The returned snapshot is a private tuple of copied rows and can only
    be consumed read-only by ``evaluate_ablations_on_frozen_dataset``.
    """
    result: dict[str, Any] = {
        "status": "UNMEASURABLE",
        "verdict": "INSUFFICIENT_DATA",
        "reason": None,
        "dataset_id": dataset_id,
        "dataset_sha256": dataset_sha256,
        "content_sha256": None,
        "n_rows": 0,
        "episode_ids": [],
        "cutoff_ms": cutoff_ms,
        "paper_read_only": True,
        "rows": (),
    }
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        result["reason"] = "dataset_id_invalide"
        return result
    if not isinstance(dataset_sha256, str) or len(dataset_sha256) != 64:
        result["reason"] = "dataset_sha256_invalide"
        return result
    try:
        int(dataset_sha256, 16)
    except ValueError:
        result["reason"] = "dataset_sha256_invalide"
        return result
    if cutoff_ms is not None and (isinstance(cutoff_ms, bool) or not isinstance(cutoff_ms, int) or cutoff_ms <= 0):
        result["reason"] = "cutoff_invalide"
        return result
    copied = [dict(row) for row in list(rows or [])]
    if not copied:
        result["reason"] = "dataset_vide"
        return result
    episode_ids: list[str] = []
    seen: set[str] = set()
    for row in copied:
        if not isinstance(row, Mapping) or episode_id_field not in row:
            result["reason"] = "episode_id_manquant"
            return result
        episode_id = row[episode_id_field]
        key = str(episode_id) if episode_id is not None else ""
        if not key or key in seen:
            result["reason"] = "episode_id_duplique_ou_invalide"
            return result
        seen.add(key)
        episode_ids.append(key)
    content_sha = hashlib.sha256(_canonical_dataset_bytes(copied)).hexdigest()
    result["content_sha256"] = content_sha
    result["n_rows"] = len(copied)
    result["episode_ids"] = episode_ids
    result["rows"] = tuple(copied)
    if content_sha != dataset_sha256.lower():
        result["reason"] = "hash_dataset_inattendu"
        result["rows"] = ()
        return result
    result.update(status="PROVEN", verdict="DATASET_FIGE")
    return result


def evaluate_ablations_on_frozen_dataset(
    frozen_dataset: Mapping[str, Any],
    ablations: Sequence[Mapping[str, Any]],
    evaluate: Callable[[tuple[dict[str, Any], ...], Mapping[str, Any]], float],
) -> dict[str, Any]:
    """Evaluate every ablation on the exact frozen rows, never on a fresh sample."""
    result: dict[str, Any] = {
        "status": "UNMEASURABLE",
        "verdict": "INSUFFICIENT_DATA",
        "reason": None,
        "dataset_id": frozen_dataset.get("dataset_id") if isinstance(frozen_dataset, Mapping) else None,
        "dataset_sha256": frozen_dataset.get("dataset_sha256") if isinstance(frozen_dataset, Mapping) else None,
        "n_ablations": len(ablations or []),
        "results": [],
        "same_dataset": False,
        "paper_read_only": True,
        "real_execution": False,
    }
    if not isinstance(frozen_dataset, Mapping) or frozen_dataset.get("status") != "PROVEN":
        result["reason"] = "dataset_non_fige"
        return result
    rows = frozen_dataset.get("rows")
    if not isinstance(rows, tuple) or not rows:
        result["reason"] = "rows_figees_absentes"
        return result
    if not callable(evaluate) or not ablations:
        result["reason"] = "ablations_ou_evaluateur_absents"
        return result
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    invalid = False
    for ablation in ablations:
        ablation_id = ablation.get("ablation_id") if isinstance(ablation, Mapping) else None
        key = str(ablation_id) if ablation_id is not None else ""
        entry: dict[str, Any] = {
            "ablation_id": key or None,
            "dataset_sha256": frozen_dataset.get("dataset_sha256"),
            "n_rows": len(rows),
            "status": "UNMEASURABLE",
            "score": None,
            "reason": None,
        }
        if not key or key in seen:
            entry["reason"] = "ablation_id_duplique_ou_invalide"
            invalid = True
            results.append(entry)
            continue
        seen.add(key)
        try:
            score = evaluate(tuple(dict(row) for row in rows), ablation)
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
                raise ValueError("score_non_fini")
            entry.update(status="PROVEN", score=float(score), reason=None)
        except Exception as exc:  # callback is an explicit experiment boundary
            entry["reason"] = str(exc)[:160] or "evaluation_echouee"
            invalid = True
        results.append(entry)
    result["results"] = results
    result["same_dataset"] = not invalid and all(
        entry["dataset_sha256"] == frozen_dataset.get("dataset_sha256")
        and entry["n_rows"] == len(rows)
        for entry in results
    )
    if invalid or not result["same_dataset"]:
        result["reason"] = "ablation_non_mesurable"
        return result
    result.update(status="PROVEN", verdict="ABLATIONS_DATASET_FIGE")
    return result


def assess_parameter_neighbor_plateau(
    center_rows: Sequence[Mapping[str, Any]],
    neighbor_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    episode_id_field: str = "episode_id",
    value_field: str = "net_usd",
    fraction_floor: float = 0.7,
    confidence: float = 0.95,
    n_bootstrap: int = 1000,
    seed: int = 7,
) -> dict[str, Any]:
    """Measure a parameter plateau on the same episodes with paired CIs.

    The center and every neighbour must contain the exact same unique episode
    IDs. Paired bootstrap differences provide a confidence interval for each
    neighbour; the split is never changed and a missing episode invalidates the
    whole comparison. ``plateau`` is true only when at least the declared
    fraction of neighbours stays above ``fraction_floor`` times the center mean
    throughout its lower confidence bound.
    """
    result: dict[str, Any] = {
        "status": "UNMEASURABLE",
        "verdict": "INSUFFICIENT_DATA",
        "reason": None,
        "n_episodes": 0,
        "n_neighbors": len(neighbor_rows or {}),
        "center_mean": None,
        "neighbor_floor": None,
        "plateau_fraction": None,
        "plateau": False,
        "neighbors": {},
        "same_split": False,
        "real_execution": False,
    }
    if isinstance(fraction_floor, bool) or not isinstance(fraction_floor, (int, float)):
        result["reason"] = "fraction_floor_invalide"
        return result
    fraction_floor = float(fraction_floor)
    if not 0.0 < fraction_floor <= 1.0:
        result["reason"] = "fraction_floor_invalide"
        return result
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 < float(confidence) < 1.0:
        result["reason"] = "confidence_invalide"
        return result
    if isinstance(n_bootstrap, bool) or not isinstance(n_bootstrap, int) or n_bootstrap < 1:
        result["reason"] = "n_bootstrap_invalide"
        return result
    if not isinstance(seed, int) or isinstance(seed, bool) or not neighbor_rows:
        result["reason"] = "voisins_absents_ou_seed_invalide"
        return result

    def normalize(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, float], str | None]:
        values: dict[str, float] = {}
        for row in list(rows or []):
            if not isinstance(row, Mapping) or episode_id_field not in row or value_field not in row:
                return {}, "champ_manquant"
            episode = row[episode_id_field]
            value = row[value_field]
            key = str(episode) if episode is not None else ""
            if not key or key in values or isinstance(value, bool):
                return {}, "episode_duplique_ou_invalide"
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return {}, "valeur_invalide"
            if not math.isfinite(numeric):
                return {}, "valeur_non_finie"
            values[key] = numeric
        return values, None

    center, error = normalize(center_rows)
    if error or len(center) < 2:
        result["reason"] = error or "centre_insuffisant"
        return result
    center_mean = statistics.fmean(center.values())
    if center_mean <= 0.0:
        result["reason"] = "centre_non_positif"
        return result
    result["n_episodes"] = len(center)
    result["center_mean"] = center_mean
    floor = fraction_floor * center_mean
    result["neighbor_floor"] = floor
    lower_delta_floor = floor - center_mean
    assessments: dict[str, dict[str, Any]] = {}
    stable_count = 0

    def quantile(values: list[float], q: float) -> float:
        ordered = sorted(values)
        offset = (len(ordered) - 1) * q
        lower = math.floor(offset)
        upper = math.ceil(offset)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (offset - lower)

    center_ids = set(center)
    for index, (neighbor_id, rows) in enumerate(neighbor_rows.items()):
        neighbor, error = normalize(rows)
        if error or set(neighbor) != center_ids:
            result["reason"] = "splits_episode_incompatibles"
            return result
        deltas = [neighbor[key] - center[key] for key in center]
        rng = random.Random(seed + index)
        bootstrap = [statistics.fmean(rng.choice(deltas) for _ in deltas) for _ in range(n_bootstrap)]
        alpha = (1.0 - float(confidence)) / 2.0
        delta_mean = statistics.fmean(deltas)
        ci_low = quantile(bootstrap, alpha)
        ci_high = quantile(bootstrap, 1.0 - alpha)
        neighbor_mean = statistics.fmean(neighbor.values())
        meets = neighbor_mean >= floor and ci_low >= lower_delta_floor
        stable_count += int(meets)
        assessments[str(neighbor_id)] = {
            "neighbor_mean": neighbor_mean,
            "delta_mean": delta_mean,
            "delta_ci_low": ci_low,
            "delta_ci_high": ci_high,
            "meets_plateau": meets,
            "n_episodes": len(neighbor),
        }
    plateau_fraction = stable_count / len(assessments)
    result.update(
        status="PROVEN",
        verdict="PLATEAU_MEASURED",
        plateau_fraction=plateau_fraction,
        plateau=plateau_fraction >= fraction_floor,
        neighbors=assessments,
        same_split=True,
    )
    return result
