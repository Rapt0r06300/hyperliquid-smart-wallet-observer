from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


class WalletStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    OBSERVED = "OBSERVED"
    SHORTLISTED = "SHORTLISTED"
    BLOCKED = "BLOCKED"
    IGNORED = "IGNORED"


class SignalState(StrEnum):
    OBSERVED = "OBSERVED"
    CANDIDATE = "CANDIDATE"
    REJECTED_BY_RISK = "REJECTED_BY_RISK"
    PAPER_ACCEPTED = "PAPER_ACCEPTED"
    TESTNET_PENDING = "TESTNET_PENDING"
    TESTNET_REJECTED = "TESTNET_REJECTED"
    TESTNET_ACCEPTED = "TESTNET_ACCEPTED"


class WalletScoreStatus(StrEnum):
    SCORED = "SCORED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_DATA = "INVALID_DATA"
    BLOCKED = "BLOCKED"
    NEEDS_MORE_HISTORY = "NEEDS_MORE_HISTORY"
    REJECTED_BY_RISK = "REJECTED_BY_RISK"


class PaperIntentStatus(StrEnum):
    CREATED = "CREATED"
    REJECTED_BY_RISK = "REJECTED_BY_RISK"
    ACCEPTED_FOR_SIMULATION = "ACCEPTED_FOR_SIMULATION"
    CANCELLED = "CANCELLED"
    INVALID_DATA = "INVALID_DATA"


class PaperTradeStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    INVALID = "INVALID"


class PositionActionType(StrEnum):
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    INCREASE_LONG = "INCREASE_LONG"
    INCREASE_SHORT = "INCREASE_SHORT"
    REDUCE_LONG = "REDUCE_LONG"
    REDUCE_SHORT = "REDUCE_SHORT"
    LIQUIDATION = "LIQUIDATION"
    FUNDING = "FUNDING"
    TRANSFER = "TRANSFER"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    ORDER_OPEN = "ORDER_OPEN"
    ORDER_CANCEL = "ORDER_CANCEL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Wallet:
    address: str
    source: str
    label: str | None = None
    discovered_at: datetime = field(default_factory=utc_now)
    status: WalletStatus = WalletStatus.DISCOVERED
    notes: str | None = None


@dataclass(frozen=True)
class Fill:
    wallet_address: str
    coin: str
    side: str
    price: float
    size: float
    fee: float
    timestamp: datetime
    raw_id: str | None = None
    source: str = "hyperliquid_info"
    closed_pnl: float | None = None
    action_type: str | None = None
    start_position: float | None = None
    fee_token: str | None = None
    raw_json: str | None = None


@dataclass(frozen=True)
class PositionSnapshot:
    wallet_address: str
    coin: str
    size: float
    timestamp: datetime
    entry_price: float | None = None
    mark_price: float | None = None
    unrealized_pnl: float | None = None
    leverage: float | None = None


@dataclass(frozen=True)
class WalletScore:
    wallet_address: str
    calculated_at: datetime
    total_trades: int
    winrate: float | None = None
    pnl_net: float | None = None
    max_drawdown: float | None = None
    profit_factor: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    calmar: float | None = None
    confidence_score: float | None = None
    final_score: float | None = None
    refusal_reason: str | None = None


@dataclass(frozen=True)
class ScoreBreakdown:
    wallet_address: str
    calculated_at: datetime
    status: WalletScoreStatus
    total_fills: int
    usable_fills: int
    skipped_fills: int
    first_fill_at: datetime | None = None
    last_fill_at: datetime | None = None
    history_days: float | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None
    total_fees: float | None = None
    winrate: float | None = None
    average_win: float | None = None
    average_loss: float | None = None
    profit_factor: float | None = None
    max_drawdown: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    calmar: float | None = None
    sample_quality_score: float = 0.0
    recency_score: float = 0.0
    consistency_score: float = 0.0
    risk_score: float = 0.0
    confidence_score: float = 0.0
    final_score: float | None = None
    refusal_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Signal:
    signal_id: str
    wallet_address: str
    coin: str
    side: str
    confidence: float
    created_at: datetime
    state: SignalState
    reason: str


@dataclass(frozen=True)
class PaperIntent:
    intent_id: str
    wallet_address: str
    coin: str
    side: str
    reference_price: float
    requested_notional: float
    created_at: datetime
    source: str
    reason: str
    score_snapshot_id: str | None = None
    status: PaperIntentStatus = PaperIntentStatus.CREATED
    refusal_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PaperExecutionEstimate:
    reference_price: float
    spread_bps: float
    slippage_bps: float
    fee_rate_bps: float
    latency_ms: int
    simulated_entry_price: float
    estimated_fee_entry: float
    simulated_exit_price: float | None = None
    estimated_fee_exit: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PaperTrade:
    trade_id: str
    signal_id: str
    coin: str
    side: str
    entry_price: float
    size: float
    simulated_fee: float
    simulated_slippage: float
    opened_at: datetime
    closed_at: datetime | None = None
    exit_price: float | None = None
    pnl: float | None = None
    state: str = "OPEN"
    intent_id: str | None = None
    wallet_address: str | None = None
    notional: float | None = None
    fee_entry: float | None = None
    fee_exit: float | None = None
    slippage_entry: float | None = None
    slippage_exit: float | None = None
    spread_cost: float = 0.0
    gross_pnl: float | None = None
    net_pnl: float | None = None
    status: PaperTradeStatus = PaperTradeStatus.OPEN
    close_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PaperPortfolioSnapshot:
    timestamp: datetime
    starting_equity: float
    current_equity: float
    realized_pnl: float
    unrealized_pnl: float
    total_fees: float
    open_trades: int
    closed_trades: int
    max_drawdown: float | None = None


@dataclass(frozen=True)
class RiskEvent:
    severity: str
    component: str
    reason_code: str
    message: str
    blocked_action: str
    context: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=utc_now)
