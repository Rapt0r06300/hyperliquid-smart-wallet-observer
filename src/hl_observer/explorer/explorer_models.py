from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from hl_observer.utils.time import now_ms


class ExplorerSourceStatus(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    IMPORT_REQUIRED = "IMPORT_REQUIRED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    NETWORK_FAILED = "NETWORK_FAILED"
    DOM_FAILED = "DOM_FAILED"
    FULL_ADDRESS_OK = "FULL_ADDRESS_OK"
    TRUNCATED_ADDRESS_REJECTED = "TRUNCATED_ADDRESS_REJECTED"
    EVENT_WITHOUT_ADDRESS = "EVENT_WITHOUT_ADDRESS"
    TX_STORED = "TX_STORED"
    CANDIDATE_CREATED = "CANDIDATE_CREATED"
    REVALIDATED_BY_INFO = "REVALIDATED_BY_INFO"


class ExplorerTransaction(BaseModel):
    tx_hash: str | None = None
    block: int | None = None
    timestamp_ms: int | None = None
    action_type: str | None = None
    wallet_address: str | None = None
    address_short: str | None = None
    coin: str | None = None
    side: str | None = None
    size: float | None = None
    price: float | None = None
    value_usdc: float | None = None
    raw_payload_hash: str | None = None
    source_url: str | None = None
    confidence_score: float = 0.0
    validation_status: ExplorerSourceStatus = ExplorerSourceStatus.EVENT_WITHOUT_ADDRESS
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class ExplorerEndpointProbe(BaseModel):
    endpoint_url: str
    method: str = "GET"
    status: ExplorerSourceStatus = ExplorerSourceStatus.IMPORT_REQUIRED
    http_status: int | None = None
    error_message: str | None = None
    notes: list[str] = Field(default_factory=list)


class ExplorerResult(BaseModel):
    method: str = "network"
    status: ExplorerSourceStatus = ExplorerSourceStatus.IMPORT_REQUIRED
    started_at_ms: int = Field(default_factory=now_ms)
    finished_at_ms: int | None = None
    endpoints_found: list[ExplorerEndpointProbe] = Field(default_factory=list)
    events_seen: int = 0
    transactions: list[ExplorerTransaction] = Field(default_factory=list)
    full_addresses_found: int = 0
    truncated_addresses_rejected: int = 0
    candidates_created: int = 0
    error_message: str | None = None
    notes: list[str] = Field(default_factory=list)

    def finish(self) -> "ExplorerResult":
        self.finished_at_ms = now_ms()
        return self

