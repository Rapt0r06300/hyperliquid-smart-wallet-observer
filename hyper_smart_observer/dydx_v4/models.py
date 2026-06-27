"""
Modèles normalisés internes dYdX v4.

Ces modèles sont indépendants du format brut dYdX.
Le reste du logiciel consomme uniquement ces modèles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum):
        """Compatibilité Python 3.10."""
        def __str__(self) -> str:
            return self.value

from typing import Optional


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #

class PositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    UNKNOWN = "UNKNOWN"


class LifecycleEvent(StrEnum):
    OPEN = "OPEN"
    ADD = "ADD"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"
    FLIP = "FLIP"
    LIQUIDATION = "LIQUIDATION"
    UNKNOWN = "UNKNOWN"


class OrderStatus(StrEnum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    BEST_EFFORT_CANCELED = "BEST_EFFORT_CANCELED"
    BEST_EFFORT_OPENED = "BEST_EFFORT_OPENED"
    UNTRIGGERED = "UNTRIGGERED"
    UNKNOWN = "UNKNOWN"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class PaperTradeStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    STOPPED = "STOPPED"


class NoTradeReason(StrEnum):
    STALE_SIGNAL = "STALE_SIGNAL"
    EDGE_REMAINING_TOO_LOW = "EDGE_REMAINING_TOO_LOW"
    EDGE_BELOW_COST_MULTIPLIER = "EDGE_BELOW_COST_MULTIPLIER"
    LIQUIDITY_TOO_LOW = "LIQUIDITY_TOO_LOW"
    SPREAD_TOO_HIGH = "SPREAD_TOO_HIGH"
    PRICE_DEVIATION_TOO_HIGH = "PRICE_DEVIATION_TOO_HIGH"
    COPY_DEGRADATION_TOO_HIGH = "COPY_DEGRADATION_TOO_HIGH"
    UNKNOWN_DELTA = "UNKNOWN_DELTA"
    NO_MATCHING_PAPER_POSITION_FOR_CLOSE = "NO_MATCHING_PAPER_POSITION_FOR_CLOSE"
    ORPHAN_CLOSE = "ORPHAN_CLOSE"
    ADD_WITHOUT_OPEN = "ADD_WITHOUT_OPEN"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    ACCOUNT_NOT_SHORTLISTED = "ACCOUNT_NOT_SHORTLISTED"
    MARKET_NOT_WHITELISTED = "MARKET_NOT_WHITELISTED"
    MARKET_BLACKLISTED = "MARKET_BLACKLISTED"
    DATA_GAP_DETECTED = "DATA_GAP_DETECTED"
    WEBSOCKET_DEGRADED = "WEBSOCKET_DEGRADED"
    REST_BACKFILL_REQUIRED = "REST_BACKFILL_REQUIRED"
    SAFETY_DENY_BY_DEFAULT = "SAFETY_DENY_BY_DEFAULT"
    TEST_FIXTURE_ACCOUNT = "TEST_FIXTURE_ACCOUNT"
    MAX_OPEN_TRADES_REACHED = "MAX_OPEN_TRADES_REACHED"
    POSITION_ALREADY_LOSING = "POSITION_ALREADY_LOSING"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    LIFECYCLE_UNKNOWN = "LIFECYCLE_UNKNOWN"
    MARKET_ILLIQUID = "MARKET_ILLIQUID"
    LEADERS_LOSING_AFTER_COSTS = "LEADERS_LOSING_AFTER_COSTS"
    CONSENSUS_NOT_REACHED = "CONSENSUS_NOT_REACHED"
    INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"


class SimulationMode(StrEnum):
    LIVE = "live"
    BACKTEST = "backtest"
    REPLAY = "replay"
    TEST_FIXTURE = "test_fixture"


# --------------------------------------------------------------------------- #
# Modèles normalisés
# --------------------------------------------------------------------------- #

@dataclass
class NormalizedMarket:
    """Marché dYdX v4 normalisé."""
    market_id: str          # ex: "BTC-USD"
    base_asset: str         # ex: "BTC"
    quote_asset: str        # ex: "USD"
    tick_size: float
    step_size: float
    min_order_size: float
    oracle_price: float
    index_price: float
    mid_price: float
    best_bid: float
    best_ask: float
    spread_bps: float
    volume_24h: float
    open_interest: float
    is_active: bool
    updated_at_ms: int
    raw: dict = field(default_factory=dict)

    @property
    def spread_usdc(self) -> float:
        return self.best_ask - self.best_bid if self.best_ask > 0 and self.best_bid > 0 else 0.0


@dataclass
class NormalizedAccount:
    """Compte dYdX v4 normalisé."""
    address: str
    network: str
    subaccount_count: int = 0
    updated_at_ms: int = 0
    raw: dict = field(default_factory=dict)


@dataclass
class NormalizedSubaccount:
    """Subaccount dYdX v4 normalisé."""
    account_address: str
    subaccount_number: int   # 0, 1, 2, ...
    equity: float
    free_collateral: float
    margin_usage: float      # 0.0 à 1.0
    leverage: float
    updated_at_ms: int
    raw: dict = field(default_factory=dict)

    @property
    def subaccount_id(self) -> str:
        return f"{self.account_address}/{self.subaccount_number}"


@dataclass
class NormalizedOrder:
    """Ordre dYdX v4 normalisé."""
    order_id: str
    account_address: str
    subaccount_number: int
    market_id: str
    side: OrderSide
    size: float
    price: float
    status: OrderStatus
    type: str                # "LIMIT", "MARKET", etc.
    time_in_force: str
    created_at_ms: int
    updated_at_ms: int
    total_filled: float = 0.0
    raw: dict = field(default_factory=dict)


@dataclass
class NormalizedFill:
    """Fill dYdX v4 normalisé."""
    fill_id: str
    account_address: str
    subaccount_number: int
    market_id: str
    side: OrderSide
    size: float
    price: float
    fee: float
    liquidity: str           # "TAKER" ou "MAKER"
    created_at_ms: int
    order_id: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @property
    def notional_usdc(self) -> float:
        return self.size * self.price

    @property
    def fee_bps(self) -> float:
        if self.notional_usdc <= 0:
            return 0.0
        return (self.fee / self.notional_usdc) * 10_000


@dataclass
class NormalizedTrade:
    """Trade public dYdX v4 normalisé."""
    trade_id: str
    market_id: str
    side: OrderSide
    size: float
    price: float
    created_at_ms: int
    type: str = "LIMIT"
    raw: dict = field(default_factory=dict)


@dataclass
class NormalizedPosition:
    """Position ouverte dYdX v4 normalisée."""
    account_address: str
    subaccount_number: int
    market_id: str
    side: PositionSide
    size: float                  # taille absolue
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    realized_pnl: float
    net_funding: float
    margin: float
    leverage: float
    liquidation_price: Optional[float]
    opened_at_ms: int
    updated_at_ms: int
    raw: dict = field(default_factory=dict)

    @property
    def position_key(self) -> str:
        return f"dydx_v4|{self.account_address}|{self.subaccount_number}|{self.market_id}|{self.side}"

    @property
    def notional_usdc(self) -> float:
        return abs(self.size) * self.mark_price

    @property
    def gross_pnl(self) -> float:
        """PnL brut sans frais."""
        if self.side == PositionSide.LONG:
            return (self.mark_price - self.entry_price) * abs(self.size)
        elif self.side == PositionSide.SHORT:
            return (self.entry_price - self.mark_price) * abs(self.size)
        return 0.0


@dataclass
class NormalizedPositionDelta:
    """Delta de position (changement détecté entre deux snapshots)."""
    account_address: str
    subaccount_number: int
    market_id: str
    side: PositionSide
    lifecycle: LifecycleEvent
    size_delta: float         # positif = augmentation
    price: float
    timestamp_ms: int
    fill_id: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @property
    def is_valid_lifecycle(self) -> bool:
        return self.lifecycle != LifecycleEvent.UNKNOWN


@dataclass
class SignalCandidate:
    """Candidat signal dYdX (jamais un ordre)."""
    signal_id: str
    account_address: str
    subaccount_number: int
    market_id: str
    side: PositionSide
    lifecycle: LifecycleEvent
    size: float
    price: float
    signal_age_ms: int
    edge_remaining_bps: float
    total_cost_bps: float
    source: str              # "rest_snapshot" | "ws_fill"
    simulation_mode: SimulationMode
    created_at_ms: int
    score: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def is_fresh(self) -> bool:
        return self.signal_age_ms <= 4000

    @property
    def is_live_eligible(self) -> bool:
        return (
            self.is_fresh
            and self.lifecycle != LifecycleEvent.UNKNOWN
            and self.simulation_mode == SimulationMode.LIVE
        )


@dataclass
class NoTradeDecision:
    """Décision de refus enregistrée."""
    decision_id: str
    reason: NoTradeReason
    signal_candidate_id: Optional[str]
    account_address: Optional[str]
    market_id: Optional[str]
    detail: str
    timestamp_ms: int
    simulation_mode: SimulationMode


@dataclass
class PaperTrade:
    """Trade paper simulé (jamais un vrai ordre)."""
    trade_id: str
    account_address: str
    subaccount_number: int
    market_id: str
    side: PositionSide
    size: float
    entry_price: float
    mark_price: float
    status: PaperTradeStatus
    lifecycle: LifecycleEvent
    gross_pnl: float
    net_pnl: float
    fees: float
    spread_cost: float
    slippage_cost: float
    entry_at_ms: int
    updated_at_ms: int
    closed_at_ms: Optional[int] = None
    close_reason: Optional[str] = None
    simulation_mode: SimulationMode = SimulationMode.LIVE
    signal_id: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    @property
    def position_key(self) -> str:
        return f"dydx_v4|{self.account_address}|{self.subaccount_number}|{self.market_id}|{self.side}"

    def compute_pnl(self, mark_price: float, fee_bps: float = 5.0) -> tuple[float, float]:
        """
        Calcule (gross_pnl, net_pnl) avec la formule correcte.

        LONG:  (mark - entry) * size
        SHORT: (entry - mark) * size
        """
        if self.side == PositionSide.LONG:
            gross = (mark_price - self.entry_price) * abs(self.size)
        else:
            gross = (self.entry_price - mark_price) * abs(self.size)

        notional = abs(self.size) * self.entry_price
        # Frais aller-retour (entrée + sortie)
        fees = notional * (fee_bps / 10_000) * 2
        net = gross - fees
        return gross, net


@dataclass
class PaperPosition:
    """Position paper en cours."""
    position_key: str
    account_address: str
    subaccount_number: int
    market_id: str
    side: PositionSide
    size: float
    entry_price: float
    current_mark_price: float
    realized_pnl: float
    unrealized_pnl: float
    total_fees: float
    opened_at_ms: int
    updated_at_ms: int
    simulation_mode: SimulationMode = SimulationMode.LIVE
    trade_ids: list[str] = field(default_factory=list)

    @property
    def net_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl - self.total_fees
