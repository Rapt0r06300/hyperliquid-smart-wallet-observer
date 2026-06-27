"""Unified copy-decision gate (V12 H - deny-by-default, taxonomie §17).

A single pure function that runs the copy-eligibility gates IN ORDER, deny-by-default,
each failure expressed as a canonical NO_TRADE reason (the 7-attribute schema). It does
NOT replace the existing risk engine internals; it is the taxonomy-aligned facade the
dashboard / DecisionLedger can use uniformly. Composes lifecycle_gate + the taxonomy.

Pure / deterministic: takes already-computed features, returns a decision. No I/O, no
order, no fabricated data. Missing required inputs -> INSUFFICIENT_DATA (never guessed).
"""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.signals.lifecycle_gate import lifecycle_no_trade_code
from hl_observer.signals.no_trade_taxonomy import NoTradeReason, reason


@dataclass(frozen=True, slots=True)
class CopyInputs:
    source_usable: bool = True
    lifecycle_action: str | None = None      # PositionAction value, optional
    has_known_position: bool = True
    quotes_agree: bool = True
    mid_available: bool = True
    signal_age_ms: int | None = None
    max_signal_age_ms: int = 30_000
    liquidity_score: float | None = None
    min_liquidity_score: float = 0.0
    spread_bps: float | None = None
    max_spread_bps: float = 1e9
    net_edge_bps: float | None = None
    min_edge_bps: float = 0.0


@dataclass(frozen=True, slots=True)
class CopyDecision:
    accepted: bool
    reason: NoTradeReason | None
    checks_passed: tuple[str, ...]

    @property
    def reason_code(self) -> str | None:
        return self.reason.reason_code if self.reason is not None else None


def evaluate_copy_candidate(inp: CopyInputs) -> CopyDecision:
    passed: list[str] = []

    def block(code: str, **kw) -> CopyDecision:
        return CopyDecision(accepted=False, reason=reason(code, **kw), checks_passed=tuple(passed))

    # 1) source usable (deny-by-default upstream feeds this)
    if not inp.source_usable:
        return block("INSUFFICIENT_DATA", missing_data=("usable_source",))
    passed.append("source_usable")

    # 2) lifecycle (UNKNOWN / FLIP / ORPHAN_CLOSE)
    if inp.lifecycle_action is not None:
        lc = lifecycle_no_trade_code(inp.lifecycle_action, has_known_position=inp.has_known_position)
        if lc is not None:
            return block(lc)
        passed.append("lifecycle")

    # 3) REST/WS quote agreement
    if not inp.quotes_agree:
        return block("SOURCE_CONFLICT")
    passed.append("quotes_agree")

    # 4) mark available
    if not inp.mid_available:
        return block("MID_MISSING")
    passed.append("mid")

    # 5) signal freshness
    if inp.signal_age_ms is None:
        return block("INSUFFICIENT_DATA", missing_data=("signal_age_ms",))
    if inp.signal_age_ms > inp.max_signal_age_ms:
        return block("SIGNAL_TOO_OLD")
    passed.append("freshness")

    # 6) liquidity
    if inp.liquidity_score is not None and inp.liquidity_score < inp.min_liquidity_score:
        return block("LIQUIDITY_TOO_LOW")
    passed.append("liquidity")

    # 7) spread
    if inp.spread_bps is not None and inp.spread_bps > inp.max_spread_bps:
        return block("SPREAD_TOO_WIDE")
    passed.append("spread")

    # 8) net edge after costs
    if inp.net_edge_bps is None:
        return block("EDGE_UNMEASURABLE")
    if inp.net_edge_bps < inp.min_edge_bps:
        return block("EDGE_REMAINING_TOO_LOW")
    passed.append("edge")

    return CopyDecision(accepted=True, reason=None, checks_passed=tuple(passed))


__all__ = ["CopyInputs", "CopyDecision", "evaluate_copy_candidate"]
