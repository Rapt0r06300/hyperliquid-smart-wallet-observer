from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass(slots=True)
class ClusterEvent:
    event_id: str
    coin: str
    action_type: str
    start_time_ms: int
    end_time_ms: int
    wallets: list[str]
    wallet_count: int
    high_quality_wallet_count: int
    total_notional: float
    avg_quality_score: float
    consensus_strength: float
    copyability_score: float
    simulation_score: float
    risk_flags: list[str] = field(default_factory=list)


def detect_wallet_clusters(events: list[dict], *, window_ms: int = 4_000, high_quality_threshold: float = 70.0) -> list[ClusterEvent]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for event in events:
        coin = str(event.get("coin") or "").upper()
        action = str(event.get("action_type") or "UNKNOWN").upper()
        if coin:
            grouped[(coin, action)].append(event)
    clusters: list[ClusterEvent] = []
    for (coin, action), rows in grouped.items():
        ordered = sorted(rows, key=lambda row: int(row.get("timestamp_ms", 0) or 0))
        cursor = 0
        while cursor < len(ordered):
            start = int(ordered[cursor].get("timestamp_ms", 0) or 0)
            bucket: list[dict] = []
            while cursor < len(ordered) and int(ordered[cursor].get("timestamp_ms", 0) or 0) - start <= window_ms:
                bucket.append(ordered[cursor])
                cursor += 1
            if len(bucket) < 2:
                continue
            scores = [float(row.get("wallet_score", 0.0) or 0.0) for row in bucket]
            copy_scores = [float(row.get("copyability_score", 0.0) or 0.0) for row in bucket]
            simulation_scores = [float(row.get("simulation_score", 0.0) or 0.0) for row in bucket]
            wallets = list(dict.fromkeys(str(row.get("wallet") or row.get("wallet_address") or "") for row in bucket))
            high_quality = sum(1 for score in scores if score >= high_quality_threshold)
            avg_quality = sum(scores) / max(1, len(scores))
            consensus_strength = min(1.0, (len(wallets) / 10.0) * (avg_quality / 100.0))
            risks = []
            if high_quality == 0:
                risks.append("NO_HIGH_QUALITY_WALLET")
            if consensus_strength < 0.2:
                risks.append("WEAK_CLUSTER")
            clusters.append(
                ClusterEvent(
                    event_id=f"{coin}:{action}:{start}:{len(wallets)}",
                    coin=coin,
                    action_type=action,
                    start_time_ms=start,
                    end_time_ms=max(int(row.get("timestamp_ms", start) or start) for row in bucket),
                    wallets=wallets,
                    wallet_count=len(wallets),
                    high_quality_wallet_count=high_quality,
                    total_notional=sum(float(row.get("notional", 0.0) or 0.0) for row in bucket),
                    avg_quality_score=round(avg_quality, 6),
                    consensus_strength=round(consensus_strength, 6),
                    copyability_score=round(sum(copy_scores) / max(1, len(copy_scores)), 6),
                    simulation_score=round(sum(simulation_scores) / max(1, len(simulation_scores)), 6),
                    risk_flags=risks,
                )
            )
    return sorted(clusters, key=lambda row: row.consensus_strength, reverse=True)
