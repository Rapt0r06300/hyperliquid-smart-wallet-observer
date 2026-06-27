"""V13 — Training orchestrator: ledger dataset → train → evaluate (OOS) → persist (gated).

Builds the labeled set (ml.dataset), trains the calibrated logistic (ml.model), evaluates
out-of-sample, and persists the model ONLY if it beats the base-rate baseline
(ready_for_promotion discipline). Honest: refuses on too few samples; never fabricates.
"""

from __future__ import annotations

from hl_observer.ml.dataset import build_training_set, to_matrix
from hl_observer.ml.model import evaluate, train_logistic, train_test_split


def train_from_dataset(
    rows, outcomes, *, context: str | None = "LIVE", out_path: str | None = None,
    test_frac: float = 0.3, min_samples: int = 40, seed: int = 7,
) -> dict:
    ds = build_training_set(rows, outcomes, context=context)
    if ds["n"] < min_samples or ds["n_win"] == 0 or ds["n_loss"] == 0:
        return {"trained": False, "reason": "insufficient_or_single_class",
                "n": ds["n"], "n_win": ds["n_win"], "n_loss": ds["n_loss"], "saved": False}
    names = ds["feature_names"]
    X, y = to_matrix(ds["samples"], names)
    Xtr, ytr, Xte, yte = train_test_split(X, y, test_frac=test_frac, seed=seed)
    model = train_logistic(Xtr.tolist(), ytr.tolist(), names, min_samples=min_samples, seed=seed)
    ev = evaluate(model, Xte.tolist(), yte.tolist(), names) if model.trained else {"beats_baseline": False, "empty": True}
    saved = False
    if out_path and model.trained and ev.get("beats_baseline"):
        model.save(out_path)             # promote only when it beats the base rate (OOS)
        saved = True
    return {
        "trained": bool(model.trained), "saved": saved, "out_path": out_path,
        "n": ds["n"], "n_win": ds["n_win"], "n_loss": ds["n_loss"],
        "evaluation": ev, "feature_names": names,
        "ready_for_promotion": bool(model.trained and ev.get("beats_baseline")),
    }


__all__ = ["train_from_dataset"]
