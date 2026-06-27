"""Phase 5: deterministic paper EXIT decision layer (simulation-only, read-only).

This module decides WHEN/HOW to reduce or close existing local paper positions
by following a leader's REDUCE/CLOSE and by applying local protective stops
(time stop, max-holding, trailing stop, max adverse/favorable excursion). It NEVER
sends an order and NEVER signs anything: execution is delegated to the existing
``PaperTradingSimulator.close_paper_trade`` (no parallel PnL engine).

Deny-by-default: no matching paper position, unpriceable exit, or non-reducing
"reduce" all yield NO_TRADE with an explicit reason. A paper trade is not an order.

Stop predicate lineage (kept inline to avoid cross-package import fragility):
``src/hl_observer/exits/{time_stop,trailing_stop}.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from hyper_smart_observer.copy_mode.copy_models import NoTradeReason

_PAPER_WARNINGS = ["LOCAL PAPER SIMULATION ONLY", "Not a trading signal. Not an order."]


class ExitAction(str, Enum):
    CLOSE = "CLOSE"
    REDUCE = "REDUCE"
    NO_TRADE = "NO_TRADE"


class ExitTrigger(str, Enum):
    LEADER_CLOSE = "LEADER_CLOSE"
    LEADER_REDUCE = "LEADER_REDUCE"
    TIME_STOP = "TIME_STOP"
    MAX_HOLDING = "MAX_HOLDING"
    TRAILING_STOP = "TRAILING_STOP"
    MAX_ADVERSE = "MAX_ADVERSE"
    MAX_FAVORABLE = "MAX_FAVORABLE"


@dataclass(frozen=True)
class OpenPaperPosition:
    trade_id: str
    coin: str
    side: str  # BUY/LONG or SELL/SHORT
    entry_price: float
    size: float
    opened_at: datetime
    wallet_address: str | None = None

    @property
    def is_long(self) -> bool:
        return self.side.upper() in ("BUY", "LONG")


@dataclass(frozen=True)
class ExitPolicy:
    max_holding_seconds: float = 3_600.0
    trailing_stop_bps: float = 18.0
    max_adverse_bps: float = 25.0
    max_favorable_bps: float = 35.0


@dataclass(frozen=True)
class LeaderExitSignal:
    coin: str
    trigger: ExitTrigger  # LEADER_CLOSE or LEADER_REDUCE
    exit_reference_price: float | None
    wallet_address: str | None = None
    leader_prev_size: float | None = None
    leader_curr_size: float | None = None


@dataclass(frozen=True)
class ExitDecision:
    action: ExitAction
    trade_id: str | None
    trigger: ExitTrigger | None
    exit_reference_price: float | None
    reduce_fraction: float | None = None
    reason_codes: list[str] = field(default_factory=list)
    note: str = ""
    warnings: list[str] = field(default_factory=lambda: list(_PAPER_WARNINGS))


def _no_trade(reason: str, note: str, *, coin: str | None = None) -> ExitDecision:
    return ExitDecision(
        action=ExitAction.NO_TRADE,
        trade_id=None,
        trigger=None,
        exit_reference_price=None,
        reason_codes=[reason],
        note=note,
    )


def _matching(positions, coin, wallet_address, already_exited_ids):
    done = set(already_exited_ids or ())
    coin_u = coin.upper()
    out = []
    for p in positions:
        if p.trade_id in done:
            continue
        if p.coin.upper() != coin_u:
            continue
        if wallet_address is not None and (p.wallet_address or "").lower() != wallet_address.lower():
            continue
        out.append(p)
    return out


def decide_leader_exit(
    signal: LeaderExitSignal,
    open_positions,
    *,
    already_exited_ids=None,
) -> list[ExitDecision]:
    """Follow a leader REDUCE/CLOSE on matching local paper positions.

    CLOSE -> close every matching paper trade. REDUCE -> close the single oldest
    matching paper trade (partial position reduction using the existing engine).
    """

    matches = _matching(open_positions, signal.coin, signal.wallet_address, already_exited_ids)
    if not matches:
        return [
            _no_trade(
                NoTradeReason.NO_MATCHING_PAPER_POSITION_FOR_CLOSE.value,
                f"No open paper position for {signal.coin.upper()} to exit.",
            )
        ]
    px = signal.exit_reference_price
    if px is None or px <= 0:
        return [
            _no_trade(
                NoTradeReason.EDGE_UNMEASURABLE.value,
                "Exit reference price missing/non-positive; cannot price exit.",
            )
        ]

    if signal.trigger == ExitTrigger.LEADER_REDUCE:
        if (
            signal.leader_prev_size is not None
            and signal.leader_curr_size is not None
            and abs(signal.leader_curr_size) >= abs(signal.leader_prev_size)
        ):
            return [
                _no_trade(
                    NoTradeReason.REDUCE_OR_CLOSE_NOT_ENTRY.value,
                    "Leader size did not actually decrease; not a reduction.",
                )
            ]
        oldest = sorted(matches, key=lambda p: p.opened_at)[0]
        reduce_fraction = _leader_reduce_fraction(signal.leader_prev_size, signal.leader_curr_size)
        return [
            ExitDecision(
                action=ExitAction.REDUCE,
                trade_id=oldest.trade_id,
                trigger=ExitTrigger.LEADER_REDUCE,
                exit_reference_price=px,
                reduce_fraction=reduce_fraction,
                note=f"Follow leader reduce: partial close {reduce_fraction:.4f} of oldest matching paper trade.",
            )
        ]

    # LEADER_CLOSE -> close all matching
    return [
        ExitDecision(
            action=ExitAction.CLOSE,
            trade_id=p.trade_id,
            trigger=ExitTrigger.LEADER_CLOSE,
            exit_reference_price=px,
            note="Follow leader close.",
        )
        for p in sorted(matches, key=lambda p: p.opened_at)
    ]


def _excursion_bps(position: OpenPaperPosition, current_price: float) -> float:
    """Signed favorable-direction excursion in bps (positive = in profit)."""
    if position.entry_price <= 0:
        return 0.0
    move = (current_price - position.entry_price) / position.entry_price * 10_000.0
    return move if position.is_long else -move


def _leader_reduce_fraction(prev_size: float | None, curr_size: float | None) -> float:
    """Fraction of local paper trade to reduce, derived from leader size change."""
    if prev_size is None or curr_size is None:
        return 0.5
    old_abs = abs(float(prev_size))
    new_abs = abs(float(curr_size))
    if old_abs <= 0 or new_abs >= old_abs:
        return 0.5
    return max(0.01, min(1.0, (old_abs - new_abs) / old_abs))


def decide_stop_exits(
    open_positions,
    *,
    coin: str,
    current_price: float | None,
    now: datetime | None = None,
    policy: ExitPolicy | None = None,
    already_exited_ids=None,
    best_price: float | None = None,
) -> list[ExitDecision]:
    """Apply local protective stops to matching open paper positions.

    Reuses time-stop and trailing-stop logic (lineage in module docstring). Emits a
    CLOSE per triggered position; deny-by-default when the exit is unpriceable.
    """

    policy = policy or ExitPolicy()
    now = now or datetime.now(timezone.utc)
    matches = _matching(open_positions, coin, None, already_exited_ids)
    if not matches:
        return [
            _no_trade(
                NoTradeReason.NO_MATCHING_PAPER_POSITION_FOR_CLOSE.value,
                f"No open paper position for {coin.upper()} to stop-exit.",
            )
        ]
    if current_price is None or current_price <= 0:
        return [
            _no_trade(
                NoTradeReason.EDGE_UNMEASURABLE.value,
                "Current price missing/non-positive; cannot evaluate stops.",
            )
        ]

    decisions: list[ExitDecision] = []
    for p in sorted(matches, key=lambda p: p.opened_at):
        age_s = (now - p.opened_at).total_seconds()
        excursion = _excursion_bps(p, current_price)
        trigger: ExitTrigger | None = None
        if age_s >= policy.max_holding_seconds:
            trigger = ExitTrigger.MAX_HOLDING
        elif excursion <= -abs(policy.max_adverse_bps):
            trigger = ExitTrigger.MAX_ADVERSE
        elif excursion >= abs(policy.max_favorable_bps):
            trigger = ExitTrigger.MAX_FAVORABLE
        elif best_price is not None and best_price > 0:
            # trailing stop: long stops below trail; short stops above trail
            if p.is_long:
                trail = best_price * (1 - policy.trailing_stop_bps / 10_000.0)
                if current_price <= trail:
                    trigger = ExitTrigger.TRAILING_STOP
            else:
                trail = best_price * (1 + policy.trailing_stop_bps / 10_000.0)
                if current_price >= trail:
                    trigger = ExitTrigger.TRAILING_STOP
        if trigger is not None:
            decisions.append(
                ExitDecision(
                    action=ExitAction.CLOSE,
                    trade_id=p.trade_id,
                    trigger=trigger,
                    exit_reference_price=current_price,
                    note=f"Protective stop: {trigger.value}.",
                )
            )
    if not decisions:
        return [
            _no_trade(
                NoTradeReason.REDUCE_OR_CLOSE_NOT_ENTRY.value,
                "No stop triggered for matching positions.",
            )
        ]
    return decisions


def apply_exit_decisions(simulator, decisions):
    """Execute CLOSE/REDUCE decisions against the EXISTING PaperTradingSimulator.

    Returns the simulator's PaperCloseResult list. NO_TRADE decisions are skipped.
    The simulator itself refuses to re-close a non-open trade (duplicate guard).
    """

    results = []
    for d in decisions:
        if d.action == ExitAction.NO_TRADE or d.trade_id is None:
            continue
        if d.exit_reference_price is None or d.exit_reference_price <= 0:
            continue
        reason = d.trigger.value if d.trigger else "EXIT"
        if d.action == ExitAction.REDUCE:
            results.append(
                simulator.partial_close_paper_trade(
                    d.trade_id,
                    d.exit_reference_price,
                    reason,
                    fraction=d.reduce_fraction or 0.5,
                )
            )
        else:
            results.append(simulator.close_paper_trade(d.trade_id, d.exit_reference_price, reason))
    return results
