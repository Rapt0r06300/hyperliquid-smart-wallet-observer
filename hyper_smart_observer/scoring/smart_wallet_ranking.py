from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.models import ScoreBreakdown, WalletScoreStatus
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories import scores_repo


@dataclass(frozen=True)
class SmartWalletRanking:
    wallet_address: str
    computed_at: datetime
    rank_score: float
    status: str
    reason: str
    warnings: list[str] = field(default_factory=list)


class SmartWalletRankingEngine:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config

    def rank_from_latest_scores(self, limit: int = 50) -> list[SmartWalletRanking]:
        if self.config is None:
            return []
        initialize_database(self.config)
        with get_connection(self.config) as conn:
            rows = scores_repo.list_latest_scores(conn, limit=limit)
        return sorted(
            [self.rank_score(_score_from_row(row)) for row in rows],
            key=lambda item: item.rank_score,
            reverse=True,
        )

    def rank_scores(self, scores: list[ScoreBreakdown]) -> list[SmartWalletRanking]:
        rankings = [self.rank_score(score) for score in scores]
        return sorted(rankings, key=lambda item: item.rank_score, reverse=True)

    def rank_score(self, score: ScoreBreakdown) -> SmartWalletRanking:
        warnings: list[str] = []
        if score.status != WalletScoreStatus.SCORED:
            return SmartWalletRanking(
                wallet_address=score.wallet_address,
                computed_at=datetime.now(UTC),
                rank_score=0.0,
                status="REJECTED",
                reason="wallet score is not SCORED",
                warnings=["eligible for further research observation only"],
            )
        if score.sample_quality_score < 60 or score.confidence_score < 60:
            warnings.append("sample/confidence below ranking threshold")
            return SmartWalletRanking(score.wallet_address, datetime.now(UTC), 0.0, "REJECTED", "insufficient quality", warnings)
        rank_score = (
            0.30 * score.sample_quality_score
            + 0.25 * score.confidence_score
            + 0.20 * score.risk_score
            + 0.15 * score.consistency_score
            + 0.10 * score.recency_score
        )
        return SmartWalletRanking(
            wallet_address=score.wallet_address,
            computed_at=datetime.now(UTC),
            rank_score=max(0.0, min(100.0, rank_score)),
            status="RESEARCH_OBSERVATION",
            reason="eligible for further research observation only",
            warnings=warnings,
        )


def _score_from_row(row) -> ScoreBreakdown:
    status_value = row["status"] or "INSUFFICIENT_DATA"
    try:
        status = WalletScoreStatus(status_value)
    except ValueError:
        status = WalletScoreStatus.INVALID_DATA
    return ScoreBreakdown(
        wallet_address=row["wallet_address"],
        calculated_at=datetime.fromisoformat(row["calculated_at"]),
        status=status,
        total_fills=int(row["total_trades"] or 0),
        usable_fills=int(row["usable_fills"] or row["total_trades"] or 0),
        skipped_fills=int(row["skipped_fills"] or 0),
        sample_quality_score=float(row["sample_quality_score"] or 0.0),
        recency_score=float(row["recency_score"] or 0.0),
        consistency_score=float(row["consistency_score"] or 0.0),
        risk_score=float(row["risk_score"] or 0.0),
        confidence_score=float(row["confidence_score"] or 0.0),
        final_score=row["final_score"],
        refusal_reason=row["refusal_reason"],
    )
