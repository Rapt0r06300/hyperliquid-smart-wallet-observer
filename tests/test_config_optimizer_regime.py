"""P2: optimiseur de configs OOS (réutilise gardes) + edge régime/volume."""

from __future__ import annotations

from hl_observer.edge.regime_volume import RANGING, TRENDING, adjusted_edge_bps, regime_multiplier, volume_multiplier
from hl_observer.optimization.config_optimizer import optimize_configs


def _samples(n):
    return [{"ts_ms": i * 1000, "v": i} for i in range(n)]


def test_optimizer_keeps_robust_config_rejects_overfit():
    samples = _samples(100)
    # config A: robuste (PF ~1.5 partout). config B: overfit (train fort, test faible).
    def evaluate(cfg, subset):
        if cfg["name"] == "robust":
            return 1.5
        # overfit: dépend de la taille (train plus grand → PF gonflé, test → sous 1)
        return 2.5 if len(subset) > 50 else 0.7
    res = optimize_configs([{"name": "robust"}, {"name": "overfit"}], samples, evaluate)
    names_accepted = {r["config"]["name"] for r in res["ranked_accepted"]}
    assert "robust" in names_accepted
    assert "overfit" not in names_accepted     # rejeté: s'effondre hors échantillon
    assert res["best"]["config"]["name"] == "robust"


def test_optimizer_handles_eval_failure_gracefully():
    def boom(cfg, subset):
        raise ValueError("bad")
    res = optimize_configs([{"name": "x"}], _samples(40), boom)
    assert res["n_accepted"] == 0
    assert res["all"][0]["reason"] == "EVAL_FAILED"


def test_regime_multiplier_suppresses_ranging():
    assert regime_multiplier(RANGING) == 0.0
    assert regime_multiplier(TRENDING) == 1.2
    assert regime_multiplier("whatever") == 1.0


def test_volume_multiplier_bands():
    assert volume_multiplier(1.5) == 1.2     # volume haut confirme
    assert volume_multiplier(-1.5) == 0.5    # volume bas fragilise
    assert volume_multiplier(0.0) == 1.0


def test_adjusted_edge_combines_and_suppresses():
    trending = adjusted_edge_bps(40.0, regime="TRENDING", volume_zscore=1.5)
    assert trending["adjusted_edge_bps"] == round(40.0 * 1.2 * 1.2, 4)
    ranging = adjusted_edge_bps(40.0, regime="RANGING", volume_zscore=2.0)
    assert ranging["adjusted_edge_bps"] == 0.0 and ranging["suppressed"] is True
