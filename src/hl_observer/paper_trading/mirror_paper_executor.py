"""Paper-only executor for wallet mirror candidates.

The module glues together V14 copy-trading ideas:
leader delta -> proportional sizing -> slippage/depth guard -> risk approval
-> local PaperSimConnector. It never creates or submits a real order.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable

from hl_observer.copy_mode.wallet_mirror_runtime import MirrorCandidate, candidate_to_paper_intent
from hl_observer.paper_trading.paper_connector import PaperSimConnector, PaperSimConnectorResult
from hl_observer.risk.proportional_paper_sizer import ProportionalSizingConfig, size_proportional_paper_notional
from hl_observer.risk.slippage_guard_v2 import SlippageGuardConfig, evaluate_slippage_guard_v2
from hl_observer.strategies.models import PaperIntent, approve_with_risk, approve_with_risk_and_gate


RiskFn = Callable[[PaperIntent], tuple[bool, list[str] | tuple[str, ...]]]


@dataclass(frozen=True, slots=True)
class MirrorPaperExecutionConfig:
    sizing: ProportionalSizingConfig = field(default_factory=ProportionalSizingConfig)
    slippage: SlippageGuardConfig = field(default_factory=SlippageGuardConfig)
    min_candidate_confidence: float = 0.55


@dataclass(frozen=True, slots=True)
class MirrorPaperExecutionResult:
    accepted: bool
    candidate_id: str
    intent: PaperIntent | None
    paper_result: PaperSimConnectorResult | None
    reason_codes: tuple[str, ...]
    evidence: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "candidate_id": self.candidate_id,
            "intent": asdict(self.intent) if self.intent else None,
            "paper_result": self.paper_result.as_dict() if self.paper_result else None,
            "reason_codes": list(self.reason_codes),
            "evidence": self.evidence,
            "paper_only": True,
            "external_action": False,
        }


def execute_mirror_candidate_paper(
    candidate: MirrorCandidate,
    *,
    equity_usdt: float,
    mid_price: float,
    top_depth_usdt: float | None = None,
    asks: tuple[tuple[float, float], ...] = (),
    bids: tuple[tuple[float, float], ...] = (),
    observed_at_ms: int,
    connector: PaperSimConnector | None = None,
    risk_fn: RiskFn | None = None,
    config: MirrorPaperExecutionConfig | None = None,
) -> MirrorPaperExecutionResult:
    cfg = config or MirrorPaperExecutionConfig()
    reasons = list(candidate.reason_codes)
    evidence: dict[str, object] = {
        "candidate": candidate.as_dict(),
        "paper_only": True,
        "external_action": False,
        "observed_at_ms": int(observed_at_ms),
    }
    if not candidate.is_entry:
        reasons.append("MIRROR_ENTRY_ONLY")
    if candidate.confidence < cfg.min_candidate_confidence:
        reasons.append("MIRROR_CANDIDATE_CONFIDENCE_LOW")
    if candidate.side not in {"LONG", "SHORT"}:
        reasons.append("MIRROR_SIDE_UNKNOWN")
    if reasons:
        return _reject(candidate, reasons, evidence=evidence)

    sizing = size_proportional_paper_notional(
        leader_size=candidate.leader_size,
        leader_price=candidate.leader_price,
        equity_usdt=equity_usdt,
        config=cfg.sizing,
    )
    evidence["sizing"] = asdict(sizing)
    if not sizing.accepted:
        return _reject(candidate, [sizing.reason], evidence=evidence)

    side_for_book = "BUY" if candidate.side == "LONG" else "SELL"
    slippage = evaluate_slippage_guard_v2(
        side=side_for_book,
        notional_usdt=sizing.paper_notional_usdt,
        mid_price=mid_price,
        asks=asks,
        bids=bids,
        config=cfg.slippage,
    )
    evidence["slippage_guard"] = asdict(slippage)
    if not slippage.accepted:
        return _reject(candidate, [slippage.reason], evidence=evidence)

    intent = candidate_to_paper_intent(
        candidate,
        target_notional_usdt=sizing.paper_notional_usdt,
        created_at_ms=observed_at_ms,
    )
    from hl_observer.signals.entry_gate_runtime import make_gate_fn  # lazy: evite un import circulaire
    _entry_gate_fn = make_gate_fn(lambda _i: {
        "edge_net_bps": float(getattr(candidate, "edge_remaining_bps", 0.0) or 0.0),
        "liquidity_ok": True,          # slippage guard deja passe ci-dessus
        "fill_confirmed": True,        # on copie un FILL leader confirme, pas un openOrder
    })
    approve = approve_with_risk_and_gate(intent, risk_fn or _default_risk_fn, gate_fn=_entry_gate_fn)
    evidence["risk"] = {"risk_ok": approve.risk_ok, "risk_reasons": list(approve.risk_reasons)}
    from hl_observer.signals.entry_gate_runtime import entry_gate_enabled  # lazy
    evidence["entry_gate"] = {"enabled": entry_gate_enabled()}  # A6 : trace au ledger/evidence
    if not approve.risk_ok:
        return MirrorPaperExecutionResult(
            accepted=False,
            candidate_id=candidate.candidate_id,
            intent=intent,
            paper_result=None,
            reason_codes=tuple(dict.fromkeys(("RISK_NOT_APPROVED", *approve.risk_reasons))),
            evidence=evidence,
        )

    paper_connector = connector or PaperSimConnector()
    result = paper_connector.apply_intent(
        approve,
        mid_price=mid_price,
        top_depth_usdt=top_depth_usdt,
        observed_at_ms=observed_at_ms,
        asks=asks,
        bids=bids,
        min_fill_ratio=cfg.slippage.min_fill_ratio,
    )
    evidence["paper_connector"] = result.as_dict()
    return MirrorPaperExecutionResult(
        accepted=result.accepted,
        candidate_id=candidate.candidate_id,
        intent=intent,
        paper_result=result,
        reason_codes=tuple(result.reason_codes),
        evidence=evidence,
    )


def _default_risk_fn(intent: PaperIntent) -> tuple[bool, tuple[str, ...]]:
    if intent.target_notional_usdt <= 0:
        return False, ("PAPER_NOTIONAL_MISSING",)
    if intent.side.value not in {"LONG", "SHORT"}:
        return False, ("PAPER_SIDE_INVALID",)
    # A5 : risk gate portefeuille (halts/DD/VaR) — lazy import, OFF par defaut = inchange
    from hl_observer.risk.risk_gate_runtime import risk_gate_check
    g_ok, g_reasons = risk_gate_check()
    if not g_ok:
        return False, g_reasons
    return True, ()


def _reject(
    candidate: MirrorCandidate,
    reasons: list[str],
    *,
    evidence: dict[str, object],
) -> MirrorPaperExecutionResult:
    return MirrorPaperExecutionResult(
        accepted=False,
        candidate_id=candidate.candidate_id,
        intent=None,
        paper_result=None,
        reason_codes=tuple(dict.fromkeys(reasons)),
        evidence=evidence,
    )


__all__ = [
    "MirrorPaperExecutionConfig",
    "MirrorPaperExecutionResult",
    "execute_mirror_candidate_paper",
]
