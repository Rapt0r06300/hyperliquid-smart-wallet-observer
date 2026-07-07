"""V13 #164 — Calibration rigoureuse EMOS/CRPS + reliability diagram + promotion gate.

Pour le binaire, le CRPS se réduit au score de Brier. EMOS = recalibrer les probas (a*logit+b)
pour coller à la réalité. On NE PROMEUT la version calibrée que si elle bat la version brute en
out-of-sample (ready_for_promotion). Pur python (pas de dépendance) ; honnête.
"""

from __future__ import annotations

from math import exp, log

from hl_observer.calibration.confidence_buckets import bucketize


def crps_binary(predictions: list[tuple[float, float | int]]) -> float | None:
    if not predictions:
        return None
    return sum((min(1.0, max(0.0, float(p))) - (1.0 if y else 0.0)) ** 2 for p, y in predictions) / len(predictions)


def reliability_diagram(predictions: list[tuple[float, float | int]], *, n_bins: int = 10) -> list[dict]:
    buckets = bucketize(predictions, n_buckets=n_bins)
    return [{"from": round(b.low, 2), "to": round(b.high, 2), "count": b.count,
             "predicted": None if b.mean_confidence is None else round(b.mean_confidence, 4),
             "observed": None if b.win_rate is None else round(b.win_rate, 4)}
            for b in buckets if b.count > 0]


def _logit(p: float) -> float:
    p = min(1 - 1e-6, max(1e-6, float(p)))
    return log(p / (1 - p))


def emos_fit(raw_probs: list[float], outcomes: list[float | int], *, epochs: int = 400, lr: float = 0.1) -> tuple[float, float]:
    """Fit a,b for calibrated p = sigmoid(a*logit(raw)+b). Pure-python GD."""
    z = [_logit(p) for p in raw_probs]
    y = [1.0 if o else 0.0 for o in outcomes]
    n = len(y)
    a, b = 1.0, 0.0
    if n < 5:
        return a, b
    for _ in range(epochs):
        ga = gb = 0.0
        for zi, yi in zip(z, y):
            pc = 1.0 / (1.0 + exp(-(a * zi + b)))
            e = pc - yi
            ga += e * zi
            gb += e
        a -= lr * ga / n
        b -= lr * gb / n
    return a, b


def emos_apply(raw_prob: float, a: float, b: float) -> float:
    return 1.0 / (1.0 + exp(-(a * _logit(raw_prob) + b)))


def promotion_gate(raw_preds: list[tuple[float, float | int]],
                   cal_preds: list[tuple[float, float | int]]) -> dict:
    """Promeut la calibration seulement si elle bat le brut (Brier) en OOS."""
    rb = crps_binary(raw_preds)
    cb = crps_binary(cal_preds)
    ready = rb is not None and cb is not None and cb < rb
    return {"raw_brier": None if rb is None else round(rb, 6),
            "calibrated_brier": None if cb is None else round(cb, 6),
            "improved": ready, "ready_for_promotion": ready}


__all__ = ["crps_binary", "reliability_diagram", "emos_fit", "emos_apply", "promotion_gate"]
