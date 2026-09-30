from __future__ import annotations

from pydantic import BaseModel, Field

from hl_observer.copying.leaderboard_autoselect import CopyLeaderAutoSelectConfig, select_copy_leaders
from hl_observer.wallets.leaderboard_models import LeaderboardCandidate
from hl_observer.wallets.leaderboard_validation import is_full_wallet_address


class RankedTopWallet(BaseModel):
    wallet_address: str
    rank: int | None = None
    source: str = "leaderboard"
    score: float
    reasons: list[str] = Field(default_factory=list)


def rank_top_wallets(
    candidates: list[LeaderboardCandidate],
    *,
    target: int = 500,
    min_score: float = 50.0,
) -> list[RankedTopWallet]:
    ranked: list[RankedTopWallet] = []
    report = select_copy_leaders(
        candidates,
        config=CopyLeaderAutoSelectConfig(
            top_n=target,
            min_score=min_score,
            require_positive_pnl=False,
            require_positive_roi=False,
        ),
    )
    by_address = {candidate.wallet_address.lower(): candidate for candidate in candidates}
    for selection in report.accepted:
        address = selection.wallet_address.lower()
        if not is_full_wallet_address(address):
            continue
        candidate = by_address[address]
        ranked.append(
            RankedTopWallet(
                wallet_address=address,
                rank=candidate.rank,
                score=selection.score,
                reasons=[
                    "leaderboard_full_address",
                    "smart_copy_leader_filters",
                    *selection.reasons,
                    *selection.warnings,
                ],
            )
        )
        if len(ranked) >= target:
            break
    return ranked
