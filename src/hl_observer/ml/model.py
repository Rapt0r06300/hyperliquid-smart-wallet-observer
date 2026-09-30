"""V13 — Local trade-selection model (FREE: training=numpy, inference=pure-python).

Predicts P(profitable paper trade | decision-time features). Trained on the real ledger
dataset (ml.dataset). Design choices for safety + zero cost:
  * Training uses numpy (offline). INFERENCE is pure-python (math.exp) so the live engine
    needs NO numpy and no new dependency.
  * Platt calibration (sigmoid(a*z+b)) corrects over/under-confidence.
  * Honest: refuses to train on too few samples or a single class (trained=False); never
    fabricates a probability. Serialises to JSON (no pickle).
Read-only / paper-only: the model SCORES, it never places an order.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass(frozen=True, slots=True)
class LogisticModel:
    feature_names: tuple[str, ...]
    weights: tuple[float, ...]
    bias: float
    mean: tuple[float, ...]
    std: tuple[float, ...]
    platt_a: float = 1.0
    platt_b: float = 0.0
    n_train: int = 0
    trained: bool = False

    def _logit(self, features: dict) -> float:
        z = self.bias
        for name, w, mu, sd in zip(self.feature_names, self.weights, self.mean, self.std):
            x = float(features.get(name, mu))          # missing feature -> neutral (its mean)
            z += w * ((x - mu) / (sd if sd > 1e-12 else 1.0))
        return z

    def predict_proba_one(self, features: dict) -> float:
        """Calibrated P(profit) in [0,1]. Pure-python (no numpy needed at inference)."""
        z = self._logit(features)
        return _sigmoid(self.platt_a * z + self.platt_b)

    def to_dict(self) -> dict:
        return {
            "feature_names": list(self.feature_names), "weights": list(self.weights),
            "bias": self.bias, "mean": list(self.mean), "std": list(self.std),
            "platt_a": self.platt_a, "platt_b": self.platt_b,
            "n_train": self.n_train, "trained": self.trained, "kind": "logistic_v13",
        }

    @staticmethod
    def from_dict(d: dict) -> "LogisticModel":
        return LogisticModel(
            feature_names=tuple(d["feature_names"]), weights=tuple(d["weights"]),
            bias=float(d["bias"]), mean=tuple(d["mean"]), std=tuple(d["std"]),
            platt_a=float(d.get("platt_a", 1.0)), platt_b=float(d.get("platt_b", 0.0)),
            n_train=int(d.get("n_train", 0)), trained=bool(d.get("trained", False)),
        )

    def save(self, path) -> None:
        from pathlib import Path
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @staticmethod
    def load(path) -> "LogisticModel | None":
        from pathlib import Path
        p = Path(path)
        if not p.exists():
            return None
        try:
            return LogisticModel.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return None


def brier_score(probs: list[float], labels: list[int]) -> float:
    if not probs:
        return 0.0
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(probs)


def train_test_split(X, y, *, test_frac: float = 0.3, seed: int = 7):
    import numpy as np
    n = len(y)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n)
    cut = int(n * (1.0 - test_frac))
    tr, te = idx[:cut], idx[cut:]
    Xa = np.asarray(X, dtype=float)
    ya = np.asarray(y, dtype=float)
    return Xa[tr], ya[tr], Xa[te], ya[te]


def train_logistic(
    X, y, feature_names: list[str], *,
    l2: float = 1.0, lr: float = 0.1, epochs: int = 600, calibrate: bool = True,
    min_samples: int = 40, seed: int = 7,
) -> LogisticModel:
    """Train a calibrated logistic model. Refuses (trained=False) on too few samples/one class."""
    import numpy as np
    Xa = np.asarray(X, dtype=float)
    ya = np.asarray(y, dtype=float)
    n, d = (Xa.shape if Xa.ndim == 2 else (len(ya), 0))
    names = tuple(feature_names)
    if n < min_samples or d == 0 or len(set(ya.tolist())) < 2:
        # honest refusal: not enough signal to learn
        return LogisticModel(names, tuple([0.0] * d), 0.0, tuple([0.0] * d),
                             tuple([1.0] * d), 1.0, 0.0, int(n), False)

    mean = Xa.mean(axis=0)
    std = Xa.std(axis=0)
    std = np.where(std < 1e-12, 1.0, std)
    Xs = (Xa - mean) / std

    w = np.zeros(d)
    b = 0.0
    for _ in range(int(epochs)):
        z = Xs @ w + b
        p = 1.0 / (1.0 + np.exp(-z))
        err = p - ya
        gw = Xs.T @ err / n + l2 / n * w
        gb = float(err.mean())
        w -= lr * gw
        b -= lr * gb

    # Platt calibration: fit sigmoid(a*z + b2) on the model logits vs labels
    platt_a, platt_b = 1.0, 0.0
    if calibrate:
        z = Xs @ w + b
        a, b2 = 1.0, 0.0
        for _ in range(300):
            pc = 1.0 / (1.0 + np.exp(-(a * z + b2)))
            e = pc - ya
            ga = float((e * z).mean())
            gb2 = float(e.mean())
            a -= 0.1 * ga
            b2 -= 0.1 * gb2
        platt_a, platt_b = float(a), float(b2)

    return LogisticModel(
        feature_names=names, weights=tuple(float(v) for v in w), bias=float(b),
        mean=tuple(float(v) for v in mean), std=tuple(float(v) for v in std),
        platt_a=platt_a, platt_b=platt_b, n_train=int(n), trained=True,
    )


def evaluate(model: LogisticModel, X_test, y_test, feature_names: list[str]) -> dict:
    """Out-of-sample Brier vs base-rate baseline + accuracy. Honest empty if no test rows."""
    yt = [int(v) for v in y_test]
    if not yt:
        return {"n": 0, "brier": None, "baseline_brier": None, "brier_advantage": None,
                "accuracy": None, "empty": True}
    probs = []
    for row in X_test:
        feats = {name: float(row[i]) for i, name in enumerate(feature_names)}
        probs.append(model.predict_proba_one(feats))
    base_rate = sum(yt) / len(yt)
    brier = brier_score(probs, yt)
    baseline = brier_score([base_rate] * len(yt), yt)
    acc = sum(1 for p, y in zip(probs, yt) if (1 if p >= 0.5 else 0) == y) / len(yt)
    return {
        "n": len(yt), "brier": round(brier, 6), "baseline_brier": round(baseline, 6),
        "brier_advantage": round(baseline - brier, 6),   # >0 = beats base rate
        "accuracy": round(acc, 4), "beats_baseline": brier < baseline, "empty": False,
    }


__all__ = ["LogisticModel", "brier_score", "train_test_split", "train_logistic", "evaluate"]
