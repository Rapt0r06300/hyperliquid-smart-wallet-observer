from __future__ import annotations

import re

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from pydantic import BaseModel, Field, field_validator, model_validator


_WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class DataQuality(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    BAD = "BAD"
    UNKNOWN = "UNKNOWN"


class PositionAction(StrEnum):
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    ADD = "ADD"
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    UNKNOWN = "UNKNOWN"


class SourceMeta(BaseModel):
    venue: str = "Hyperliquid"
    source_endpoint: str | None = None
    source_channel: str | None = None
    source_ts: int | None = None
    local_received_ts: int
    latency_ms: int | None = None
    raw_ref: str | None = None
    raw_hash: str | None = None
    data_quality: DataQuality = DataQuality.UNKNOWN
    is_stale: bool = False
    schema_version: str = "v9"
    adapter_version: str = "hl_observer.v9"

    @model_validator(mode="after")
    def require_source_and_raw_reference(self) -> "SourceMeta":
        if not (self.source_endpoint or self.source_channel):
            raise ValueError("source endpoint or source channel is required")
        if not (self.raw_ref or self.raw_hash):
            raise ValueError("raw_ref or raw_hash is required")
        return self


class Wallet(BaseModel):
    address: str
    meta: SourceMeta

    @field_validator("address")
    @classmethod
    def validate_wallet(cls, value: str) -> str:
        if "..." in value:
            raise ValueError("truncated wallet address rejected")
        if not _WALLET_RE.match(value):
            raise ValueError("wallet address must be 0x + 40 hex chars")
        return value.lower()


class Coin(BaseModel):
    symbol: str

    @field_validator("symbol")
    @classmethod
    def normalize_coin(cls, value: str) -> str:
        clean = str(value or "").strip().upper()
        if not clean or clean.startswith(("@", "#")):
            raise ValueError("coin symbol is required")
        return clean


class Position(BaseModel):
    wallet: str
    coin: str
    signed_size: float
    entry_px: float | None = None
    mark_px: float | None = None
    unrealized_pnl: float | None = None
    meta: SourceMeta

    @field_validator("wallet")
    @classmethod
    def validate_wallet(cls, value: str) -> str:
        return Wallet(address=value, meta=_dummy_meta()).address

    @field_validator("coin")
    @classmethod
    def validate_coin(cls, value: str) -> str:
        return Coin(symbol=value).symbol


class OpenOrder(BaseModel):
    wallet: str
    coin: str
    oid: str
    side: str | None = None
    limit_px: float | None = None
    size: float | None = None
    reduce_only: bool = False
    meta: SourceMeta

    @field_validator("wallet")
    @classmethod
    def validate_wallet(cls, value: str) -> str:
        return Wallet(address=value, meta=_dummy_meta()).address

    @field_validator("coin")
    @classmethod
    def validate_coin(cls, value: str) -> str:
        return Coin(symbol=value).symbol


class Fill(BaseModel):
    wallet: str
    coin: str
    direction: str | None = None
    side: str | None = None
    size: float
    price: float
    time_ms: int
    start_position: float | None = None
    closed_pnl: float | None = None
    fee: float | None = None
    oid: str | None = None
    tid: str | None = None
    fill_hash: str | None = None
    meta: SourceMeta

    @field_validator("wallet")
    @classmethod
    def validate_wallet(cls, value: str) -> str:
        return Wallet(address=value, meta=_dummy_meta()).address

    @field_validator("coin")
    @classmethod
    def validate_coin(cls, value: str) -> str:
        return Coin(symbol=value).symbol

    @model_validator(mode="after")
    def validate_fill_numbers(self) -> "Fill":
        if self.size <= 0:
            raise ValueError("fill size must be positive")
        if self.price <= 0:
            raise ValueError("fill price must be positive")
        return self


class Candle(BaseModel):
    coin: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    start_ms: int
    meta: SourceMeta

    @field_validator("coin")
    @classmethod
    def validate_coin(cls, value: str) -> str:
        return Coin(symbol=value).symbol


class BookLevel(BaseModel):
    price: float
    size: float

    @model_validator(mode="after")
    def validate_level(self) -> "BookLevel":
        if self.price <= 0:
            raise ValueError("book price must be positive")
        if self.size < 0:
            raise ValueError("book size must be non-negative")
        return self


class NormalizedDelta(BaseModel):
    wallet: str
    coin: str
    previous_size: float
    current_size: float
    action: PositionAction
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    meta: SourceMeta

    @field_validator("wallet")
    @classmethod
    def validate_wallet(cls, value: str) -> str:
        return Wallet(address=value, meta=_dummy_meta()).address

    @field_validator("coin")
    @classmethod
    def validate_coin(cls, value: str) -> str:
        return Coin(symbol=value).symbol


def _dummy_meta() -> SourceMeta:
    return SourceMeta(
        source_endpoint="validation",
        local_received_ts=0,
        raw_ref="validation",
        data_quality=DataQuality.OK,
    )
