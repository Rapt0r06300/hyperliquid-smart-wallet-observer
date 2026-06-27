"""V13 #151 — Data-driven threshold optimisation on the REAL ledger (anti-overfit).

Given labeled samples (features + realized net pnl), search the threshold grid
(min edge / min liquidity / max signal age) that would have maximised net PnL — but pick
on a TRAIN split and report performance on a held-out TEST split (out-of-sample), with an
anti-overfit guard (must stay positive on BOTH and trade enough). Honest caveats included.
Pure / read-only: suggests thresholds, never trades.
"""

from __future__ import annotations

from itertools import product


def evaluate_thresholds(samples: list[dict], *, min_edge_bps: float,
                        min_liquidity: float, max_age_ms: float) -> dict:
    taken = []
    for s in samples:
        f = s.get("features", {})
        if (float(f.get("net_edge_bps", 0.0)) >= min_edge_bps
                and float(f.get("liquidity_score", 0.0)) >= min_liquidity
                and float(f.get("signal_age_ms", 0.0)) <= max_age_ms):
            taken.append(s)
    n = len(taken)
    wins = sum(1 for s in taken if float(s.get("net_pnl_usdc", 0.0)) > 0.0)
    net = sum(float(s.get("net_pnl_usdc", 0.0)) for s in taken)
    return {"n_taken": n, "win_rate": round(wins / n, 4) if n else 0.0,
            "net_pnl_usdc": round(net, 6)}


def optimize_thresholds(
    samples: list[dict], *,
    edge_grid=(10.0, 15.0, 20.0, 25.0, 30.0),
    liq_grid=(0.2, 0.3, 0.4, 0.5),
    age_grid=(8000.0, 12000.0, 15000.0, 30000.0),
    test_frac: float = 0.3, min_taken: int = 10,
) -> dict:
    """Time-ordered split (no shuffle => no lookahead). Pick best net PnL on TRAIN, report TEST."""
    seq = sorted(samples, key=lambda s: int(s.get("ts_ms", 0)))
    if len(seq) < max(2 * min_taken, 20):
        return {"ok": False, "reason": "not_enough_samples", "n": len(seq)}
    cut = int(len(seq) * (1.0 - test_frac))
    train, test = seq[:cut], seq[cut:]

    best = None
    for e, l, a in product(edge_grid, liq_grid, age_grid):
        tr = evaluate_thresholds(train, min_edge_bps=e, min_liquidity=l, max_age_ms=a)
        if tr["n_taken"] < min_taken:
            continue
        if best is None or tr["net_pnl_usdc"] > best["train"]["net_pnl_usdc"]:
            best = {"config": {"min_edge_bps": e, "min_liquidity": l, "max_age_ms": a}, "train": tr}
    if best is None:
        return {"ok": False, "reason": "no_config_traded_enough", "n": len(seq)}

    te = evaluate_thresholds(test, **{
        "min_edge_bps": best["config"]["min_edge_bps"],
        "min_liquidity": best["config"]["min_liquidity"],
        "max_age_ms": best["config"]["max_age_ms"],
    })
    oos_consistent = best["train"]["net_pnl_usdc"] > 0 and te["net_pnl_usdc"] > 0 and te["n_taken"] >= min_taken
    return {
        "ok": True, "best_config": best["config"], "train": best["train"], "test": te,
        "oos_consistent": bool(oos_consistent),
        "caveat": ("Seuils choisis sur le passé (train) et validés sur des données jamais vues "
                   "(test). oos_consistent=False => possible sur-apprentissage, ne pas appliquer."),
    }


__all__ = ["evaluate_thresholds", "optimize_thresholds"]
