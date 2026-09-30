"""V13 — Training-set builder: join decisions ↔ realized paper PnL (labels).

Foundation of the local AI model (#147). Builds, from the REAL ledger, a dataset of
(features known at decision time) → (label = profitable?). Hard rules:
  * **No-lookahead**: an outcome must be strictly AFTER its decision; otherwise the row is
    dropped (counted), never used. Features must be decision-time only (caller's responsibility).
  * **Honest labels**: a decision with NO realized outcome (still open) is SKIPPED, never
    labeled. No fabrication.
  * **Context isolation**: LIVE / BACKTEST / REPLAY / TEST_FIXTURE never mixed (filterable).
Pure / read-only. No order, no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class FeatureRow:
    decision_id: str
    ts_ms: int
    features: dict           # decision-time features only (numeric)
    context: str = "LIVE"
    side: str = ""


@dataclass(frozen=True, slots=True)
class Outcome:
    decision_id: str
    close_ts_ms: int
    realized_net_pnl_usdc: float


def build_training_set(
    rows: list[FeatureRow],
    outcomes: list[Outcome],
    *,
    context: str | None = None,
    min_decision_to_close_ms: int = 0,
) -> dict:
    """Join rows↔outcomes with a strict no-lookahead guard; emit labeled samples."""
    by_id: dict[str, Outcome] = {}
    for o in outcomes:
        # keep the EARLIEST valid close per decision (first realized outcome)
        prev = by_id.get(o.decision_id)
        if prev is None or int(o.close_ts_ms) < int(prev.close_ts_ms):
            by_id[o.decision_id] = o

    samples: list[dict] = []
    feature_names: set[str] = set()
    skipped_no_outcome = 0
    skipped_lookahead = 0
    skipped_context = 0

    for r in rows:
        if context is not None and r.context != context:
            skipped_context += 1
            continue
        o = by_id.get(r.decision_id)
        if o is None:
            skipped_no_outcome += 1            # still open / never resolved -> no label
            continue
        if int(o.close_ts_ms) <= int(r.ts_ms) + int(min_decision_to_close_ms):
            skipped_lookahead += 1             # outcome not strictly after decision -> drop
            continue
        label = 1 if float(o.realized_net_pnl_usdc) > 0.0 else 0
        feats = {k: float(v) for k, v in (r.features or {}).items()}
        feature_names.update(feats)
        samples.append({
            "decision_id": r.decision_id,
            "ts_ms": int(r.ts_ms),
            "context": r.context,
            "features": feats,
            "label": label,
            "net_pnl_usdc": round(float(o.realized_net_pnl_usdc), 6),
        })

    n_win = sum(1 for s in samples if s["label"] == 1)
    return {
        "samples": samples,
        "n": len(samples),
        "n_win": n_win,
        "n_loss": len(samples) - n_win,
        "feature_names": sorted(feature_names),
        "skipped_no_outcome": skipped_no_outcome,
        "skipped_lookahead": skipped_lookahead,
        "skipped_context": skipped_context,
        "empty": not samples,
    }


def to_matrix(samples: list[dict], feature_names: list[str]) -> tuple[list[list[float]], list[int]]:
    """Ordered numeric design matrix X and label vector y for the model (#147)."""
    X = [[float(s["features"].get(name, 0.0)) for name in feature_names] for s in samples]
    y = [int(s["label"]) for s in samples]
    return X, y


__all__ = ["FeatureRow", "Outcome", "build_training_set", "to_matrix"]
