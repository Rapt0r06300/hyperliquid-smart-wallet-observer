"""Single entry guard — composes the V9 risk layers (S7 wiring helper).

The runtime has several independent V9 gates: the burst ``CircuitBreaker``, the
smart-money ``leader_quality_gate``, the per-decision ``exec_gates`` (liquidity /
spread / staleness), and the net-edge bar. This module folds them into ONE
deny-by-default decision so the copy loop can gate an entry with a single call
instead of re-implementing the wiring inline.

It is deliberately *pure*: the caller passes already-computed signals (or the
small result objects), and gets back ``allow`` + ordered ``reasons``. It performs
no I/O, no scoring, and — like every module here — never places an order. A
blocked entry simply means "no paper entry this tick".
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EntryGuardConfig:
    require_leader_quality: bool = True
    """If True, a leader that is not smart-money qualified blocks the entry."""
    min_edge_bps: float = 10.0
    """Net edge (after all costs) required to allow an entry."""


@dataclass(frozen=True, slots=True)
class EntryGuardDecision:
    allow: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def blocked(self) -> bool:
        return not self.allow


def _dedupe(reasons: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for r in reasons:
        if r and r not in seen:
            seen.add(r)
            ordered.append(r)
    return tuple(ordered)


def evaluate_entry(
    *,
    now_sec: float,
    circuit_tripped: bool = False,
    leader_qualified: bool | None = None,
    exec_blocked: bool = False,
    exec_reasons: tuple[str, ...] = (),
    edge_remaining_bps: float | None = None,
    config: EntryGuardConfig | None = None,
) -> EntryGuardDecision:
    """Combine the gate signals into one deny-by-default entry decision."""
    cfg = config or EntryGuardConfig()
    reasons: list[str] = []

    if circuit_tripped:
        reasons.append("CIRCUIT_BREAKER_TRIPPED")
    if cfg.require_leader_quality and leader_qualified is False:
        reasons.append("LEADER_NOT_SMART_MONEY")
    if exec_blocked:
        reasons.extend(exec_reasons or ("EXEC_GATE_BLOCKED",))
    if edge_remaining_bps is not None and edge_remaining_bps < cfg.min_edge_bps:
        reasons.append("EDGE_REMAINING_TOO_LOW")

    ordered = _dedupe(reasons)
    return EntryGuardDecision(allow=not ordered, reasons=ordered)


def evaluate_entry_from_components(
    *,
    now_sec: float,
    circuit_breaker=None,
    leader_quality=None,
    exec_gate_result=None,
    edge_remaining_bps: float | None = None,
    config: EntryGuardConfig | None = None,
) -> EntryGuardDecision:
    """Convenience overload that accepts the live result objects directly.

    - ``circuit_breaker``: a ``CircuitBreaker`` (or None to skip).
    - ``leader_quality``: a ``LeaderQuality`` with ``.qualified`` (or None).
    - ``exec_gate_result``: an ``ExecGateResult`` with ``.blocked`` / ``.reasons``.
    """
    circuit_tripped = bool(circuit_breaker is not None and not circuit_breaker.allow_entry(now_sec))
    leader_qualified = None if leader_quality is None else bool(getattr(leader_quality, "qualified", False))
    exec_blocked = bool(exec_gate_result is not None and getattr(exec_gate_result, "blocked", False))
    exec_reasons = tuple(getattr(exec_gate_result, "reasons", ()) or ()) if exec_gate_result is not None else ()
    return evaluate_entry(
        now_sec=now_sec,
        circuit_tripped=circuit_tripped,
        leader_qualified=leader_qualified,
        exec_blocked=exec_blocked,
        exec_reasons=exec_reasons,
        edge_remaining_bps=edge_remaining_bps,
        config=config,
    )


__all__ = [
    "EntryGuardConfig",
    "EntryGuardDecision",
    "evaluate_entry",
    "evaluate_entry_from_components",
]
