"""Research-only wallet pattern detector.

Patterns are diagnostic evidence for scoring and dashboard explanation. They do
not produce orders and they never claim future profit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from hashlib import sha256

from hl_observer.scoring.wallet_score_v2 import WalletPerformanceSample


class PatternType(StrEnum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ONE_BIG_WIN = "ONE_BIG_WIN"
    PNL_CONCENTRATED = "PNL_CONCENTRATED"
    COIN_SPECIALIST = "COIN_SPECIALIST"
    CUTS_LOSSES = "CUTS_LOSSES"
    LETS_WINNERS_RUN = "LETS_WINNERS_RUN"


@dataclass(frozen=True, slots=True)
class PatternResult:
    pattern_id: str
    wallet: str
    pattern_type: PatternType
    confidence: float
    evidence_count: int
    pnl_association: float
    risk_flags: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    research_only_message: str = "Research only: historical pattern is not future profit."


def detect_wallet_patterns(
    wallet: str,
    samples: list[WalletPerformanceSample],
    *,
    min_samples: int = 12,
) -> list[PatternResult]:
    clean = [s for s in samples if s.wallet.lower() == wallet.lower()]
    clean.sort(key=lambda s: s.timestamp_ms)
    if len(clean) < min_samples:
        return [
            _pattern(
                wallet,
                PatternType.INSUFFICIENT_DATA,
                confidence=1.0,
                evidence_count=len(clean),
                pnl_association=0.0,
                warnings=("INSUFFICIENT_CLOSED_PNL",),
            )
        ]

    results: list[PatternResult] = []
    pnls = [float(s.closed_pnl_usdc) for s in clean]
    wins = [x for x in pnls if x > 0]
    total_positive = sum(wins)
    if total_positive > 0:
        concentration = max(wins) / total_positive
        if concentration >= 0.30:
            results.append(
                _pattern(
                    wallet,
                    PatternType.ONE_BIG_WIN,
                    confidence=min(1.0, concentration),
                    evidence_count=len(clean),
                    pnl_association=max(wins),
                    risk_flags=("ONE_BIG_WIN_RISK", "PNL_CONCENTRATION_RISK"),
                )
            )

    by_coin: dict[str, float] = {}
    for sample in clean:
        by_coin[sample.coin.upper()] = by_coin.get(sample.coin.upper(), 0.0) + abs(float(sample.closed_pnl_usdc))
    total_abs = sum(by_coin.values())
    if total_abs > 0 and by_coin:
        coin, value = max(by_coin.items(), key=lambda item: item[1])
        share = value / total_abs
        if share >= 0.60:
            results.append(
                _pattern(
                    wallet,
                    PatternType.COIN_SPECIALIST,
                    confidence=share,
                    evidence_count=sum(1 for s in clean if s.coin.upper() == coin),
                    pnl_association=sum(float(s.closed_pnl_usdc) for s in clean if s.coin.upper() == coin),
                    risk_flags=("MONO_COIN_DEPENDENCY",) if share >= 0.80 else (),
                    warnings=(f"dominant_coin={coin}",),
                )
            )

    losses_with_short_holding = [
        s for s in clean
        if s.closed_pnl_usdc < 0 and s.holding_time_ms is not None and s.holding_time_ms <= 15 * 60_000
    ]
    if losses_with_short_holding and len(losses_with_short_holding) / max(1, len([s for s in clean if s.closed_pnl_usdc < 0])) >= 0.60:
        results.append(
            _pattern(
                wallet,
                PatternType.CUTS_LOSSES,
                confidence=len(losses_with_short_holding) / max(1, len(clean)),
                evidence_count=len(losses_with_short_holding),
                pnl_association=sum(float(s.closed_pnl_usdc) for s in losses_with_short_holding),
            )
        )

    wins_with_long_holding = [
        s for s in clean
        if s.closed_pnl_usdc > 0 and s.holding_time_ms is not None and s.holding_time_ms >= 60 * 60_000
    ]
    if wins_with_long_holding and len(wins_with_long_holding) / max(1, len(wins)) >= 0.50:
        results.append(
            _pattern(
                wallet,
                PatternType.LETS_WINNERS_RUN,
                confidence=len(wins_with_long_holding) / max(1, len(wins)),
                evidence_count=len(wins_with_long_holding),
                pnl_association=sum(float(s.closed_pnl_usdc) for s in wins_with_long_holding),
            )
        )

    if not results:
        results.append(
            _pattern(
                wallet,
                PatternType.PNL_CONCENTRATED if total_positive > 0 else PatternType.INSUFFICIENT_DATA,
                confidence=0.25,
                evidence_count=len(clean),
                pnl_association=sum(pnls),
                warnings=("NO_STRONG_PATTERN_DETECTED",),
            )
        )
    return results


def _pattern(
    wallet: str,
    pattern_type: PatternType,
    *,
    confidence: float,
    evidence_count: int,
    pnl_association: float,
    risk_flags: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> PatternResult:
    material = f"{wallet.lower()}|{pattern_type.value}|{evidence_count}|{pnl_association:.8f}|{','.join(risk_flags)}|{','.join(warnings)}"
    return PatternResult(
        pattern_id="pattern:" + sha256(material.encode("utf-8")).hexdigest(),
        wallet=wallet,
        pattern_type=pattern_type,
        confidence=round(max(0.0, min(1.0, confidence)), 6),
        evidence_count=int(evidence_count),
        pnl_association=round(float(pnl_association), 6),
        risk_flags=risk_flags,
        warnings=warnings,
    )


__all__ = ["PatternResult", "PatternType", "detect_wallet_patterns"]
