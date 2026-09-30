"""B7 — Sélecteur de meilleure config par profit factor test, sous garde OOS + anti-overfit."""

from __future__ import annotations

from hl_observer.optimization.anti_overfit_guard import accept_config


def select_best(results: list[dict], *, min_pf: float = 1.0, min_ratio: float = 0.5) -> dict | None:
    """results: [{config, train_pf, test_pf, test_n}]. Retourne le meilleur test_pf validé, sinon None."""
    valid = [
        r for r in results
        if accept_config(float(r.get("train_pf", 0.0)), float(r.get("test_pf", 0.0)),
                         min_pf=min_pf, min_ratio=min_ratio)
    ]
    if not valid:
        return None
    return max(valid, key=lambda r: (float(r.get("test_pf", 0.0)), float(r.get("test_pnl", 0.0))))


__all__ = ["select_best"]
