from __future__ import annotations

from sqlalchemy.orm import Session

from hl_observer.following.follow_decision_engine import FollowDecisionKind
from hl_observer.storage.models import FollowDecision, FollowSignal, PaperFollowOrder
from hl_observer.utils.time import now_ms


def create_paper_follow_orders(session: Session, *, max_signals: int = 20) -> int:
    signals = session.query(FollowSignal).order_by(FollowSignal.created_at_ms.desc()).limit(max_signals).all()
    created = 0
    for signal in signals:
        decision = session.query(FollowDecision).filter(FollowDecision.signal_id == signal.id).order_by(
            FollowDecision.computed_at_ms.desc()
        ).first()
        if decision is None or decision.decision != FollowDecisionKind.PAPER_FOLLOW_ALLOWED.value:
            continue
        order_id = f"paper-follow:{signal.id}"
        if session.get(PaperFollowOrder, order_id) is not None:
            continue
        session.add(
            PaperFollowOrder(
                id=order_id,
                signal_id=signal.id,
                wallet_address=signal.wallet_address,
                coin=signal.coin,
                side=signal.side,
                notional_usdc=1.0,
                status="SIMULATED",
                created_at_ms=now_ms(),
            )
        )
        created += 1
    return created
