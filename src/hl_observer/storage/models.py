from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hl_observer.storage.database import Base
from hl_observer.utils.time import utc_now


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Wallet(Base, TimestampMixin):
    __tablename__ = "wallets"
    address: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(64), default="candidate")
    sources: Mapped[list["WalletSource"]] = relationship(back_populates="wallet")


class WalletSource(Base, TimestampMixin):
    __tablename__ = "wallet_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(ForeignKey("wallets.address"))
    source: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    wallet: Mapped[Wallet] = relationship(back_populates="sources")


class WalletSnapshot(Base, TimestampMixin):
    __tablename__ = "wallet_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    exchange_ts: Mapped[int | None] = mapped_column(Integer)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class WalletScoreModel(Base, TimestampMixin):
    __tablename__ = "wallet_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    score: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(64))
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Fill(Base, TimestampMixin):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    exchange_ts: Mapped[int] = mapped_column(Integer, index=True)
    side: Mapped[str | None] = mapped_column(String(16))
    price: Mapped[float | None] = mapped_column(Float)
    size: Mapped[float | None] = mapped_column(Float)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("wallet_address", "coin", "exchange_ts", "raw_json"),)


class OpenOrder(Base, TimestampMixin):
    __tablename__ = "open_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    oid: Mapped[str | None] = mapped_column(String(128), index=True)
    cloid: Mapped[str | None] = mapped_column(String(128), index=True)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Position(Base, TimestampMixin):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    size: Mapped[float] = mapped_column(Float, default=0.0)
    entry_price: Mapped[float | None] = mapped_column(Float)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class PositionDeltaModel(Base, TimestampMixin):
    __tablename__ = "position_deltas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    previous_size: Mapped[float] = mapped_column(Float)
    current_size: Mapped[float] = mapped_column(Float)
    delta_size: Mapped[float] = mapped_column(Float)
    exchange_ts: Mapped[int | None] = mapped_column(Integer)


class MarketSnapshot(Base, TimestampMixin):
    __tablename__ = "market_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), default="allMids")
    exchange_ts: Mapped[int | None] = mapped_column(Integer)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class OrderbookSnapshot(Base, TimestampMixin):
    __tablename__ = "orderbook_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    exchange_ts: Mapped[int | None] = mapped_column(Integer)
    depth_usdc: Mapped[float | None] = mapped_column(Float)
    spread_bps: Mapped[float | None] = mapped_column(Float)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Signal(Base, TimestampMixin):
    __tablename__ = "signals"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_wallet: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(16))
    signal_type: Mapped[str] = mapped_column(String(32))
    decision: Mapped[str] = mapped_column(String(64))
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class SignalScoreModel(Base, TimestampMixin):
    __tablename__ = "signal_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(String(128), index=True)
    score: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(64))
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)


class RejectedSignal(Base, TimestampMixin):
    __tablename__ = "rejected_signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(String(128), index=True)
    decision: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class EdgeMetric(Base, TimestampMixin):
    __tablename__ = "edge_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(String(128), index=True)
    expected_edge_bps: Mapped[float] = mapped_column(Float)
    costs_bps: Mapped[float] = mapped_column(Float)
    edge_remaining_bps: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(64))


class PaperOrderModel(Base, TimestampMixin):
    __tablename__ = "paper_orders"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(128), index=True)
    coin: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(16))
    notional_usdc: Mapped[float] = mapped_column(Float)
    requested_price: Mapped[float] = mapped_column(Float)
    simulated_fill_price: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(64))


class PaperFill(Base, TimestampMixin):
    __tablename__ = "paper_fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_order_id: Mapped[str] = mapped_column(String(64), index=True)
    fill_price: Mapped[float] = mapped_column(Float)
    fill_size: Mapped[float] = mapped_column(Float)
    fee_bps: Mapped[float] = mapped_column(Float)


class RiskEvent(Base, TimestampMixin):
    __tablename__ = "risk_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str | None] = mapped_column(String(128), index=True)
    decision: Mapped[str] = mapped_column(String(64))
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)
    gates_json: Mapped[dict] = mapped_column(JSON, default=dict)


class KillSwitchEvent(Base, TimestampMixin):
    __tablename__ = "kill_switch_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    active: Mapped[bool]
    reason: Mapped[str | None] = mapped_column(Text)


class ApiHealth(Base, TimestampMixin):
    __tablename__ = "api_health"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String(64))
    ok: Mapped[bool]
    latency_ms: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)


class SourceReference(Base, TimestampMixin):
    __tablename__ = "source_references"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class RawEvent(Base, TimestampMixin):
    __tablename__ = "raw_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64))
    wallet: Mapped[str | None] = mapped_column(String(64), index=True)
    coin: Mapped[str | None] = mapped_column(String(32), index=True)
    exchange_ts: Mapped[int | None] = mapped_column(Integer, index=True)
    local_received_ts: Mapped[int] = mapped_column(Integer, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
