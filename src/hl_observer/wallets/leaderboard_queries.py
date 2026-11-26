from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hl_observer.storage.models import LeaderboardWalletCandidate


def latest_leaderboard_candidate_rows(
    session: Session,
    *,
    limit: int,
    period: str | None = None,
    min_pnl: float | None = None,
    min_roi: float | None = None,
) -> list[LeaderboardWalletCandidate]:
    """Return a bounded pool with only the newest imported row per wallet.

    The optional period narrows the history *before* choosing each wallet's latest
    row. Metric filters apply afterward, so an older row cannot pass a filter when
    that wallet's current row does not.
    """
    if limit <= 0:
        return []

    latest_ids_query = select(func.max(LeaderboardWalletCandidate.id).label("id")).group_by(
        func.lower(LeaderboardWalletCandidate.wallet_address)
    )
    if period is not None:
        latest_ids_query = latest_ids_query.where(LeaderboardWalletCandidate.period == period)
    latest_ids = latest_ids_query.subquery()

    query = select(LeaderboardWalletCandidate).join(latest_ids, LeaderboardWalletCandidate.id == latest_ids.c.id)
    if min_pnl is not None:
        query = query.where(LeaderboardWalletCandidate.pnl_usdc >= min_pnl)
    if min_roi is not None:
        query = query.where(LeaderboardWalletCandidate.roi_pct >= min_roi)
    query = query.order_by(LeaderboardWalletCandidate.id.desc()).limit(limit)
    return list(session.scalars(query).all())
