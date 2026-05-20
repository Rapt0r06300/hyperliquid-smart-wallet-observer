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
    min_edge_required_bps: float = 8.0
    min_wallet_score: float = 75.0
    min_signal_score: float = 80.0
    max_testnet_trade_size_usdc: float = 5.0
    kill_switch_active: bool = False


class Settings(BaseModel):
    environment: ExecutionEnvironment = ExecutionEnvironment.PAPER
    database_url: str = "sqlite:///./logs/hl_observer.sqlite3"
    logs_dir: Path = Path("./logs")
    log_level: str = "INFO"
    hyperliquid: HyperliquidSettings = Field(default_factory=HyperliquidSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)

    @property
    def read_only_or_paper(self) -> bool:
        return self.environment in {
            ExecutionEnvironment.READ_ONLY,
            ExecutionEnvironment.PAPER,
        }
