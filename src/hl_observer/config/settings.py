from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class ExecutionEnvironment(StrEnum):
    READ_ONLY = "read_only"
    PAPER = "paper"
    TESTNET = "testnet"
    MAINNET = "mainnet"


class HyperliquidSettings(BaseModel):
    info_base_url: str = "https://api.hyperliquid.xyz/info"
    testnet_info_base_url: str = "https://api.hyperliquid-testnet.xyz/info"
    ws_base_url: str = "wss://api.hyperliquid.xyz/ws"
    testnet_ws_base_url: str = "wss://api.hyperliquid-testnet.xyz/ws"
    timeout_seconds: float = 10.0
    max_retries: int = 3
    backoff_base_seconds: float = 0.25


class CollectionSettings(BaseModel):
    default_coins: list[str] = Field(default_factory=lambda: ["BTC", "ETH"])
    request_timeout_seconds: float = 10.0
    retry_count: int = 2
    retry_backoff_seconds: float = 1.0
    store_raw_events: bool = True
    store_response_hash: bool = True
    max_user_fills_pages: int = 5
    user_fills_page_window_ms: int = 86_400_000


class WalletDiscoverySettings(BaseModel):
    enabled: bool = True
    auto_discover_on_startup: bool = True
    sources: list[str] = Field(
        default_factory=lambda: [
            "hyperliquid_leaderboard",
            "hyperliquid_explorer",
            "local_db",
            "local_config",
            "coinglass_whale_tracker",
            "hyperdash",
            "hypertracker",
        ]
    )
    max_sources_per_run: int = 5
    max_candidates_per_source: int = 50
    max_total_candidates: int = 200
    max_wallets_to_backfill: int = 10
    min_discovery_score: float = 55.0
    require_positive_pnl: bool = True
    require_positive_roi: bool = False
    allow_incomplete_external_metrics: bool = True
    revalidate_with_hyperliquid_info: bool = True
    backfill_selected_after_discovery: bool = True
    backfill_days: int = 7
    cooldown_seconds: int = 300
    source_timeout_seconds: float = 15.0
    external_sources_enabled: bool = True
    store_raw_discovery_payloads: bool = True


class WalletBootstrapSettings(BaseModel):
    enabled: bool = True
    run_on_startup: bool = True
    target_wallets: int = 500
    primary_source: str = "all"
    min_wallets_to_start: int = 25
    max_candidates_total: int = 3000
    max_candidates_per_source: int = 1000
    max_sources_per_run: int = 6
    min_bootstrap_score: float = 50.0
    require_positive_pnl: bool = True
    require_positive_roi: bool = False
    allow_missing_roi: bool = True
    allow_missing_pnl_if_revalidates: bool = True
    reject_truncated_addresses: bool = True
    revalidate_with_hyperliquid_info: bool = True
    revalidate_limit: int = 500
    backfill_selected: bool = True
    backfill_limit_per_run: int = 50
    backfill_days: int = 7
    cooldown_seconds: int = 3600
    store_raw_source_payloads: bool = True
    export_top500_json: bool = True
    export_top500_csv: bool = True
    refresh_existing_wallets: bool = True
    include_altcoins: bool = True
    group_by_coin: bool = True
    source_timeout_seconds: float = 15.0
    source_retry_count: int = 2


class WalletScannerSettings(BaseModel):
    enabled: bool = True
    scan_max_wallets_per_run: int = 500
    scan_batch_size: int = 25
    scan_max_parallelism: int = 1
    scan_retry_count: int = 2
    scan_retry_backoff_seconds: int = 30
    scan_cooldown_seconds: int = 900
    scan_resume_unfinished: bool = True
    scan_prioritize_leaderboard: bool = True
    scan_prioritize_positive_pnl: bool = True
    scan_prioritize_positive_roi: bool = True
    scan_prioritize_multi_source_wallets: bool = True
    scan_store_progress: bool = True
    scan_stop_on_kill_switch: bool = True


class MarketUniverseSettings(BaseModel):
    enabled: bool = True
    discover_from_meta: bool = True
    discover_from_all_mids: bool = True
    include_spot: bool = False
    default_fallback_coins: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "HYPE"])
    excluded_coins: list[str] = Field(default_factory=list)
    max_coins_per_scan: int = 50
    max_l2book_coins_per_scan: int = 15
    max_candle_coins_per_scan: int = 20
    min_mid_price_usdc: float = 0.0
    min_orderbook_depth_usdc: float = 5000.0
    max_spread_bps: float = 25.0
    prefer_wallet_active_coins: bool = True
    prefer_positive_pnl_coins: bool = True
    prefer_high_volume_coins: bool = True
    prefer_major_coins: bool = True
    altcoins_enabled: bool = True


class WalletAnalysisSettings(BaseModel):
    analyze_all_coins: bool = True
    per_coin_metrics: bool = True
    include_altcoins: bool = True
    ignore_unknown_coins: bool = False
    min_coin_fills_for_score: int = 3


class AdaptiveRiskFilterSettings(BaseModel):
    enabled: bool = True
    default_decision: str = "observe_only"
    max_signal_age_ms: int = 3000
    max_price_moved_bps: float = 30.0
    max_spread_bps: float = 20.0
    max_estimated_slippage_bps: float = 25.0
    min_orderbook_depth_usdc: float = 10000.0
    min_wallet_score: float = 70.0
    min_wallet_coin_score: float = 70.0
    min_opening_pattern_score: float = 65.0
    min_pattern_sample_size: int = 20
    reduce_size_if_altcoin: bool = True
    reduce_size_if_high_volatility: bool = True
    block_if_wallet_reducing: bool = True
    block_if_wallet_closing: bool = True
    block_if_dca_toxic: bool = True
    block_if_data_stale: bool = True
    paper_max_size_usdc: float = 10.0
    paper_tiny_size_usdc: float = 1.0
    paper_small_size_usdc: float = 3.0
    paper_normal_size_usdc: float = 5.0
    max_daily_paper_loss_usdc: float = 10.0
    max_coin_exposure_usdc: float = 20.0
    max_wallet_exposure_usdc: float = 20.0


class ExecutionSettings(BaseModel):
    enable_mainnet_execution: bool = False
    enable_testnet_execution: bool = False
    require_confirm_testnet_only: bool = True
    require_cloid: bool = True
    require_schedule_cancel: bool = True
    require_reduce_only_exits: bool = True


class RiskSettings(BaseModel):
    max_signal_age_ms: int = 3500
    max_spread_bps: float = 6.0
    max_slippage_bps: float = 10.0
    min_orderbook_depth_usdc: float = 5000.0
    max_liquidity_penalty_bps: float = 50.0
    max_total_costs_bps: float = 100.0
    min_edge_required_bps: float = 8.0
    min_wallet_score: float = 75.0
    min_signal_score: float = 80.0
    min_gain_assurance_score: float = 50.0
    edge_freshness_half_life_ms: float = 3500.0
    edge_volatility_bps_per_sec: float = 0.2
    edge_crowding_threshold: int = 3
    edge_crowding_penalty_per_leader_bps: float = 3.0
    max_testnet_trade_size_usdc: float = 5.0
    kill_switch_active: bool = False


class CopyTradingSettings(BaseModel):
    enabled: bool = True
    default_interval_seconds: int = 300
    top_leaders: int = 50
    min_history_days: int = 7
    min_copy_leader_score: float = 60.0
    max_drawdown_pct: float = 35.0
    min_consistency_score: float = 55.0
    max_pnl_concentration: float = 0.65
    require_positive_pnl: bool = True
    require_positive_roi: bool = False
    mode_default: str = "PAPER_MOCK_USDC"
    dry_run_default: bool = True


class Settings(BaseModel):
    environment: ExecutionEnvironment = ExecutionEnvironment.PAPER
    database_url: str = "sqlite:///./data/hl_observer.sqlite3"
    logs_dir: Path = Path("./logs")
    log_level: str = "INFO"
    hyperliquid: HyperliquidSettings = Field(default_factory=HyperliquidSettings)
    collection: CollectionSettings = Field(default_factory=CollectionSettings)
    wallet_discovery: WalletDiscoverySettings = Field(default_factory=WalletDiscoverySettings)
    wallet_bootstrap: WalletBootstrapSettings = Field(default_factory=WalletBootstrapSettings)
    wallet_scanner: WalletScannerSettings = Field(default_factory=WalletScannerSettings)
    market_universe: MarketUniverseSettings = Field(default_factory=MarketUniverseSettings)
    wallet_analysis: WalletAnalysisSettings = Field(default_factory=WalletAnalysisSettings)
    adaptive_risk_filter: AdaptiveRiskFilterSettings = Field(default_factory=AdaptiveRiskFilterSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    copy_trading: CopyTradingSettings = Field(default_factory=CopyTradingSettings)

    @property
    def read_only_or_paper(self) -> bool:
        return self.environment in {
            ExecutionEnvironment.READ_ONLY,
            ExecutionEnvironment.PAPER,
        }
