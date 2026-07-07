"""Concentration guard for copy clusters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ConcentrationRiskResult:
    blocked: bool
    top_wallet_share: float
    reason: str


def detect_concentration_risk(wallet_notionals: Iterable[float], *, max_top_share: float = 0.65) -> ConcentrationRiskResult:
    notionals = [max(float(value), 0.0) for value in wallet_notionals]
    total = sum(notionals)
    share = max(notionals) / total if total > 0 else 0.0
    blocked = total <= 0 or share > max_top_share
    return ConcentrationRiskResult(blocked=blocked, top_wallet_share=round(share, 8), reason="CONCENTRATION_TOO_HIGH" if blocked else "OK")


__all__ = ["ConcentrationRiskResult", "detect_concentration_risk"]
