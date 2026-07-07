"""B4 — Garde out-of-sample : split temporel (pas de lookahead) + cohérence train/test."""

from __future__ import annotations


def oos_split(samples: list[dict], *, test_frac: float = 0.3, ts_key: str = "ts_ms"):
    """Split temporel ordonné (aucun shuffle => aucun lookahead)."""
    seq = sorted(samples, key=lambda s: int(s.get(ts_key, 0)))
    cut = int(len(seq) * (1.0 - float(test_frac)))
    return seq[:cut], seq[cut:]


def oos_consistent(train_pf: float, test_pf: float, test_n: int, *, min_pf: float = 1.0, min_n: int = 10) -> bool:
    """Un config n'est fiable que s'il est positif sur train ET test, avec assez de trades."""
    return train_pf >= min_pf and test_pf >= min_pf and int(test_n) >= min_n


__all__ = ["oos_split", "oos_consistent"]
