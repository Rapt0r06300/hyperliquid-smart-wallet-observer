import numpy as np
from hl_observer.ml.model import LogisticModel, brier_score, evaluate, train_logistic, train_test_split


def _make_data(n=400, seed=3):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 3))
    # true rule: profitable when edge(0) high and bias(1) positive; feature 2 is noise
    logit = 1.6 * X[:, 0] + 1.1 * X[:, 1] - 0.4
    p = 1.0 / (1.0 + np.exp(-logit))
    y = (rng.random(n) < p).astype(int)
    return X.tolist(), y.tolist()


def test_model_learns_and_beats_baseline_out_of_sample():
    X, y = _make_data()
    names = ["edge", "bias", "noise"]
    Xtr, ytr, Xte, yte = train_test_split(X, y, test_frac=0.3, seed=11)
    m = train_logistic(Xtr.tolist(), ytr.tolist(), names, seed=11)
    assert m.trained is True
    ev = evaluate(m, Xte.tolist(), yte.tolist(), names)
    assert ev["beats_baseline"] is True and ev["brier_advantage"] > 0
    assert ev["accuracy"] >= 0.6


def test_probabilities_are_bounded_and_monotone_in_edge():
    X, y = _make_data()
    names = ["edge", "bias", "noise"]
    m = train_logistic(X, y, names, seed=5)
    lo = m.predict_proba_one({"edge": -3, "bias": 0, "noise": 0})
    hi = m.predict_proba_one({"edge": 3, "bias": 0, "noise": 0})
    assert 0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0
    assert hi > lo                      # higher edge -> higher P(profit)


def test_refuses_on_too_few_samples_or_one_class():
    m = train_logistic([[1, 2]], [1], ["a", "b"])
    assert m.trained is False
    m2 = train_logistic([[1, 2]] * 60, [1] * 60, ["a", "b"])   # single class
    assert m2.trained is False
    # untrained model still returns a usable neutral-ish probability, never crashes
    assert 0.0 <= m.predict_proba_one({"a": 1, "b": 2}) <= 1.0


def test_serialization_roundtrip():
    X, y = _make_data()
    names = ["edge", "bias", "noise"]
    m = train_logistic(X, y, names, seed=2)
    m2 = LogisticModel.from_dict(m.to_dict())
    f = {"edge": 1.0, "bias": 0.5, "noise": -1.0}
    assert abs(m.predict_proba_one(f) - m2.predict_proba_one(f)) < 1e-9
