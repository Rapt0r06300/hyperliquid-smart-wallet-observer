from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


class LeaderStatus(StrEnum):
    SHORTLISTED = "SHORTLISTED"
    REJECTED = "REJECTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    WATCH_ONLY = "WATCH_ONLY"


class LeaderRejectReason(StrEnum):
    TRUNCATED_ADDRESS_REJECTED = "TRUNCATED_ADDRESS_REJECTED"
    INVALID_ADDRESS_REJECTED = "INVALID_ADDRESS_REJECTED"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INSUFFICIENT_CLOSED_PNL = "INSUFFICIENT_CLOSED_PNL"
    PNL_CONCENTRATION_TOO_HIGH = "PNL_CONCENTRATION_TOO_HIGH"
    ONE_BIG_WIN_RISK = "ONE_BIG_WIN_RISK"
    LOW_CONSISTENCY = "LOW_CONSISTENCY"
    MAX_DRAWDOWN_TOO_HIGH = "MAX_DRAWDOWN_TOO_HIGH"


class DeltaAction(StrEnum):
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    ADD = "ADD"
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    UNKNOWN = "UNKNOWN"


class SignalDecision(StrEnum):
    ACCEPT_PAPER = "ACCEPT_PAPER"
    REJECT_NO_TRADE = "REJECT_NO_TRADE"


class NoTradeReason(StrEnum):
    TRUNCATED_ADDRESS_REJECTED = "TRUNCATED_ADDRESS_REJECTED"
    INVALID_ADDRESS_REJECTED = "INVALID_ADDRESS_REJECTED"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INSUFFICIENT_CLOSED_PNL = "INSUFFICIENT_CLOSED_PNL"
    PNL_CONCENTRATION_TOO_HIGH = "PNL_CONCENTRATION_TOO_HIGH"
    ONE_BIG_WIN_RISK = "ONE_BIG_WIN_RISK"
    LOW_CONSISTENCY = "LOW_CONSISTENCY"
    MAX_DRAWDOWN_TOO_HIGH = "MAX_DRAWDOWN_TOO_HIGH"
    STALE_SIGNAL = "STALE_SIGNAL"
    EDGE_UNMEASURABLE = "EDGE_UNMEASURABLE"
    EDGE_REMAINING_TOO_LOW = "EDGE_REMAINING_TOO_LOW"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    SLIPPAGE_TOO_HIGH = "SLIPPAGE_TOO_HIGH"
    LIQUIDITY_TOO_LOW = "LIQUIDITY_TOO_LOW"
    COPY_DEGRADATION_TOO_HIGH = "COPY_DEGRADATION_TOO_HIGH"
    UNKNOWN_DELTA = "UNKNOWN_DELTA"
    REDUCE_OR_CLOSE_NOT_ENTRY = "REDUCE_OR_CLOSE_NOT_ENTRY"
    NO_MATCHING_PAPER_POSITION_FOR_CLOSE = "NO_MATCHING_PAPER_POSITION_FOR_CLOSE"
    DUPLICATE_FILL = "DUPLICATE_FILL"
    BLOCKED_ASSET = "BLOCKED_ASSET"
    MAX_OPEN_PAPER_TRADES_REACHED = "MAX_OPEN_PAPER_TRADES_REACHED"
    NETWORK_READ_DISABLED = "NETWORK_READ_DISABLED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    RATE_LIMIT_GUARD = "RATE_LIMIT_GUARD"
    OPEN_ORDERS_CONTEXT_ONLY = "OPEN_ORDERS_CONTEXT_ONLY"
    API_RESPONSE_INVALID = "API_RESPONSE_INVALID"
    PAGINATION_STOPPED = "PAGINATION_STOPPED"
    WEBSOCKET_LIMIT_GUARD = "WEBSOCKET_LIMIT_GUARD"
    ARCHIVE_DIRTY_ROOT_ZIP = "ARCHIVE_DIRTY_ROOT_ZIP"
    LEADER_EQUITY_MISSING = "LEADER_EQUITY_MISSING"
    LEADER_POSITION_NOTIONAL_UNMEASURABLE = "LEADER_POSITION_NOTIONAL_UNMEASURABLE"
    COPY_NOTIONAL_TOO_SMALL = "COPY_NOTIONAL_TOO_SMALL"
    COPY_NOTIONAL_CAPPED = "COPY_NOTIONAL_CAPPED"
    PAPER_SIZING_INVALID = "PAPER_SIZING_INVALID"


@dataclass(frozen=True)
class LeaderCandidateInput:
    wallet_address: str
    source: str = "leaderboard"
    rank: int | None = None
    history_days: float | None = None
    closed_pnl_points: int = 0
    total_closed_pnl: float | None = None
    max_single_trade_pnl: float | None = None
    max_drawdown_pct: float | None = None
    consistency_score: float | None = None
    per_coin_stability_score: float | None = None
    execution_quality_score: float | None = None
    sample_confidence: float | None = None
    copyability_score: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LeaderShortlistEntry:
    wallet_address: str
    status: LeaderStatus
    score: float
    source: str
    rank: int | None = None
    history_days: float | None = None
    closed_pnl_points: int = 0
    pnl_concentration: float | None = None
    consistency_score: float | None = None
    max_drawdown_pct: float | None = None
    refusal_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LeaderboardShortlistReport:
    generated_at: datetime
    target_count: int
    candidates_seen: int
    entries: list[LeaderShortlistEntry]
    mode: str = "PAPER_MOCK_USDC_ONLY"

    @property
    def shortlisted(self) -> list[LeaderShortlistEntry]:
        return [entry for entry in self.entries if entry.status == LeaderStatus.SHORTLISTED]

    @property
    def rejected(self) -> list[LeaderShortlistEntry]:
        return [entry for entry in self.entries if entry.status == LeaderStatus.REJECTED]


@dataclass(frozen=True)
class PositionView:
    wallet_address: str
    coin: str
    signed_size: float
    timestamp: datetime | None = None
    mark_price: float | None = None


@dataclass(frozen=True)
class FillView:
    wallet_address: str
    coin: str
    direction: str | None
    side: str | None = None
    size: float | None = None
    price: float | None = None
    start_position: float | None = None
    closed_pnl: float | None = None
    timestamp: datetime | None = None
    raw_id: str | None = None


@dataclass(frozen=True)
class LeaderDelta:
    delta_id: str
    leader_wallet: str
    coin: str
    action_type: DeltaAction
    observed_at: datetime
    previous_size: float | None = None
    current_size: float | None = None
    leader_reference_price: float | None = None
    leader_fill_time: datetime | None = None
    raw_event_hash: str | None = None
    source_snapshot_id: str | None = None
    collection_run_id: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EdgeInputs:
    leader_expected_edge_bps: float | None
    leader_consistency_factor: float = 1.0
    signal_freshness_factor: float = 1.0
    delay_cost_bps: float = 0.0
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    fee_bps: float = 0.0
    liquidity_penalty_bps: float = 0.0
    adverse_selection_penalty_bps: float = 0.0
    crowding_penalty_bps: float = 0.0
    funding_penalty_bps: float = 0.0


@dataclass(frozen=True)
class SignalCandidate:
    candidate_id: str
    leader_wallet: str
    coin: str
    action_type: DeltaAction
    observed_at: datetime
    leader_fill_time: datetime | None
    leader_reference_price: float | None
    current_mid: float | None
    spread_bps: float
    slippage_bps: float
    fee_bps: float
    latency_ms: int
    liquidity_score: float
    leader_score: float
    signal_freshness_score: float
    copy_degradation_bps: float
    edge_remaining_bps: float | None
    paper_mode: str
    decision: SignalDecision
    refusal_reasons: list[str]
    raw_event_hash: str
    source_snapshot_id: str | None = None
    collection_run_id: str | None = None


@dataclass(frozen=True)
class NoTradeDecision:
    decision_id: str
    created_at: datetime
    reason: NoTradeReason
    observed: str
    why_not_simulable: str
    missing_data: str
    next_action: str
    leader_wallet: str | None = None
    coin: str | None = None
    candidate_id: str | None = None
    risk_level: str = "INFO"
    component: str = "copy_mode"
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CopyRunReport:
    started_at: datetime
    finished_at: datetime
    interval_seconds: int
    dry_run: bool
    network_read: bool
    ws: bool
    leaders_seen: int
    deltas_seen: int
    signal_candidates: list[SignalCandidate]
    no_trade_decisions: list[NoTradeDecision]
    source_failures: list[str] = field(default_factory=list)
    message: str = "Observation/paper only. No order, no signature, no mainnet."


@dataclass(frozen=True)
class CopySizingInput:
    leader_wallet: str
    coin: str
    action_type: DeltaAction
    leader_position_size: float | None
    leader_reference_price: float | None
    leader_account_value: float | None
    follower_equity: float
    max_notional: float
    min_notional: float = 10.0
    leverage_adjustment: float = 1.0
    blocked_assets: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class CopySizingResult:
    accepted: bool
    requested_notional: float | None
    copy_ratio: float | None
    leader_position_notional: float | None
    refusal_reasons: list[str]
    warnings: list[str] = field(default_factory=list)


def stable_hash(payload: str) -> str:
    return sha256(payload.encode("utf-8")).hexdigest()


def to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value
