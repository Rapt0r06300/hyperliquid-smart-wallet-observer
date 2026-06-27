import numpy as np
from hl_observer.ml.features import canonical_feature_names, canonical_features
from hl_observer.ml.inference import apply_model_promotion, model_accepts
from hl_observer.ml.dataset import FeatureRow, Outcome
from hl_observer.ml.train import train_from_dataset


def test_canonical_features_stable():
    f = canonical_features(net_edge_bps=20, liquidity_score=0.5)
    assert set(f) == set(canonical_feature_names()) and f["net_edge_bps"] == 20.0


def test_model_promotion_only_tightens():
    A = "EDGE_OK_FOR_LOCAL_SIMULATION"
    assert apply_model_promotion(score_reason=A, model_accept=False, authoritative=False) == A   # shadow no-op
    assert apply_model_promotion(score_reason=A, model_accept=False, authoritative=True) == "REJECT_MODEL_LOW_P"
    assert apply_model_promotion(score_reason=A, model_accept=True, authoritative=True) == A
    assert apply_model_promotion(score_reason="REJECT_TOO_LATE", model_accept=True, authoritative=True) == "REJECT_TOO_LATE"


def test_model_accepts_none_when_no_model():
    assert model_accepts(None) is None          # no model -> no opinion (don't block)
    assert model_accepts(0.8, min_p=0.5) is True
    assert model_accepts(0.2, min_p=0.5) is False


def test_train_from_dataset_and_persist(tmp_path):
    rng = np.random.default_rng(1)
    rows, outcomes = [], []
    for i in range(300):
        edge = float(rng.normal())
        bias = float(rng.normal())
        ts = 1000 + i
        # profitable when edge+bias high
        win = (1.5 * edge + 1.0 * bias - 0.3 + rng.normal() * 0.5) > 0
        rows.append(FeatureRow(decision_id=str(i), ts_ms=ts,
                               features=canonical_features(net_edge_bps=edge, bias_bps=bias)))
        outcomes.append(Outcome(str(i), ts + 100, 5.0 if win else -5.0))
    out = tmp_path / "model.json"
    res = train_from_dataset(rows, outcomes, out_path=str(out))
    assert res["trained"] is True and res["evaluation"]["beats_baseline"] is True
    assert res["saved"] is True and out.exists()


def test_train_refuses_insufficient():
    res = train_from_dataset([], [], out_path=None)
    assert res["trained"] is False and res["saved"] is False


def test_shadow_exposes_model_p_profit_when_model_present(tmp_path, monkeypatch):
    import numpy as np
    from hl_observer.ml.dataset import FeatureRow, Outcome
    from hl_observer.ml.train import train_from_dataset
    from hl_observer.signals.shadow_wiring import compute_shadow_signals
    import hl_observer.ml.inference as inf
    rng = np.random.default_rng(2)
    rows, outs = [], []
    for i in range(300):
        edge = float(rng.normal()); bias = float(rng.normal()); ts = 1000 + i
        win = (1.5 * edge + bias + rng.normal() * 0.5) > 0
        rows.append(FeatureRow(str(i), ts, canonical_features(net_edge_bps=edge, bias_bps=bias)))
        outs.append(Outcome(str(i), ts + 100, 5.0 if win else -5.0))
    mp = tmp_path / "m.json"
    res = train_from_dataset(rows, outs, out_path=str(mp))
    assert res["saved"] is True
    monkeypatch.setenv("HYPERSMART_V13_MODEL_PATH", str(mp))
    inf._CACHE.update({"path": None, "mtime": None, "model": None})  # bust cache
    s = compute_shadow_signals(action_type="OPEN_LONG", coin="BTC", side="LONG", age_ms=2000,
                               consensus_wallets=2, leader_score=70, leader_notional_usdc=5000,
                               net_edge_bps=25, liquidity_score=0.5)
    assert s["shadow_model_p_profit"] is not None and 0.0 <= s["shadow_model_p_profit"] <= 1.0
    assert s["shadow_model_accept"] in (True, False)
