from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass(slots=True)
class ConsensusSnapshot:
    timestamp_ms: int
    coin: str
    direction: str
    action_type: str
    wallet_count: int
    high_quality_wallet_count: int
    total_observed_notional: float
    median_wallet_score: float
    weighted_confidence: float
    consensus_strength: float
    top_wallets: list[str] = field(default_factory=list)
    conflicting_wallets: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_position_consensus(events: list[dict], *, timestamp_ms: int, high_quality_threshold: float = 70.0) -> list[ConsensusSnapshot]:
    buckets: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for event in events:
        coin = str(event.get("coin") or "").upper()
        direction = str(event.get("direction") or event.get("side") or "").upper()
        action = str(event.get("action_type") or "UNKNOWN").upper()
        if not coin or not direction:
            continue
        buckets[(coin, direction, action)].append(event)

    snapshots: list[ConsensusSnapshot] = []
    for (coin, direction, action), rows in buckets.items():
        scores = sorted(float(row.get("wallet_score", 0.0) or 0.0) for row in rows)
        notionals = [float(row.get("notional", 0.0) or 0.0) for row in rows]
        high_quality = sum(1 for score in scores if score >= high_quality_threshold)
        median = scores[len(scores) // 2] if scores else 0.0
        weighted = min(1.0, (sum(scores) / max(1, len(scores))) / 100.0)
        strength = min(1.0, (len(rows) / 10.0) * weighted)
        warnings = []
        if len(rows) < 2:
            warnings.append("LOW_WALLET_COUNT")
        if high_quality == 0:
            warnings.append("NO_HIGH_QUALITY_WALLET")
        snapshots.append(
            ConsensusSnapshot(
                timestamp_ms=timestamp_ms,
                coin=coin,
                direction=direction,
                action_type=action,
                wallet_count=len(rows),
                high_quality_wallet_count=high_quality,
                total_observed_notional=round(sum(notionals), 8),
                median_wallet_score=median,
                weighted_confidence=round(weighted, 6),
                consensus_strength=round(strength, 6),
                top_wallets=[str(row.get("wallet") or row.get("wallet_address") or "") for row in rows[:5]],
                warnings=warnings,
            )
        )
    return sorted(snapshots, key=lambda row: row.consensus_strength, reverse=True)
