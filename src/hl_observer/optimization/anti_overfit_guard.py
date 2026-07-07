"""B4 — Garde anti-surapprentissage : le profit factor test ne doit pas s'effondrer vs train."""

from __future__ import annotations


def degradation_ratio(train_pf: float, test_pf: float) -> float:
    """test/train. ~1 = généralise bien ; <<1 = sur-appris."""
    if train_pf <= 0:
        return 0.0
    return float(test_pf) / float(train_pf)


def is_overfit(train_pf: float, test_pf: float, *, min_ratio: float = 0.5) -> bool:
    if train_pf <= 0:
        return False
    return degradation_ratio(train_pf, test_pf) < float(min_ratio)


def accept_config(train_pf: float, test_pf: float, *, min_pf: float = 1.0, min_ratio: float = 0.5) -> bool:
    return (train_pf >= min_pf and test_pf >= min_pf
            and not is_overfit(train_pf, test_pf, min_ratio=min_ratio))


__all__ = ["degradation_ratio", "is_overfit", "accept_config"]
