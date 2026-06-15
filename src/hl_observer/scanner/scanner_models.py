from __future__ import annotations

from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass
from typing import Any


class ScanTier(StrEnum):
    COLD = "COLD"
    WARM = "WARM"
    HOT = "HOT"


class MissedOpportunityReason(StrEnum):
    STALE_SIGNAL = "STALE_SIGNAL"
    RATE_LIMIT_GUARD = "RATE_LIMIT_GUARD"
    WALLET_SKIPPED_BY_BUDGET = "WALLET_SKIPPED_BY_BUDGET"
    NETWORK_READ_DISABLED = "NETWORK_READ_DISABLED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    MISSING_CURRENT_MID = "MISSING_CURRENT_MID"
    EDGE_UNMEASURABLE = "EDGE_UNMEASURABLE"
    EDGE_REMAINING_TOO_LOW = "EDGE_REMAINING_TOO_LOW"
    LIQUIDITY_TOO_LOW = "LIQUIDITY_TOO_LOW"
    COPY_DEGRADATION_TOO_HIGH = "COPY_DEGRADATION_TOO_HIGH"
    NO_MATCHING_PAPER_POSITION_FOR_CLOSE = "NO_MATCHING_PAPER_POSITION_FOR_CLOSE"
    MAX_OPEN_PAPER_TRADES_REACHED = "MAX_OPEN_PAPER_TRADES_REACHED"
    INVALID_WALLET_ADDRESS = "INVALID_WALLET_ADDRESS"
    TRUNCATED_WALLET_ADDRESS = "TRUNCATED_WALLET_ADDRESS"


@dataclass(slots=True)
class WalletPriorityInput:
    wallet_address: str
    source: str = "unknown"
    trades_count: int = 0
    observed_notional_usdt: float = 0.0
    last_seen_ms: int | None = None
    now_ms: int = 0
    wallet_quality_score: float = 0.0
    consistency_score: float = 0.0
    copyability_score: float = 0.0
    consensus_hits: int = 0
    source_health_score: float = 1.0
    one_big_win_risk: float = 0.0
    drawdown_pct: float = 0.0
    inactive_penalty: float = 0.0


@dataclass(slots=True)
class WalletPriorityScore:
    wallet_address: str
    source: str
    priority_score: float
    status: str
    reasons: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class ScanBudget:
    max_leaders_per_run: int = 3
    max_ws_unique_users: int = 10
    rest_weight_limit_per_minute: int = 1200
    rest_weight_remaining: int = 1200
    max_pages_per_wallet: int = 5
    max_fills_per_run: int = 10_000
    network_read_enabled: bool = False


@dataclass(slots=True)
class ScanSelection:
    selected_wallets: list[WalletPriorityScore]
    skipped: list["MissedOpportunity"]
    stopped_reason: str


@dataclass(slots=True)
class SignalObservation:
    signal_id: str
    wallet_address: str
    coin: str
    action_type: str
    observed_at_ms: int
    now_ms: int
    current_mid: float | None = None
    edge_remaining_bps: float | None = None
    liquidity_score: float = 1.0
    copy_degradation_bps: float = 0.0
    has_matching_paper_position: bool = True
    open_positions_count: int = 0
    max_open_positions: int = 3
    source: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MissedOpportunity:
    reason: str
    wallet_address: str | None
    coin: str | None
    action_type: str | None
    observed_at_ms: int | None
    detected_at_ms: int
    component: str
    message: str
    next_action: str
    severity: str = "INFO"
    details: dict[str, Any] = field(default_factory=dict)

