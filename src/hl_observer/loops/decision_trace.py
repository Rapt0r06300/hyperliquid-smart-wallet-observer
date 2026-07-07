from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hl_observer.loops.models import LoopRunResult
from hl_observer.testnet.models import unix_ms


@dataclass(frozen=True, slots=True)
class LoopDecisionTrace:
    """Dashboard/audit trace for one local decision.

    This is not an execution ledger and never implies a real order. It links the
    observed SignalCandidate to the local decision, prepared testnet request and
    optional fake/testnet result so UI spikes and no-trades can be explained.
    """

    trace_id: str
    run_id: str
    candidate_id: str | None
    coin: str | None
    side: str | None
    signal_type: str | None
    decision_action: str
    execution_status: str
    edge_remaining_bps: float | None
    order_action: str | None
    reduce_only: bool | None
    reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at_ms: int = field(default_factory=unix_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "candidate_id": self.candidate_id,
            "coin": self.coin,
            "side": self.side,
            "signal_type": self.signal_type,
            "decision_action": self.decision_action,
            "execution_status": self.execution_status,
            "edge_remaining_bps": self.edge_remaining_bps,
            "order_action": self.order_action,
            "reduce_only": self.reduce_only,
            "reasons": list(self.reasons),
            "evidence": dict(self.evidence),
            "created_at_ms": self.created_at_ms,
        }


def build_decision_traces(result: LoopRunResult) -> list[LoopDecisionTrace]:
    traces: list[LoopDecisionTrace] = []
    feedback_by_candidate = {item.candidate_id: item for item in result.feedback}
    for index, decision in enumerate(result.decisions):
        candidate_id = _str_or_none(decision.get("candidate_id"))
        feedback = feedback_by_candidate.get(candidate_id)
        evidence = _dict(decision.get("evidence"))
        candidate = _dict(evidence.get("candidate"))
        request = _dict(decision.get("order_request"))
        trace = LoopDecisionTrace(
            trace_id=f"{result.run_id}-{index}",
            run_id=result.run_id,
            candidate_id=candidate_id,
            coin=_str_or_none(candidate.get("coin") or request.get("coin")),
            side=_str_or_none(candidate.get("side") or request.get("side")),
            signal_type=_str_or_none(candidate.get("signal_type")),
            decision_action=str(decision.get("action") or "UNKNOWN"),
            execution_status=feedback.execution_status if feedback else "UNKNOWN",
            edge_remaining_bps=_float_or_none(candidate.get("edge_remaining_bps")),
            order_action=_str_or_none(request.get("action")),
            reduce_only=_bool_or_none(request.get("reduce_only")),
            reasons=list(feedback.reasons if feedback else decision.get("reasons") or []),
            evidence=evidence,
            created_at_ms=feedback.created_at_ms if feedback else result.created_at_ms,
        )
        traces.append(trace)
    return traces


def traces_to_dicts(result: LoopRunResult) -> list[dict[str, Any]]:
    return [trace.to_dict() for trace in build_decision_traces(result)]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)
