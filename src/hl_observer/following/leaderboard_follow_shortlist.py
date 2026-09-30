from __future__ import annotations

from sqlalchemy.orm import Session

from hl_observer.storage.models import TopWallet


def load_leaderboard_follow_shortlist(session: Session, *, limit: int = 50) -> list[str]:
    return [
        row.wallet_address
        for row in session.query(TopWallet).order_by(TopWallet.score.desc()).limit(limit).all()
    ]
