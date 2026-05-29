from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class WalletStatus(StrEnum):
    REJECTED = "REJECTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    WATCH_ONLY = "WATCH_ONLY"
    SHORTLISTED = "SHORTLISTED"
    ACTIVE_LEADER = "ACTIVE_LEADER"
    BLOCKED = "BLOCKED"


class SignalDecision(StrEnum):
    IGNORE = "IGNORE"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    PAPER_CANDIDATE = "PAPER_CANDIDATE"
    PAPER_TRADE = "PAPER_TRADE"
    TESTNET_CANDIDATE = "TESTNET_CANDIDATE"
    TESTNET_ALLOWED = "TESTNET_ALLOWED"
    WAIT_FOR_PULLBACK = "WAIT_FOR_PULLBACK"
    WAIT_FOR_CONFIRMATION = "WAIT_FOR_CONFIRMATION"
    EXPIRED = "EXPIRED"
    REJECT_TOO_LATE = "REJECT_TOO_LATE"
    REJECT_EDGE_NEGATIVE = "REJECT_EDGE_NEGATIVE"
    REJECT_EDGE_TOO_SMALL = "REJECT_EDGE_TOO_SMALL"
    REJECT_EDGE_TOO_WEAK = "REJECT_EDGE_TOO_WEAK"
    REJECT_TOO_ILLIQUID = "REJECT_TOO_ILLIQUID"
    REJECT_SPREAD_TOO_WIDE = "REJECT_SPREAD_TOO_WIDE"
    REJECT_SLIPPAGE_TOO_HIGH = "REJECT_SLIPPAGE_TOO_HIGH"
    REJECT_WALLET_TOXIC = "REJECT_WALLET_TOXIC"
    REJECT_WALLET_UNPROVEN = "REJECT_WALLET_UNPROVEN"
    REJECT_WALLET_DEGRADED = "REJECT_WALLET_DEGRADED"
    REJECT_SAMPLE_TOO_SMALL = "REJECT_SAMPLE_TOO_SMALL"
    REJECT_ONE_BIG_WIN_WALLET = "REJECT_ONE_BIG_WIN_WALLET"
    REJECT_MARTINGALE_PATTERN = "REJECT_MARTINGALE_PATTERN"
    REJECT_MARKET_REGIME_BAD = "REJECT_MARKET_REGIME_BAD"
    REJECT_CROWDING_TOO_HIGH = "REJECT_CROWDING_TOO_HIGH"
    REJECT_CROWDING_RISK = "REJECT_CROWDING_RISK"
    REJECT_EXIT_PLAN_WEAK = "REJECT_EXIT_PLAN_WEAK"
    REJECT_EXIT_NOT_CLEAR = "REJECT_EXIT_NOT_CLEAR"
    REJECT_DATA_GAP = "REJECT_DATA_GAP"
    REJECT_WS_RECENTLY_RECONNECTED = "REJECT_WS_RECENTLY_RECONNECTED"
    REJECT_RECONCILIATION_UNCERTAIN = "REJECT_RECONCILIATION_UNCERTAIN"
    REJECT_DUPLICATE_ORDER_RISK = "REJECT_DUPLICATE_ORDER_RISK"
    REJECT_API_UNSTABLE = "REJECT_API_UNSTABLE"
    REJECT_MAINNET_FORBIDDEN = "REJECT_MAINNET_FORBIDDEN"
    REJECT_TESTNET_LOCKED = "REJECT_TESTNET_LOCKED"
    REJECT_PRICE_ALREADY_MOVED = "REJECT_PRICE_ALREADY_MOVED"
    REJECT_COPY_DEGRADATION_TOO_HIGH = "REJECT_COPY_DEGRADATION_TOO_HIGH"
    REJECT_UNKNOWN_POSITION_STATE = "REJECT_UNKNOWN_POSITION_STATE"
    REJECT_ORDERBOOK_STALE = "REJECT_ORDERBOOK_STALE"


class WalletStyle(StrEnum):
    SCALPER = "SCALPER"
    MOMENTUM_TRADER = "MOMENTUM_TRADER"
    BREAKOUT_TRADER = "BREAKOUT_TRADER"
    MEAN_REVERSION_TRADER = "MEAN_REVERSION_TRADER"
    SWING_TRADER = "SWING_TRADER"
    DCA_TRADER = "DCA_TRADER"
    MARTINGALE_AVERAGER = "MARTINGALE_AVERAGER"
    HIGH_LEVERAGE_RISKY = "HIGH_LEVERAGE_RISKY"
    ONE_BIG_WIN = "ONE_BIG_WIN"
    HEDGER_OR_COMPLEX = "HEDGER_OR_COMPLEX"
    ALTCOIN_SPECIALIST = "ALTCOIN_SPECIALIST"
    BTC_ETH_MAJOR_ONLY = "BTC_ETH_MAJOR_ONLY"
    HYPE_SPECIALIST = "HYPE_SPECIALIST"
    WHALE_POSITIONAL = "WHALE_POSITIONAL"
    ILLIQUIDITY_HUNTER = "ILLIQUIDITY_HUNTER"
    NEWS_REACTIVE = "NEWS_REACTIVE"
    UNKNOWN = "UNKNOWN"


class OrderStatusKind(StrEnum):
    OPEN = "open"
    FILLED = "filled"
    CANCELED = "canceled"
    TRIGGERED = "triggered"
    REJECTED = "rejected"
    MARGIN_CANCELED = "marginCanceled"
    REDUCE_ONLY_CANCELED = "reduceOnlyCanceled"
    SCHEDULED_CANCEL = "scheduledCancel"
    TICK_REJECTED = "tickRejected"
    MIN_TRADE_NTL_REJECTED = "minTradeNtlRejected"
    UNKNOWN = "unknown"


REJECTED_ORDER_STATUSES = {
    OrderStatusKind.REJECTED,
    OrderStatusKind.MARGIN_CANCELED,
    OrderStatusKind.REDUCE_ONLY_CANCELED,
    OrderStatusKind.TICK_REJECTED,
    OrderStatusKind.MIN_TRADE_NTL_REJECTED,
}


class OrderStatus(BaseModel):
    status: OrderStatusKind
    is_rejected: bool = False
    raw: dict = Field(default_factory=dict)


class WalletProfile(BaseModel):
    address: str
    trades_count: int = 0
    fills_count: int = 0
    closed_pnl_count: int = 0
    active_days: int = 0
    history_days: float = 0.0
    pnl_bps: float = 0.0
    pnl_total_usdc: float = 0.0
    pnl_net_after_fees_usdc: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown_bps: float = 0.0
    max_drawdown_pct: float = 0.0
    pnl_concentration: float = 0.0
    top_trade_pnl_share: float = 0.0
    coins_traded_count: int = 0
    main_coin: str | None = None
    avg_hold_time_minutes: float = 0.0
    recent_activity_score: float = 0.0
    regularity_score: float = 0.0
    copyability_score: float = 0.0
    toxicity_score: float = 0.0
    style: WalletStyle = WalletStyle.UNKNOWN
    status: WalletStatus = WalletStatus.INSUFFICIENT_DATA


class WalletScore(BaseModel):
    address: str
    score: float
    status: WalletStatus = WalletStatus.INSUFFICIENT_DATA
    decision: SignalDecision
    reasons: list[str] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)


class SignalCandidate(BaseModel):
    id: str
    source_wallet: str
    coin: str
    side: Literal["long", "short"]
    signal_type: Literal["open", "add", "reduce", "close", "flip"]
    observed_price: float
    timestamp_ms: int
    signal_age_ms: int
    wallet_score: float = 0.0
    signal_score: float = 0.0
    edge_remaining_bps: float = 0.0
    estimated_fee_bps: float = 0.0
    estimated_spread_bps: float = 0.0
    estimated_slippage_bps: float = 0.0
    estimated_latency_decay_bps: float = 0.0
    orderbook_depth_usdc: float = 0.0
    crowding_score: float = 0.0
    exit_plan_id: str | None = None
    decision: SignalDecision = SignalDecision.OBSERVE_ONLY
    reject_reason: str | None = None

    @field_validator("coin")
    @classmethod
    def coin_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("coin is required")
        return value.upper()


class SignalScore(BaseModel):
    signal_id: str
    score: float
    decision: SignalDecision
    reasons: list[str] = Field(default_factory=list)


class EdgeRemainingInputs(BaseModel):
    leader_expected_move_bps: float = 0.0
    cluster_confirmation_bps: float = 0.0
    orderbook_confirmation_bps: float = 0.0
    regime_bonus_bps: float = 0.0
    taker_fee_bps: float = 0.0
    spread_cost_bps: float = 0.0
    estimated_slippage_bps: float = 0.0
    latency_decay_bps: float = 0.0
    adverse_selection_bps: float = 0.0
    funding_expected_cost_bps: float = 0.0


class EdgeRemaining(BaseModel):
    expected_edge_bps: float
    costs_bps: float
    edge_remaining_bps: float
    min_edge_required_bps: float
    decision: SignalDecision
    reasons: list[str] = Field(default_factory=list)


class RiskDecision(BaseModel):
    allowed: bool
    decision: SignalDecision
    reasons: list[str] = Field(default_factory=list)
    gates: dict[str, bool] = Field(default_factory=dict)


class PaperOrder(BaseModel):
    order_id: str
    signal_id: str
    coin: str
    side: Literal["buy", "sell"]
    notional_usdc: float
    requested_price: float
    simulated_fill_price: float
    fee_bps: float
    slippage_bps: float
    decision: SignalDecision
    rejected_reason: str | None = None


class GainAssuranceSignal(BaseModel):
    signal_id: str
    wallet: str
    coin: str
    side: Literal["long", "short"]
    signal_type: str
    wallet_style: WalletStyle
    wallet_score: float
    gain_assurance_score: float
    lead_lag_score: float
    copy_half_life_ms: int
    edge_remaining_bps: float
    replicable_pnl_estimate_bps: float
    entry_copy_degradation_bps: float | None
    expected_exit_capture_ratio: float
    market_regime: str
    entry_plan: str
    exit_plan: str
    decision: SignalDecision
    reject_reason: str | None = None
