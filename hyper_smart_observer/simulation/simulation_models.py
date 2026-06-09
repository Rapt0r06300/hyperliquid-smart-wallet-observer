from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SimulationSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class SimulationAction(StrEnum):
    OPEN = "OPEN"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"


class SimulationRunMode(StrEnum):
    LIVE = "LIVE"
    BACKTEST = "BACKTEST"
    REPLAY = "REPLAY"
    TEST_FIXTURE = "TEST_FIXTURE"


class SimulationSourceQuality(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    REPLAY = "REPLAY"
    FIXTURE = "FIXTURE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    starting_equity: float = 1000.0
    max_position_notional: float = 50.0
    max_total_exposure: float = 200.0
    max_open_positions: int = 3
    fee_bps: float = 5.0
    spread_bps: float = 2.0
    slippage_bps: float = 5.0
    latency_ms: int = 500
    partial_fill_ratio: float = 1.0


@dataclass(frozen=True, slots=True)
class SimulationIntent:
    wallet_address: str
    coin: str
    side: SimulationSide
    action: SimulationAction
    reference_price: float
    requested_notional: float
    observed_at_ms: int
    signal_id: str
    run_mode: SimulationRunMode = SimulationRunMode.LIVE
    source_quality: SimulationSourceQuality = SimulationSourceQuality.UNKNOWN


@dataclass(slots=True)
class SimulationDecision:
    accepted: bool
    reason: str
    message: str
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SimulationFill:
    fill_id: str
    coin: str
    side: SimulationSide
    action: SimulationAction
    price: float
    size: float
    notional: float
    fee: float
    timestamp_ms: int
    realized_pnl: float = 0.0

