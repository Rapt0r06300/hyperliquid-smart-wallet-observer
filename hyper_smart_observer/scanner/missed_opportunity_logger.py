from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MissedOpportunity:
    id: str
    timestamp_ms: int
    coin: str
    wallet: str
    action_type: str
    missed_reason: str
    detected_late_by_seconds: float
    source: str
    would_have_been_candidate: bool
    blocked_by: str
    estimated_simulation_result_if_seen: float | None
    lesson: str
    recommended_fix: str


@dataclass(slots=True)
class MissedOpportunityLogger:
    rows: list[MissedOpportunity] = field(default_factory=list)

    def record(
        self,
        *,
        timestamp_ms: int,
        coin: str,
        wallet: str,
        action_type: str,
        missed_reason: str,
        detected_late_by_seconds: float,
        source: str = "local_scan",
        would_have_been_candidate: bool = False,
        blocked_by: str = "scanner",
        estimated_simulation_result_if_seen: float | None = None,
    ) -> MissedOpportunity:
        row = MissedOpportunity(
            id=f"{timestamp_ms}:{wallet}:{coin}:{action_type}:{missed_reason}",
            timestamp_ms=timestamp_ms,
            coin=coin,
            wallet=wallet,
            action_type=action_type,
            missed_reason=missed_reason,
            detected_late_by_seconds=detected_late_by_seconds,
            source=source,
            would_have_been_candidate=would_have_been_candidate,
            blocked_by=blocked_by,
            estimated_simulation_result_if_seen=estimated_simulation_result_if_seen,
            lesson="Increase local priority or improve freshness before accepting simulation.",
            recommended_fix="Promote wallet to warm/hot watch only if budgets and read-only guards allow it.",
        )
        self.rows.append(row)
        return row

    def report(self, *, period: str = "24h") -> str:
        lines = [
            f"missed_opportunities_period={period}",
            "research_only=true",
            f"count={len(self.rows)}",
        ]
        for row in self.rows[:20]:
            lines.append(f"{row.timestamp_ms} | {row.coin} | {row.wallet} | {row.missed_reason} | {row.recommended_fix}")
        if not self.rows:
            lines.append("No local missed opportunities recorded yet.")
        return "\n".join(lines)
