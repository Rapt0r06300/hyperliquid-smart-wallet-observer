"""Tests du harnais d'expérience + gate 'edge réel'."""
from __future__ import annotations

import random

from hl_observer.backtesting.experiment_harness import promotion_gate, run_experiment


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
