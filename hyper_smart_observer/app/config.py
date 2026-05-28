from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RuntimeMode(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    OBSERVER = "OBSERVER"
    PAPER_TRADING = "PAPER_TRADING"
    TESTNET_EXECUTION_LOCKED = "TESTNET_EXECUTION_LOCKED"


FORBIDDEN_MODE_TERMS = {
    "MAINNET",
    "LIVE",
    "REAL_MONEY",
    "PRODUCTION_TRADING",
    "FULL_LIVE",
    "AUTO_PROFIT",
    "GUARANTEED",
}


@dataclass(frozen=True)
class AppConfig:
    """Central runtime configuration with safe defaults."""

    mode: str = RuntimeMode.RESEARCH_ONLY.value
    database_path: Path = Path("data/hypersmart_observer.sqlite3")
    log_level: str = "INFO"
    execution_enabled: bool = False
    testnet_execution_enabled: bool = False
    confirm_testnet_only: bool = False
    allow_mainnet: bool = False
    hyperliquid_info_base_url: str = "https://api.hyperliquid-testnet.xyz"
    hyperliquid_ws_base_url: str = "wss://api.hyperliquid-testnet.xyz/ws"
    sensitive_key_material: str | None = None
    http_timeout_seconds: float = 15.0
    http_max_retries: int = 2
    info_page_limit: int = 500
    info_time_range_page_limit: int = 500
    info_max_pages_per_wallet: int = 5
    max_pages_per_wallet: int = 5
    max_fills_per_run: int = 10_000
    user_fills_recent_limit: int = 2_000
    user_fills_by_time_max_recent: int = 10_000
    rest_weight_limit_per_minute: int = 1_200
    info_weight_extra_item_bucket_size: int = 20
    info_min_request_interval_ms: int = 250
    enable_network_reads: bool = False
    min_fills_to_score: int = 30
    min_history_days_to_score: float = 7.0
    min_closed_pnl_points: int = 10
    score_require_net_pnl: bool = True
    score_max_lookback_days: int = 90
    score_recency_half_life_days: float = 14.0
    score_min_confidence: float = 0.60
    score_store_rejected: bool = True
    enable_paper_trading: bool = True
    paper_starting_equity: float = 1000.0
    paper_max_position_notional: float = 50.0
    paper_max_total_exposure: float = 200.0
    paper_max_open_trades: int = 3
    paper_max_risk_per_trade_pct: float = 1.0
    paper_max_drawdown_stop_pct: float = 10.0
    paper_fee_rate_bps: float = 5.0
    paper_spread_bps: float = 2.0
    paper_slippage_bps: float = 5.0
    paper_latency_ms: int = 500
    paper_min_wallet_confidence: float = 0.60
    paper_min_sample_quality: float = 0.60
    paper_max_drawdown_allowed: float = 0.25
    paper_require_scored_wallet: bool = True
    paper_store_refusals: bool = True
    runtime_root: Path = Path(".")
    dashboard_dir: Path = Path("data/dashboard")
    reports_dir: Path = Path("data/reports")
    archive_output_dir: Path = Path("data/archives")
    explorer_observer_enabled: bool = False
    ws_monitor_enabled: bool = False
    ws_max_connections: int = 10
    ws_max_new_connections_per_min: int = 30
    ws_max_user_subscriptions: int = 10
    ws_max_subscriptions: int = 1000
    explorer_weight: int = 40
    copy_poll_interval_seconds: int = 300
    copy_min_edge_required_bps: float = 8.0
    copy_max_signal_age_ms: int = 300_000
    copy_max_degradation_bps: float = 40.0
    copy_leaderboard_target_count: int = 5
    copy_max_leaders_per_run: int = 3
    copy_min_history_days: float = 7.0
    copy_min_closed_pnl_points: int = 10

    @property
    def runtime_mode(self) -> RuntimeMode:
        return RuntimeMode(self.mode)


def load_config(env_file: str | Path = ".env") -> AppConfig:
    """Load config from environment plus an optional .env file.

    The parser is intentionally small and conservative; process environment
    values win over .env values.
    """

    values = _read_env_file(Path(env_file))
    merged = {**values, **os.environ}
    return AppConfig(
        mode=merged.get("HYPERSMART_MODE", RuntimeMode.RESEARCH_ONLY.value).strip().upper(),
        database_path=Path(
            merged.get("HYPERSMART_DATABASE_PATH", "data/hypersmart_observer.sqlite3")
        ),
        log_level=merged.get("HYPERSMART_LOG_LEVEL", "INFO").strip().upper(),
        execution_enabled=_as_bool(merged.get("HYPERSMART_ENABLE_EXECUTION", "false")),
        testnet_execution_enabled=_as_bool(
            merged.get("HYPERSMART_ENABLE_TESTNET_EXECUTION", "false")
        ),
        confirm_testnet_only=_as_bool(
            merged.get("HYPERSMART_CONFIRM_TESTNET_ONLY", "false")
        ),
        allow_mainnet=_as_bool(merged.get("HYPERSMART_ALLOW_MAINNET", "false")),
        hyperliquid_info_base_url=merged.get(
            "HYPERSMART_HYPERLIQUID_INFO_BASE_URL",
            "https://api.hyperliquid-testnet.xyz",
        ),
        hyperliquid_ws_base_url=merged.get(
            "HYPERSMART_HYPERLIQUID_WS_BASE_URL",
            "wss://api.hyperliquid-testnet.xyz/ws",
        ),
        sensitive_key_material=_blank_to_none(merged.get("HYPERSMART_PRIVATE_KEY")),
        http_timeout_seconds=_as_float(merged.get("HYPERSMART_HTTP_TIMEOUT_SECONDS", "15")),
        http_max_retries=_as_int(merged.get("HYPERSMART_HTTP_MAX_RETRIES", "2")),
        info_page_limit=_as_int(merged.get("HYPERSMART_INFO_PAGE_LIMIT", "500")),
        info_time_range_page_limit=_as_int(
            merged.get("HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT", "500")
        ),
        info_max_pages_per_wallet=_as_int(
            merged.get("HYPERSMART_INFO_MAX_PAGES_PER_WALLET", "5")
        ),
        max_pages_per_wallet=_as_int(merged.get("HYPERSMART_MAX_PAGES_PER_WALLET", "5")),
        max_fills_per_run=_as_int(merged.get("HYPERSMART_MAX_FILLS_PER_RUN", "10000")),
        user_fills_recent_limit=_as_int(
            merged.get("HYPERSMART_USER_FILLS_RECENT_LIMIT", "2000")
        ),
        user_fills_by_time_max_recent=_as_int(
            merged.get("HYPERSMART_USER_FILLS_BY_TIME_MAX_RECENT", "10000")
        ),
        rest_weight_limit_per_minute=_as_int(
            merged.get("HYPERSMART_REST_WEIGHT_LIMIT_PER_MINUTE", "1200")
        ),
        info_weight_extra_item_bucket_size=_as_int(
            merged.get("HYPERSMART_INFO_WEIGHT_EXTRA_ITEM_BUCKET_SIZE", "20")
        ),
        info_min_request_interval_ms=_as_int(
            merged.get("HYPERSMART_INFO_MIN_REQUEST_INTERVAL_MS", "250")
        ),
        enable_network_reads=_as_bool(merged.get("HYPERSMART_ENABLE_NETWORK_READS", "false")),
        min_fills_to_score=_as_int(merged.get("HYPERSMART_MIN_FILLS_TO_SCORE", "30")),
        min_history_days_to_score=_as_float(
            merged.get("HYPERSMART_MIN_HISTORY_DAYS_TO_SCORE", "7")
        ),
        min_closed_pnl_points=_as_int(merged.get("HYPERSMART_MIN_CLOSED_PNL_POINTS", "10")),
        score_require_net_pnl=_as_bool(
            merged.get("HYPERSMART_SCORE_REQUIRE_NET_PNL", "true")
        ),
        score_max_lookback_days=_as_int(merged.get("HYPERSMART_SCORE_MAX_LOOKBACK_DAYS", "90")),
        score_recency_half_life_days=_as_float(
            merged.get("HYPERSMART_SCORE_RECENCY_HALF_LIFE_DAYS", "14")
        ),
        score_min_confidence=_as_float(merged.get("HYPERSMART_SCORE_MIN_CONFIDENCE", "0.60")),
        score_store_rejected=_as_bool(merged.get("HYPERSMART_SCORE_STORE_REJECTED", "true")),
        enable_paper_trading=_as_bool(merged.get("HYPERSMART_ENABLE_PAPER_TRADING", "true")),
        paper_starting_equity=_as_float(
            merged.get("HYPERSMART_PAPER_STARTING_EQUITY", "1000.0")
        ),
        paper_max_position_notional=_as_float(
            merged.get("HYPERSMART_PAPER_MAX_POSITION_NOTIONAL", "50.0")
        ),
        paper_max_total_exposure=_as_float(
            merged.get("HYPERSMART_PAPER_MAX_TOTAL_EXPOSURE", "200.0")
        ),
        paper_max_open_trades=_as_int(merged.get("HYPERSMART_PAPER_MAX_OPEN_TRADES", "3")),
        paper_max_risk_per_trade_pct=_as_float(
            merged.get("HYPERSMART_PAPER_MAX_RISK_PER_TRADE_PCT", "1.0")
        ),
        paper_max_drawdown_stop_pct=_as_float(
            merged.get("HYPERSMART_PAPER_MAX_DRAWDOWN_STOP_PCT", "10.0")
        ),
        paper_fee_rate_bps=_as_float(merged.get("HYPERSMART_PAPER_FEE_RATE_BPS", "5")),
        paper_spread_bps=_as_float(merged.get("HYPERSMART_PAPER_SPREAD_BPS", "2")),
        paper_slippage_bps=_as_float(merged.get("HYPERSMART_PAPER_SLIPPAGE_BPS", "5")),
        paper_latency_ms=_as_int(merged.get("HYPERSMART_PAPER_LATENCY_MS", "500")),
        paper_min_wallet_confidence=_as_float(
            merged.get("HYPERSMART_PAPER_MIN_WALLET_CONFIDENCE", "0.60")
        ),
        paper_min_sample_quality=_as_float(
            merged.get("HYPERSMART_PAPER_MIN_SAMPLE_QUALITY", "0.60")
        ),
        paper_max_drawdown_allowed=_as_float(
            merged.get("HYPERSMART_PAPER_MAX_DRAWDOWN_ALLOWED", "0.25")
        ),
        paper_require_scored_wallet=_as_bool(
            merged.get("HYPERSMART_PAPER_REQUIRE_SCORED_WALLET", "true")
        ),
        paper_store_refusals=_as_bool(
            merged.get("HYPERSMART_PAPER_STORE_REFUSALS", "true")
        ),
        runtime_root=Path(merged.get("HYPERSMART_RUNTIME_ROOT", ".")),
        dashboard_dir=Path(merged.get("HYPERSMART_DASHBOARD_DIR", "data/dashboard")),
        reports_dir=Path(merged.get("HYPERSMART_REPORTS_DIR", "data/reports")),
        archive_output_dir=Path(merged.get("HYPERSMART_ARCHIVE_OUTPUT_DIR", "data/archives")),
        explorer_observer_enabled=_as_bool(
            merged.get("HYPERSMART_EXPLORER_OBSERVER_ENABLED", "false")
        ),
        ws_monitor_enabled=_as_bool(merged.get("HYPERSMART_WS_MONITOR_ENABLED", "false")),
        ws_max_connections=_as_int(merged.get("HYPERSMART_WS_MAX_CONNECTIONS", "10")),
        ws_max_new_connections_per_min=_as_int(
            merged.get("HYPERSMART_WS_MAX_NEW_CONNECTIONS_PER_MIN", "30")
        ),
        ws_max_user_subscriptions=_as_int(
            merged.get("HYPERSMART_WS_MAX_USER_SUBSCRIPTIONS", merged.get("HYPERSMART_WS_MAX_UNIQUE_USERS", "10"))
        ),
        ws_max_subscriptions=_as_int(merged.get("HYPERSMART_WS_MAX_SUBSCRIPTIONS", "1000")),
        explorer_weight=_as_int(merged.get("HYPERSMART_EXPLORER_WEIGHT", "40")),
        copy_poll_interval_seconds=_as_int(
            merged.get("HYPERSMART_COPY_POLL_INTERVAL_SECONDS", "300")
        ),
        copy_min_edge_required_bps=_as_float(
            merged.get("HYPERSMART_COPY_MIN_EDGE_REQUIRED_BPS", "8")
        ),
        copy_max_signal_age_ms=_as_int(merged.get("HYPERSMART_COPY_MAX_SIGNAL_AGE_MS", "300000")),
        copy_max_degradation_bps=_as_float(
            merged.get("HYPERSMART_COPY_MAX_DEGRADATION_BPS", "40")
        ),
        copy_leaderboard_target_count=_as_int(
            merged.get("HYPERSMART_COPY_LEADERBOARD_TARGET_COUNT", "5")
        ),
        copy_max_leaders_per_run=_as_int(
            merged.get("HYPERSMART_COPY_MAX_LEADERS_PER_RUN", "3")
        ),
        copy_min_history_days=_as_float(merged.get("HYPERSMART_COPY_MIN_HISTORY_DAYS", "7")),
        copy_min_closed_pnl_points=_as_int(
            merged.get("HYPERSMART_COPY_MIN_CLOSED_PNL_POINTS", "10")
        ),
    )


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _as_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _blank_to_none(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return value


def _as_int(value: str | int | None) -> int:
    if isinstance(value, int):
        return value
    if value is None:
        return 0
    return int(str(value).strip())


def _as_float(value: str | float | None) -> float:
    if isinstance(value, float):
        return value
    if value is None:
        return 0.0
    return float(str(value).strip())
