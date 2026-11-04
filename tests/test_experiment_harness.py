"""Tests du harnais d'expérience + gate 'edge réel'."""
from __future__ import annotations

import random
import hashlib
import json

from hl_observer.backtesting.experiment_harness import (
    assess_parameter_neighbor_plateau,
    evaluate_ablations_on_frozen_dataset,
    freeze_ablation_dataset,
    promotion_gate,
    run_experiment,
)


def test_run_experiment_beats_random_on_separable_signal():
    # feature = valeur ; net = valeur ; le modèle doit apprendre à choisir les valeurs positives
    x_train = [[float(v)] for v in range(-50, 51)]
    y_train = [1 if v > 0 else 0 for v in range(-50, 51)]
    vals = list(range(-40, 41))
    random.Random(0).shuffle(vals)
    x_test = [[float(v)] for v in vals]
    nets_test = [float(v) for v in vals]
    r = run_experiment(x_train, y_train, x_test, nets_test, epochs=150)
    assert r["model_net"] > 0
    assert r["beats_random"] is True


def test_promotion_gate_logic():
    ok = promotion_gate(100.0, 50, beats_random=True, mc_p5_value=10.0)
    assert ok["promote"] is True and ok["reasons"] == []
    bad = promotion_gate(-5.0, 5, beats_random=False, mc_p5_value=-1.0)
    assert bad["promote"] is False
    assert set(bad["reasons"]) == {
        "NET_OOS_NOT_POSITIVE", "DOES_NOT_BEAT_RANDOM", "MC_P5_NOT_POSITIVE", "TOO_FEW_TRADES"}


def test_toutes_les_ablations_reutilisent_le_dataset_fige():
    rows = [{"episode_id": "e1", "net": 1.0}, {"episode_id": "e2", "net": 2.0}]
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    frozen = freeze_ablation_dataset(rows, dataset_id="safe-1", dataset_sha256=hashlib.sha256(raw).hexdigest())
    seen = []
    result = evaluate_ablations_on_frozen_dataset(
        frozen,
        [{"ablation_id": "baseline"}, {"ablation_id": "remove_signal"}],
        lambda dataset, ablation: seen.append((ablation["ablation_id"], dataset)) or sum(row["net"] for row in dataset),
    )
    assert result["status"] == "PROVEN"
    assert result["same_dataset"] is True
    assert result["n_ablations"] == 2
    assert seen[0][1] == seen[1][1] == tuple(rows)


def test_dataset_non_fige_ou_ablation_invalide_reste_non_mesurable():
    frozen = freeze_ablation_dataset(
        [{"episode_id": "e1", "net": 1.0}],
        dataset_id="safe-1",
        dataset_sha256="0" * 64,
    )
    result = evaluate_ablations_on_frozen_dataset(
        frozen, [{"ablation_id": "a"}], lambda _rows, _ablation: 1.0,
    )
    assert frozen["status"] == "UNMEASURABLE"
    assert result["status"] == "UNMEASURABLE"
