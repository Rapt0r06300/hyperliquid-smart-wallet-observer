from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UiMetric(BaseModel):
    name: str
    value: int | float | str
    status: Literal["ok", "warn", "danger", "info"] = "info"


class UiEvent(BaseModel):
    event_type: str
    message: str
    level: Literal["INFO", "WARN", "RISK", "ERROR", "SECURITY"] = "INFO"
    timestamp_ms: int
    payload: dict = Field(default_factory=dict)


class UiLogLine(BaseModel):
    level: Literal["INFO", "WARN", "RISK", "ERROR", "SECURITY"] = "INFO"
    message: str
    timestamp_ms: int
    context: dict = Field(default_factory=dict)


class UiWalletRow(BaseModel):
    address: str
    label: str | None = None
    source: str | None = None
    last_seen: str | None = None
    score: float | None = None
    status: str = "unknown"
    toxicity_flags: list[str] = Field(default_factory=list)
    degradation_status: str = "unknown"


class UiSignalRow(BaseModel):
    id: str
    wallet: str | None = None
    coin: str | None = None
    side: str | None = None
    signal_type: str | None = None
    wallet_score: float | None = None
    signal_score: float | None = None
    edge_remaining_bps: float | None = None
    decision: str
    reject_reason: str | None = None
    created_at: str | None = None


class UiRiskGate(BaseModel):
    name: str
    passed: bool
    detail: str | None = None


class UiActionRequest(BaseModel):
    action: str


class UiActionResult(BaseModel):
    action: str
    allowed: bool
    success: bool
    level: Literal["INFO", "WARN", "RISK", "ERROR", "SECURITY"] = "INFO"
    message: str
    details: dict = Field(default_factory=dict)
    action_id: str | None = None
    label: str | None = None
    status: str | None = None
    started_at_ms: int | None = None
    finished_at_ms: int | None = None
    affected_counts: dict[str, int] = Field(default_factory=dict)
    next_recommended_action: str | None = None


class ActionCatalogItem(BaseModel):
    action_id: str
    label: str
    group: str
    description: str
    enabled: bool = True
    disabled_reason: str | None = None
    safety_level: str = "read_only"
    endpoint: str = "/api/actions"
    expected_result: str
    icon: str = "terminal"
    test_id: str


class VirtualPosition(BaseModel):
    position_id: str
    wallet_address: str
    coin: str
    direction: Literal["LONG", "SHORT"]
    entry_at_ms: int
    entry_price: float
    size: float
    avg_price: float
    notional_usdc: float
    fees_usdc: float
    realized_pnl_usdc: float = 0.0
    unrealized_pnl_usdc: float = 0.0
    status: str = "OPEN"
    close_reason: str | None = None
    source_delta_ids: list[str] = Field(default_factory=list)


class UiStatus(BaseModel):
    app_name: str
    version: str
    mode: str
    db_path: str
    mainnet_enabled: bool
    testnet_enabled: bool
    paper_enabled: bool
    safety_status: str
    last_collection_run: dict | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    risk_gates: list[UiRiskGate] = Field(default_factory=list)
