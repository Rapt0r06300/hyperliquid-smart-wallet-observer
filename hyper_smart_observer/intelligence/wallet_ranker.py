from __future__ import annotations

from dataclasses import dataclass

from hyper_smart_observer.intelligence.wallet_intelligence import WalletIntelligenceReport


@dataclass(slots=True)
class WalletRank:
    rank: int
    wallet_address: str
    copyability_score: float
    quality_score: float
    status: str
    risk_flags: list[str]


def rank_wallet_reports(reports: list[WalletIntelligenceReport], *, limit: int = 50) -> list[WalletRank]:
    ordered = sorted(
        reports,
        key=lambda row: (row.copyability_score, row.quality_score, -len(row.risk_flags)),
        reverse=True,
    )
    return [
        WalletRank(
            rank=index,
            wallet_address=report.wallet_address,
            copyability_score=report.copyability_score,
            quality_score=report.quality_score,
            status=report.status,
            risk_flags=report.risk_flags,
        )
        for index, report in enumerate(ordered[: max(0, limit)], start=1)
    ]
