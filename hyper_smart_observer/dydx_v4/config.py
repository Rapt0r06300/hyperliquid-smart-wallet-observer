"""
Configuration dYdX v4 — valeurs sûres par défaut.

TOUTES les options dangereuses sont désactivées par défaut.
Aucune clé privée, aucun seed, aucune mnemonic n'est demandé.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum):
        """Compatibilité Python 3.10."""
        def __str__(self) -> str:
            return self.value


class DydxNetwork(StrEnum):
    TESTNET = "testnet"
    MAINNET = "mainnet"


class DydxMode(StrEnum):
    LIVE = "live"
    BACKTEST = "backtest"
    REPLAY = "replay"
    TEST_FIXTURE = "test_fixture"


INDEXER_REST_ENDPOINTS = {
    DydxNetwork.TESTNET: "https://indexer.v4testnet.dydx.exchange",
    DydxNetwork.MAINNET: "https://indexer.dydx.trade",
}

INDEXER_WS_ENDPOINTS = {
    DydxNetwork.TESTNET: "wss://indexer.v4testnet.dydx.exchange/v4/ws",
    DydxNetwork.MAINNET: "wss://indexer.dydx.trade/v4/ws",
}

DEFAULT_MARKET_WHITELIST = {
    "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD",
    "SUI-USD", "XRP-USD", "LTC-USD", "BNB-USD", "NEAR-USD", "APT-USD",
    "ARB-USD", "OP-USD", "TIA-USD", "WLD-USD", "DOGE-USD",
    "HYPE-USD", "TAO-USD", "SEI-USD", "HBAR-USD", "MORPHO-USD",
    "ZEC-USD", "VVV-USD", "MEGA-USD", "LIT-USD",
}

DEFAULT_MARKET_BLACKLIST: set[str] = {"XYZ:CL"}


@dataclass
class DydxV4Config:
    enabled: bool = False
    network: DydxNetwork = DydxNetwork.MAINNET
    require_testnet: bool = False
    read_only: bool = True
    paper_only: bool = True
    allow_trading: bool = False
    allow_private_key: bool = False
    allow_node_private_api: bool = False

    max_signal_age_ms: int = 30_000
    hard_max_signal_age_ms: int = 30_000
    min_edge_bps: float = 3.0
    edge_safety_multiplier: float = 1.0

    starting_balance_usdc: float = 1000.0
    max_open_paper_trades: int = 25
    max_position_pct: float = 0.12
    max_total_exposure_pct: float = 0.95
    dynamic_sizing_enabled: bool = True
    paper_notional_min_usdc: float = 20.0
    paper_notional_base_usdc: float = 75.0
    paper_notional_max_usdc: float = 100.0
    dynamic_sizing_edge_full_bps: float = 25.0
    dynamic_sizing_atr_high_pct: float = 0.03
    dynamic_sizing_loss_penalty: float = 0.25

    # Session performance guard: PAPER-only memory of markets/sides that just lost.
    # It avoids repeatedly re-entering the same bad context unless the edge improves.
    market_side_performance_guard_enabled: bool = True
    market_side_loss_cooldown_seconds: float = 180.0
    market_side_max_consecutive_losses: int = 2
    market_side_min_edge_after_loss_bps: float = 12.0
    market_side_size_penalty_after_loss: float = 0.50
    market_side_history_bootstrap_trades: int = 300

    taker_fee_bps: float = 5.0
    maker_fee_bps: float = 2.0
    estimated_spread_bps: float = 3.0
    estimated_slippage_bps: float = 1.5
    estimated_latency_bps: float = 2.0
    copy_degradation_bps: float = 5.0

    market_whitelist: set[str] = field(default_factory=lambda: set(DEFAULT_MARKET_WHITELIST))
    market_blacklist: set[str] = field(default_factory=lambda: set(DEFAULT_MARKET_BLACKLIST))

    rest_timeout_s: float = 8.0
    rest_max_retries: int = 2
    rest_backoff_base_s: float = 0.5
    rest_rate_limit_rps: float = 5.0
    health_check_retries: int = 0
    ws_ping_interval_s: float = 30.0
    ws_reconnect_delay_s: float = 5.0
    ws_max_reconnect_attempts: int = 10

    db_path: str = "data/dydx_v4.sqlite3"
    decision_log_enabled: bool = True
    decision_log_path: str = "logs/structured/decisions.jsonl"

    mode: DydxMode = DydxMode.LIVE
    demo_mode: bool = False
    allow_demo_fallback: bool = False

    consensus_required: bool = True
    consensus_min_wallets: int = 2
    consensus_window_ms: int = 3 * 60 * 1000
    consensus_recency_bonus_window_ms: int = 30_000
    consensus_recency_edge_multiplier: float = 1.08
    precision_cluster_gate_enabled: bool = True
    precision_cluster_wallet_threshold: int = 2
    precision_cluster_max_spread_ms: int = 350
    precision_cluster_max_last_age_ms: int = 350
    precision_cluster_min_strength: float = 0.88

    atr_period: int = 14
    atr_stop_mult: float = 1.0
    atr_take_profit_mult: float = 3.0
    atr_trail_mult: float = 0.8
    max_holding_hours: float = 48.0
    partial_tp_enabled: bool = True
    partial_tp_fraction: float = 0.50
    partial_tp2_multiplier: float = 2.0
    funding_adverse_threshold_hourly: float = 0.0001
    breakeven_stop_enabled: bool = True
    breakeven_trigger_atr_mult: float = 1.5
    breakeven_offset_atr_mult: float = 0.1

    use_orderbook_fills: bool = True
    max_book_participation_pct: float = 0.10
    fill_latency_extra_bps: float = 2.0

    trend_filter_enabled: bool = True
    regime_detector_enabled: bool = True
    market_context_ttl_s: float = 20.0
    trend_min_move_pct: float = 0.0015
    choppy_efficiency_max: float = 0.18
    choppy_atr_pct_min: float = 0.001
    volume_spike_enabled: bool = True
    volume_spike_zscore_min: float = 2.0
    volume_spike_imbalance_min: float = 0.62
    volume_spike_edge_multiplier: float = 1.08
    correlation_gate_enabled: bool = True
    max_correlated_same_side: int = 5
    confluence_enabled: bool = True
    confluence_window_ms: int = 45_000
    confluence_edge_multiplier: float = 1.12
    funding_edge_enabled: bool = True
    funding_edge_horizon_hours: float = 1.0

    fast_scanner_enabled: bool = True
    fast_scanner_hot_capacity: int = 1000
    risk_policy_enabled: bool = True
    min_hold_seconds: float = 20.0
    reopen_cooldown_seconds: float = 8.0
    circuit_max_consecutive_losses: int = 6
    circuit_max_daily_drawdown_pct: float = 0.05
    scalper_min_hold_seconds: float = 45.0
    adaptive_exits_enabled: bool = True
    max_decision_wallets: int = 3000
    fill_realism_mode: str = "orderbook_real"

    require_proven_leaders: bool = False
    min_leader_winrate: float = 0.45
    min_leader_profit_factor: float = 1.3
    min_leader_trades: int = 15
    min_proven_in_consensus: int = 1

    full_node_stream_enabled: bool = False
    full_node_stream_endpoint: str = "127.0.0.1:9090"
    stream_consensus_min_wallets: int = 3
    stream_window_ms: int = 12_000
    market_flow_enabled: bool = True
    allow_market_flow_solo_entries: bool = False
    # Public market-flow alone is normally context only. This separate switch
    # permits tiny PAPER-ONLY opportunities when the public flow is very fresh,
    # high-volume, and strongly imbalanced. It never enables real execution.
    allow_strong_public_flow_paper_entries: bool = True
    strong_public_flow_min_volume_usdc: float = 40_000.0
    strong_public_flow_min_trades: int = 8
    strong_public_flow_min_imbalance: float = 0.72
    strong_public_flow_max_age_ms: int = 4_000
    strong_public_flow_notional_factor: float = 0.35
    market_flow_min_volume_usdc: float = 7_500.0
    market_flow_min_imbalance: float = 0.60
    rest_poll_cap: int = 250
    max_spread_bps: float = 45.0
    flow_min_trades: int = 3
    flow_consensus_min_wallets: int = 1

    def __post_init__(self) -> None:
        self._assert_safety()

    def _assert_safety(self) -> None:
        if self.allow_trading:
            raise ValueError("SAFETY VIOLATION: allow_trading=True est interdit. Ce module est READ-ONLY / PAPER-ONLY uniquement.")
        if self.allow_private_key:
            raise ValueError("SAFETY VIOLATION: allow_private_key=True est interdit. Aucune clé privée, seed ou mnemonic ne doit être utilisé.")
        if not self.paper_only:
            raise ValueError("SAFETY VIOLATION: paper_only=False est interdit. Seuls les paper trades sont autorisés.")
        if not self.read_only:
            raise ValueError("SAFETY VIOLATION: read_only=False est interdit.")
        if self.require_testnet and self.network == DydxNetwork.MAINNET:
            raise ValueError("SAFETY VIOLATION: require_testnet=True mais network=mainnet. Mettre require_testnet=False explicitement pour utiliser mainnet (READ-ONLY seulement).")

    @property
    def indexer_rest_url(self) -> str:
        return INDEXER_REST_ENDPOINTS[self.network]

    @property
    def indexer_ws_url(self) -> str:
        return INDEXER_WS_ENDPOINTS[self.network]

    @property
    def total_round_trip_cost_bps(self) -> float:
        return (
            self.taker_fee_bps * 2
            + self.estimated_spread_bps
            + self.estimated_slippage_bps
            + self.estimated_latency_bps
            + self.copy_degradation_bps
        )


def load_config_from_env(base: DydxV4Config | None = None) -> DydxV4Config:
    cfg = base or DydxV4Config()

    def _bool(key: str, default: bool) -> bool:
        v = os.environ.get(key, "").lower()
        if v in ("1", "true", "yes"):
            return True
        if v in ("0", "false", "no"):
            return False
        return default

    def _int(key: str, default: int) -> int:
        try:
            return int(os.environ.get(key, str(default)))
        except (ValueError, TypeError):
            return default

    def _float(key: str, default: float) -> float:
        try:
            return float(os.environ.get(key, str(default)))
        except (ValueError, TypeError):
            return default

    net_str = os.environ.get("DYDX_NETWORK", cfg.network.value).lower()
    network = DydxNetwork.TESTNET if net_str == "testnet" else DydxNetwork.MAINNET
    demo_mode = False

    loaded = DydxV4Config(
        enabled=_bool("DYDX_ENABLED", cfg.enabled),
        network=network,
        require_testnet=False,
        read_only=True,
        paper_only=True,
        allow_trading=False,
        allow_private_key=False,
        allow_node_private_api=False,
        max_signal_age_ms=_int("DYDX_MAX_SIGNAL_AGE_MS", cfg.max_signal_age_ms),
        hard_max_signal_age_ms=_int("DYDX_HARD_MAX_SIGNAL_AGE_MS", cfg.hard_max_signal_age_ms),
        min_edge_bps=_float("DYDX_MIN_EDGE_BPS", cfg.min_edge_bps),
        edge_safety_multiplier=_float("DYDX_EDGE_SAFETY_MULTIPLIER", cfg.edge_safety_multiplier),
        starting_balance_usdc=_float("DYDX_STARTING_BALANCE_USDC", cfg.starting_balance_usdc),
        max_open_paper_trades=_int("DYDX_MAX_OPEN_PAPER_TRADES", cfg.max_open_paper_trades),
        max_position_pct=_float("DYDX_MAX_POSITION_PCT", cfg.max_position_pct),
        max_total_exposure_pct=_float("DYDX_MAX_TOTAL_EXPOSURE_PCT", cfg.max_total_exposure_pct),
        dynamic_sizing_enabled=_bool("DYDX_DYNAMIC_SIZING", cfg.dynamic_sizing_enabled),
        paper_notional_min_usdc=_float("DYDX_PAPER_NOTIONAL_MIN_USDC", cfg.paper_notional_min_usdc),
        paper_notional_base_usdc=_float("DYDX_PAPER_NOTIONAL_BASE_USDC", cfg.paper_notional_base_usdc),
        paper_notional_max_usdc=_float("DYDX_PAPER_NOTIONAL_MAX_USDC", cfg.paper_notional_max_usdc),
        dynamic_sizing_edge_full_bps=_float("DYDX_DYNAMIC_SIZING_EDGE_FULL_BPS", cfg.dynamic_sizing_edge_full_bps),
        dynamic_sizing_atr_high_pct=_float("DYDX_DYNAMIC_SIZING_ATR_HIGH_PCT", cfg.dynamic_sizing_atr_high_pct),
        dynamic_sizing_loss_penalty=_float("DYDX_DYNAMIC_SIZING_LOSS_PENALTY", cfg.dynamic_sizing_loss_penalty),
        market_side_performance_guard_enabled=_bool("DYDX_MARKET_SIDE_PERF_GUARD", cfg.market_side_performance_guard_enabled),
        market_side_loss_cooldown_seconds=_float("DYDX_MARKET_SIDE_LOSS_COOLDOWN_SECONDS", cfg.market_side_loss_cooldown_seconds),
        market_side_max_consecutive_losses=_int("DYDX_MARKET_SIDE_MAX_CONSECUTIVE_LOSSES", cfg.market_side_max_consecutive_losses),
        market_side_min_edge_after_loss_bps=_float("DYDX_MARKET_SIDE_MIN_EDGE_AFTER_LOSS_BPS", cfg.market_side_min_edge_after_loss_bps),
        market_side_size_penalty_after_loss=_float("DYDX_MARKET_SIDE_SIZE_PENALTY_AFTER_LOSS", cfg.market_side_size_penalty_after_loss),
        market_side_history_bootstrap_trades=_int("DYDX_MARKET_SIDE_HISTORY_BOOTSTRAP_TRADES", cfg.market_side_history_bootstrap_trades),
        db_path=os.environ.get("DYDX_DB_PATH", cfg.db_path),
        decision_log_enabled=_bool("DYDX_DECISION_LOG", cfg.decision_log_enabled),
        decision_log_path=os.environ.get("DYDX_DECISION_LOG_PATH", cfg.decision_log_path),
        partial_tp_enabled=_bool("DYDX_PARTIAL_TP", cfg.partial_tp_enabled),
        partial_tp_fraction=_float("DYDX_PARTIAL_TP_FRACTION", cfg.partial_tp_fraction),
        partial_tp2_multiplier=_float("DYDX_PARTIAL_TP2_MULTIPLIER", cfg.partial_tp2_multiplier),
        demo_mode=demo_mode,
        allow_demo_fallback=False,
        consensus_required=_bool("DYDX_CONSENSUS_REQUIRED", cfg.consensus_required),
        consensus_min_wallets=_int("DYDX_CONSENSUS_MIN_WALLETS", cfg.consensus_min_wallets),
        consensus_window_ms=_int("DYDX_CONSENSUS_WINDOW_MS", cfg.consensus_window_ms),
        consensus_recency_bonus_window_ms=_int("DYDX_CONSENSUS_RECENCY_BONUS_WINDOW_MS", cfg.consensus_recency_bonus_window_ms),
        consensus_recency_edge_multiplier=_float("DYDX_CONSENSUS_RECENCY_EDGE_MULTIPLIER", cfg.consensus_recency_edge_multiplier),
        precision_cluster_gate_enabled=_bool("DYDX_PRECISION_CLUSTER_GATE", cfg.precision_cluster_gate_enabled),
        precision_cluster_wallet_threshold=_int("DYDX_PRECISION_CLUSTER_WALLET_THRESHOLD", cfg.precision_cluster_wallet_threshold),
        precision_cluster_max_spread_ms=_int("DYDX_PRECISION_CLUSTER_MAX_SPREAD_MS", cfg.precision_cluster_max_spread_ms),
        precision_cluster_max_last_age_ms=_int("DYDX_PRECISION_CLUSTER_MAX_LAST_AGE_MS", cfg.precision_cluster_max_last_age_ms),
        precision_cluster_min_strength=_float("DYDX_PRECISION_CLUSTER_MIN_STRENGTH", cfg.precision_cluster_min_strength),
        fast_scanner_enabled=_bool("DYDX_FAST_SCANNER", cfg.fast_scanner_enabled),
        fast_scanner_hot_capacity=_int("DYDX_FAST_SCANNER_HOT_CAPACITY", cfg.fast_scanner_hot_capacity),
        risk_policy_enabled=_bool("DYDX_RISK_POLICY", cfg.risk_policy_enabled),
        min_hold_seconds=_float("DYDX_MIN_HOLD_SECONDS", cfg.min_hold_seconds),
        reopen_cooldown_seconds=_float("DYDX_REOPEN_COOLDOWN_SECONDS", cfg.reopen_cooldown_seconds),
        circuit_max_consecutive_losses=_int("DYDX_CIRCUIT_MAX_CONSECUTIVE_LOSSES", cfg.circuit_max_consecutive_losses),
        circuit_max_daily_drawdown_pct=_float("DYDX_CIRCUIT_MAX_DAILY_DD_PCT", cfg.circuit_max_daily_drawdown_pct),
        scalper_min_hold_seconds=_float("DYDX_SCALPER_MIN_HOLD_SECONDS", cfg.scalper_min_hold_seconds),
        adaptive_exits_enabled=_bool("DYDX_ADAPTIVE_EXITS", cfg.adaptive_exits_enabled),
        trend_filter_enabled=_bool("DYDX_TREND_FILTER", cfg.trend_filter_enabled),
        regime_detector_enabled=_bool("DYDX_REGIME_DETECTOR", cfg.regime_detector_enabled),
        market_context_ttl_s=_float("DYDX_MARKET_CONTEXT_TTL_S", cfg.market_context_ttl_s),
        trend_min_move_pct=_float("DYDX_TREND_MIN_MOVE_PCT", cfg.trend_min_move_pct),
        choppy_efficiency_max=_float("DYDX_CHOPPY_EFFICIENCY_MAX", cfg.choppy_efficiency_max),
        choppy_atr_pct_min=_float("DYDX_CHOPPY_ATR_PCT_MIN", cfg.choppy_atr_pct_min),
        volume_spike_enabled=_bool("DYDX_VOLUME_SPIKE", cfg.volume_spike_enabled),
        volume_spike_zscore_min=_float("DYDX_VOLUME_SPIKE_ZSCORE_MIN", cfg.volume_spike_zscore_min),
        volume_spike_imbalance_min=_float("DYDX_VOLUME_SPIKE_IMBALANCE_MIN", cfg.volume_spike_imbalance_min),
        volume_spike_edge_multiplier=_float("DYDX_VOLUME_SPIKE_EDGE_MULTIPLIER", cfg.volume_spike_edge_multiplier),
        correlation_gate_enabled=_bool("DYDX_CORRELATION_GATE", cfg.correlation_gate_enabled),
        max_correlated_same_side=_int("DYDX_MAX_CORRELATED_SAME_SIDE", cfg.max_correlated_same_side),
        confluence_enabled=_bool("DYDX_CONFLUENCE", cfg.confluence_enabled),
        confluence_window_ms=_int("DYDX_CONFLUENCE_WINDOW_MS", cfg.confluence_window_ms),
        confluence_edge_multiplier=_float("DYDX_CONFLUENCE_EDGE_MULTIPLIER", cfg.confluence_edge_multiplier),
        funding_edge_enabled=_bool("DYDX_FUNDING_EDGE", cfg.funding_edge_enabled),
        funding_edge_horizon_hours=_float("DYDX_FUNDING_EDGE_HORIZON_HOURS", cfg.funding_edge_horizon_hours),
        max_decision_wallets=_int("DYDX_MAX_DECISION_WALLETS", cfg.max_decision_wallets),
        fill_realism_mode=os.environ.get("DYDX_FILL_REALISM", cfg.fill_realism_mode),
        require_proven_leaders=_bool("DYDX_REQUIRE_PROVEN_LEADERS", cfg.require_proven_leaders),
        min_leader_winrate=_float("DYDX_MIN_LEADER_WINRATE", cfg.min_leader_winrate),
        min_leader_profit_factor=_float("DYDX_MIN_LEADER_PF", cfg.min_leader_profit_factor),
        min_leader_trades=_int("DYDX_MIN_LEADER_TRADES", cfg.min_leader_trades),
        min_proven_in_consensus=_int("DYDX_MIN_PROVEN_IN_CONSENSUS", cfg.min_proven_in_consensus),
        full_node_stream_enabled=_bool("DYDX_FULL_NODE_STREAM", cfg.full_node_stream_enabled),
        full_node_stream_endpoint=os.environ.get("DYDX_FULL_NODE_STREAM_ENDPOINT", cfg.full_node_stream_endpoint),
        stream_consensus_min_wallets=_int("DYDX_STREAM_CONSENSUS_MIN_WALLETS", cfg.stream_consensus_min_wallets),
        stream_window_ms=_int("DYDX_STREAM_WINDOW_MS", cfg.stream_window_ms),
        market_flow_enabled=_bool("DYDX_MARKET_FLOW", cfg.market_flow_enabled),
        allow_market_flow_solo_entries=_bool("DYDX_ALLOW_MARKET_FLOW_SOLO", cfg.allow_market_flow_solo_entries),
        allow_strong_public_flow_paper_entries=_bool("DYDX_ALLOW_STRONG_PUBLIC_FLOW_PAPER", cfg.allow_strong_public_flow_paper_entries),
        strong_public_flow_min_volume_usdc=_float("DYDX_STRONG_PUBLIC_FLOW_MIN_VOLUME", cfg.strong_public_flow_min_volume_usdc),
        strong_public_flow_min_trades=_int("DYDX_STRONG_PUBLIC_FLOW_MIN_TRADES", cfg.strong_public_flow_min_trades),
        strong_public_flow_min_imbalance=_float("DYDX_STRONG_PUBLIC_FLOW_MIN_IMBALANCE", cfg.strong_public_flow_min_imbalance),
        strong_public_flow_max_age_ms=_int("DYDX_STRONG_PUBLIC_FLOW_MAX_AGE_MS", cfg.strong_public_flow_max_age_ms),
        strong_public_flow_notional_factor=_float("DYDX_STRONG_PUBLIC_FLOW_NOTIONAL_FACTOR", cfg.strong_public_flow_notional_factor),
        market_flow_min_volume_usdc=_float("DYDX_MARKET_FLOW_MIN_VOLUME", cfg.market_flow_min_volume_usdc),
        market_flow_min_imbalance=_float("DYDX_MARKET_FLOW_MIN_IMBALANCE", cfg.market_flow_min_imbalance),
        rest_poll_cap=_int("DYDX_REST_POLL_CAP", cfg.rest_poll_cap),
        max_spread_bps=_float("DYDX_MAX_SPREAD_BPS", cfg.max_spread_bps),
        flow_min_trades=_int("DYDX_FLOW_MIN_TRADES", cfg.flow_min_trades),
        flow_consensus_min_wallets=_int("DYDX_FLOW_CONSENSUS_MIN_WALLETS", cfg.flow_consensus_min_wallets),
        breakeven_stop_enabled=_bool("DYDX_BREAKEVEN_STOP", cfg.breakeven_stop_enabled),
        breakeven_trigger_atr_mult=_float("DYDX_BREAKEVEN_TRIGGER_ATR_MULT", cfg.breakeven_trigger_atr_mult),
        breakeven_offset_atr_mult=_float("DYDX_BREAKEVEN_OFFSET_ATR_MULT", cfg.breakeven_offset_atr_mult),
    )
    if _bool("DYDX_OPPORTUNITY_CALIBRATION", False):
        from hyper_smart_observer.dydx_v4.opportunity_calibration import apply_opportunity_calibration
        loaded = apply_opportunity_calibration(loaded)
    return loaded


DEFAULT_CONFIG = DydxV4Config()
