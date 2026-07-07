from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any

from hl_observer.paper_trading.paper_engine import PaperDecisionResult
from hl_observer.signals.leader_delta import LeaderDelta


@dataclass(frozen=True, slots=True)
class PaperDecisionEvidence:
    decision_id: str
    delta_id: str
    wallet: str
    coin: str
    action: str
    accepted: bool
    risk_decision: str
    reason_codes: tuple[str, ...]
    paper_trade_id: str | None
    paper_position_id: str | None
    equity_usdt: float
    realized_pnl_usdt: float
    unrealized_pnl_usdt: float
    drawdown_usdt: float
    source_refs: tuple[str, ...]
    evidence_hash: str

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["reason_codes"] = "|".join(self.reason_codes)
        row["source_refs"] = "|".join(self.source_refs)
        return row


def evidence_from_paper_result(
    delta: LeaderDelta,
    result: PaperDecisionResult,
    *,
    source_refs: tuple[str, ...] = ("leader_delta", "risk_engine", "paper_engine"),
) -> PaperDecisionEvidence:
    decision_id = "decision:" + delta.delta_id.split(":", 1)[-1]
    risk_decision = getattr(result.risk_decision.decision, "value", str(result.risk_decision.decision))
    payload = {
        "decision_id": decision_id,
        "delta_id": delta.delta_id,
        "accepted": result.accepted,
        "risk_decision": risk_decision,
        "trade": result.trade.trade_id if result.trade else None,
        "position": result.position.position_id if result.position else None,
        "equity": result.equity_usdt,
        "realized": result.realized_pnl_usdt,
        "unrealized": result.unrealized_pnl_usdt,
        "source_refs": source_refs,
    }
    evidence_hash = "ev:" + sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()[:32]
    return PaperDecisionEvidence(
        decision_id=decision_id,
        delta_id=delta.delta_id,
        wallet=delta.wallet,
        coin=delta.coin,
        action=delta.action.value,
        accepted=result.accepted,
        risk_decision=risk_decision,
        reason_codes=tuple(dict.fromkeys((*delta.reason_codes, *result.reason_codes))),
        paper_trade_id=result.trade.trade_id if result.trade else None,
        paper_position_id=result.position.position_id if result.position else None,
        equity_usdt=result.equity_usdt,
        realized_pnl_usdt=result.realized_pnl_usdt,
        unrealized_pnl_usdt=result.unrealized_pnl_usdt,
        drawdown_usdt=result.drawdown_usdt,
        source_refs=source_refs,
        evidence_hash=evidence_hash,
    )


__all__ = ["PaperDecisionEvidence", "evidence_from_paper_result"]
