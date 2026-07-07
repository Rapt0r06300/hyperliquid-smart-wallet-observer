"""Evidence-based wallet labels (S5 — V9, awesome-pm A07).

A label is only attached when it is backed by enough evidence (observed
fills/positions). Without evidence a wallet stays UNVERIFIED — we never label
on a hunch.

Labels: SMART, WHALE, FRESH, SUSPICIOUS, UNVERIFIED.

SAFETY: read-only classification of public on-chain behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.scoring.smart_money_filter import (
    SmartMoneyThresholds,
    WalletStats,
    is_smart_money,
)


@dataclass(frozen=True, slots=True)
class LabelConfig:
    min_evidence: int = 20
    whale_notional_usdc: float = 250_000.0
    fresh_max_fills: int = 10
    suspicious_one_big_win_share: float = 0.60


@dataclass(frozen=True, slots=True)
class WalletLabelResult:
    labels: tuple[str, ...] = field(default_factory=tuple)
    evidence_count: int = 0
    verified: bool = False


def assign_labels(
    stats: WalletStats,
    *,
    evidence_count: int,
    largest_notional_usdc: float | None = None,
    fill_count: int | None = None,
    config: LabelConfig | None = None,
    thresholds: SmartMoneyThresholds | None = None,
) -> WalletLabelResult:
    cfg = config or LabelConfig()

    if evidence_count < cfg.min_evidence:
        return WalletLabelResult(("UNVERIFIED",), evidence_count, verified=False)

    labels: list[str] = []

    if is_smart_money(stats, thresholds).is_smart_money:
        labels.append("SMART")

    if largest_notional_usdc is not None and largest_notional_usdc >= cfg.whale_notional_usdc:
        labels.append("WHALE")

    if fill_count is not None and fill_count <= cfg.fresh_max_fills:
        labels.append("FRESH")

    if (
        stats.one_big_win_share is not None
        and stats.one_big_win_share >= cfg.suspicious_one_big_win_share
    ):
        labels.append("SUSPICIOUS")

    if not labels:
        labels.append("UNVERIFIED")

    return WalletLabelResult(tuple(labels), evidence_count, verified=True)
