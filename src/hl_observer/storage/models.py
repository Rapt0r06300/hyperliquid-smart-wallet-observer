from __future__ import annotations

from datetime import datetime

from enum import StrEnum

from sqlalchemy import Boolean, JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hl_observer.storage.database import Base
from hl_observer.utils.time import utc_now


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FreshnessStatus(StrEnum):
    FRESH = "FRESH"
    DELAYED = "DELAYED"
    STALE = "STALE"
    DEAD = "DEAD"
    ABSENT = "ABSENT"
    CONTRADICTORY = "CONTRADICTORY"
    UNKNOWN = "UNKNOWN"


class SourceHealth(Base, TimestampMixin):
    __tablename__ = "source_health"
    source_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_event_at_ms: Mapped[int | None] = mapped_column(Integer)
    last_success_at_ms: Mapped[int | None] = mapped_column(Integer)
    seconds_since_last_event: Mapped[int | None] = mapped_column(Integer)
    observed_latency_ms: Mapped[int | None] = mapped_column(Integer)
    freshness_status: Mapped[str] = mapped_column(String(32), default=FreshnessStatus.UNKNOWN.value)
    is_consistent: Mapped[bool] = mapped_column(Boolean, default=True)
    is_heartbeat: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)


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
    collection_run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    local_received_ts: Mapped[int | None] = mapped_column(Integer, index=True)
    exchange_ts: Mapped[int | None] = mapped_column(Integer)
    positions_json: Mapped[list | None] = mapped_column(JSON)
    open_orders_json: Mapped[list | None] = mapped_column(JSON)
    frontend_open_orders_json: Mapped[list | None] = mapped_column(JSON)
    fills_json: Mapped[list | None] = mapped_column(JSON)
    all_mids_json: Mapped[dict | None] = mapped_column(JSON)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str | None] = mapped_column(String(64))
    stopped_reason: Mapped[str | None] = mapped_column(String(128))
    errors_json: Mapped[list | None] = mapped_column(JSON)
    summary: Mapped[str | None] = mapped_column(Text)


class WalletScoreModel(Base, TimestampMixin):
    __tablename__ = "wallet_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    score: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(64))
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)


class WalletBackfillRun(Base):
    __tablename__ = "wallet_backfill_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    started_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    finished_at_ms: Mapped[int | None] = mapped_column(Integer)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    fills_count: Mapped[int] = mapped_column(Integer, default=0)
    open_orders_count: Mapped[int] = mapped_column(Integer, default=0)
    deltas_count: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text)


class WalletDiscoveryRun(Base):
    __tablename__ = "wallet_discovery_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    finished_at_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    sources_attempted: Mapped[int] = mapped_column(Integer, default=0)
    candidates_found: Mapped[int] = mapped_column(Integer, default=0)
    candidates_after_filter: Mapped[int] = mapped_column(Integer, default=0)
    wallets_selected: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class WalletDiscoverySourceModel(Base):
    __tablename__ = "wallet_discovery_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    source_name: Mapped[str] = mapped_column(String(128), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str | None] = mapped_column(Text)
    reliability_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    candidates_found: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    fetched_at_ms: Mapped[int] = mapped_column(Integer, index=True)


class WalletCandidateModel(Base):
    __tablename__ = "wallet_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str | None] = mapped_column(String(32), index=True)
    source_name: Mapped[str] = mapped_column(String(128), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str | None] = mapped_column(String(255))
    external_pnl_usdc: Mapped[float | None] = mapped_column(Float)
    external_roi_pct: Mapped[float | None] = mapped_column(Float)
    external_volume_usdc: Mapped[float | None] = mapped_column(Float)
    external_win_rate: Mapped[float | None] = mapped_column(Float)
    external_position_usdc: Mapped[float | None] = mapped_column(Float)
    external_unrealized_pnl: Mapped[float | None] = mapped_column(Float)
    external_funding_fee: Mapped[float | None] = mapped_column(Float)
    first_seen_ms: Mapped[int] = mapped_column(Integer)
    last_seen_ms: Mapped[int] = mapped_column(Integer)
    raw_payload_json: Mapped[dict | None] = mapped_column(JSON)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    selected_for_backfill: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class AutoWatchlist(Base):
    __tablename__ = "auto_watchlist"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str | None] = mapped_column(String(32), index=True)
    label: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(128))
    added_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(32), default="selected")
    discovery_score: Mapped[float] = mapped_column(Float, default=0.0)
    last_backfill_ms: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class WalletCandidateScoreModel(Base):
    __tablename__ = "wallet_candidate_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str | None] = mapped_column(String(32), index=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    pnl_positive_score: Mapped[float] = mapped_column(Float, default=0.0)
    roi_positive_score: Mapped[float] = mapped_column(Float, default=0.0)
    activity_score: Mapped[float] = mapped_column(Float, default=0.0)
    recency_score: Mapped[float] = mapped_column(Float, default=0.0)
    size_score: Mapped[float] = mapped_column(Float, default=0.0)
    copyability_pre_score: Mapped[float] = mapped_column(Float, default=0.0)
    source_confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_discovery_score: Mapped[float] = mapped_column(Float, default=0.0)
    decision: Mapped[str] = mapped_column(String(64))
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)


class Fill(Base, TimestampMixin):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    exchange_ts: Mapped[int] = mapped_column(Integer, index=True)
    side: Mapped[str | None] = mapped_column(String(16))
    price: Mapped[float | None] = mapped_column(Float)
    size: Mapped[float | None] = mapped_column(Float)
    fill_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    oid: Mapped[str | None] = mapped_column(String(128), index=True)
    tid: Mapped[str | None] = mapped_column(String(128), index=True)
    direction: Mapped[str | None] = mapped_column(String(64))
    start_position: Mapped[float | None] = mapped_column(Float)
    closed_pnl: Mapped[float | None] = mapped_column(Float)
    fee: Mapped[float | None] = mapped_column(Float)
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
    side: Mapped[str | None] = mapped_column(String(16))
    size: Mapped[float] = mapped_column(Float, default=0.0)
    entry_price: Mapped[float | None] = mapped_column(Float)
    entry_px_estimated: Mapped[float | None] = mapped_column(Float)
    last_px: Mapped[float | None] = mapped_column(Float)
    notional_usdc: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64), default="fills")
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    opened_at_ms: Mapped[int | None] = mapped_column(Integer)
    updated_at_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="INCOMPLETE")
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class PositionDeltaModel(Base, TimestampMixin):
    __tablename__ = "position_deltas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    previous_side: Mapped[str | None] = mapped_column(String(16))
    new_side: Mapped[str | None] = mapped_column(String(16))
    previous_size: Mapped[float] = mapped_column(Float)
    current_size: Mapped[float] = mapped_column(Float)
    new_size: Mapped[float] = mapped_column(Float, default=0.0)
    delta_size: Mapped[float] = mapped_column(Float)
    delta_notional_usdc: Mapped[float | None] = mapped_column(Float)
    action: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    exchange_ts: Mapped[int | None] = mapped_column(Integer)
    fill_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source_event_id: Mapped[int | None] = mapped_column(Integer, index=True)
    side: Mapped[str | None] = mapped_column(String(16))
    price: Mapped[float | None] = mapped_column(Float)
    fill_size: Mapped[float | None] = mapped_column(Float)
    delta_type: Mapped[str] = mapped_column(String(64), default="unknown")
    confidence: Mapped[str] = mapped_column(String(32), default="medium")
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    detected_at_ms: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(64), default="fills")
    snapshot_id: Mapped[int | None] = mapped_column(Integer, index=True)
    run_mode: Mapped[str] = mapped_column(String(32), default="LIVE")
    source_quality: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    is_paper_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    proofs_json: Mapped[dict | None] = mapped_column(JSON)
    delta_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class WalletActivitySummary(Base):
    __tablename__ = "wallet_activity_summary"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    window_start_ms: Mapped[int | None] = mapped_column(Integer)
    window_end_ms: Mapped[int | None] = mapped_column(Integer)
    fills_count: Mapped[int] = mapped_column(Integer, default=0)
    coins_count: Mapped[int] = mapped_column(Integer, default=0)
    total_volume_estimated: Mapped[float] = mapped_column(Float, default=0.0)
    long_actions_count: Mapped[int] = mapped_column(Integer, default=0)
    short_actions_count: Mapped[int] = mapped_column(Integer, default=0)
    open_count: Mapped[int] = mapped_column(Integer, default=0)
    add_count: Mapped[int] = mapped_column(Integer, default=0)
    reduce_count: Mapped[int] = mapped_column(Integer, default=0)
    close_count: Mapped[int] = mapped_column(Integer, default=0)
    flip_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at_ms: Mapped[int] = mapped_column(Integer)


class MarketSnapshot(Base, TimestampMixin):
    __tablename__ = "market_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), default="allMids")
    exchange_ts: Mapped[int | None] = mapped_column(Integer)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class MarketUniverseModel(Base):
    __tablename__ = "market_universe"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_spot: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_ms: Mapped[int] = mapped_column(Integer)
    last_seen_ms: Mapped[int] = mapped_column(Integer, index=True)
    mid_price: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)


class MarketMetric(Base):
    __tablename__ = "market_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    computed_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    mid_price: Mapped[float | None] = mapped_column(Float)
    spread_bps: Mapped[float | None] = mapped_column(Float)
    depth_usdc: Mapped[float | None] = mapped_column(Float)
    volume_hint_usdc: Mapped[float | None] = mapped_column(Float)
    open_interest_hint_usdc: Mapped[float | None] = mapped_column(Float)
    funding_hint: Mapped[float | None] = mapped_column(Float)
    liquidity_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_scannable: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class WalletCoinProfileModel(Base):
    __tablename__ = "wallet_coin_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    window: Mapped[str] = mapped_column(String(64), default="latest")
    computed_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    fills_count: Mapped[int] = mapped_column(Integer, default=0)
    deltas_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_pnl_usdc: Mapped[float | None] = mapped_column(Float)
    estimated_roi_pct: Mapped[float | None] = mapped_column(Float)
    estimated_volume_usdc: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float)
    last_activity_ms: Mapped[int | None] = mapped_column(Integer)
    copyability_score: Mapped[float] = mapped_column(Float, default=0.0)
    liquidity_score: Mapped[float] = mapped_column(Float, default=0.0)
    toxicity_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_coin_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="INCOMPLETE")


class WalletCoinScoreModel(Base):
    __tablename__ = "wallet_coin_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    computed_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    performance_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    consistency_score: Mapped[float] = mapped_column(Float, default=0.0)
    copyability_score: Mapped[float] = mapped_column(Float, default=0.0)
    liquidity_score: Mapped[float] = mapped_column(Float, default=0.0)
    timing_score: Mapped[float] = mapped_column(Float, default=0.0)
    toxicity_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    decision: Mapped[str] = mapped_column(String(64))
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)


class CoinOpportunity(Base):
    __tablename__ = "coin_opportunities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    computed_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    wallets_active: Mapped[int] = mapped_column(Integer, default=0)
    wallets_positive_pnl: Mapped[int] = mapped_column(Integer, default=0)
    wallets_positive_roi: Mapped[int] = mapped_column(Integer, default=0)
    avg_wallet_score: Mapped[float | None] = mapped_column(Float)
    best_wallet_address: Mapped[str | None] = mapped_column(String(64))
    best_wallet_score: Mapped[float | None] = mapped_column(Float)
    liquidity_score: Mapped[float] = mapped_column(Float, default=0.0)
    spread_bps: Mapped[float | None] = mapped_column(Float)
    opportunity_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="observed")
    notes: Mapped[str | None] = mapped_column(Text)


class MarketRegime(Base):
    __tablename__ = "market_regimes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    computed_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    volatility_regime: Mapped[str] = mapped_column(String(64), default="unknown")
    trend_regime: Mapped[str] = mapped_column(String(64), default="unknown")
    notes: Mapped[str | None] = mapped_column(Text)


class LeaderboardRun(Base):
    __tablename__ = "leaderboard_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    finished_at_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(64))
    source_method: Mapped[str] = mapped_column(String(64))
    period: Mapped[str] = mapped_column(String(16), default="30D")
    rows_seen: Mapped[int] = mapped_column(Integer, default=0)
    full_addresses_found: Mapped[int] = mapped_column(Integer, default=0)
    truncated_addresses_seen: Mapped[int] = mapped_column(Integer, default=0)
    candidates_created: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class LeaderboardExtractionAttempt(Base):
    __tablename__ = "leaderboard_extraction_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    finished_at_ms: Mapped[int | None] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64))
    rows_seen: Mapped[int] = mapped_column(Integer, default=0)
    full_addresses_found: Mapped[int] = mapped_column(Integer, default=0)
    truncated_addresses_seen: Mapped[int] = mapped_column(Integer, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class LeaderboardAddressValidation(Base):
    __tablename__ = "leaderboard_address_validation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    raw_value: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(String(64), index=True)
    is_full_address: Mapped[bool] = mapped_column(Boolean, default=False)
    is_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_status: Mapped[str] = mapped_column(String(64))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    source_method: Mapped[str] = mapped_column(String(64))
    created_at_ms: Mapped[int] = mapped_column(Integer, index=True)


class LeaderboardRow(Base):
    __tablename__ = "leaderboard_rows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    rank: Mapped[int | None] = mapped_column(Integer)
    address: Mapped[str | None] = mapped_column(String(64), index=True)
    address_short: Mapped[str | None] = mapped_column(String(64), index=True)
    address_is_full: Mapped[bool] = mapped_column(Boolean, default=False)
    address_validation_status: Mapped[str] = mapped_column(String(64))
    account_value_usdc: Mapped[float | None] = mapped_column(Float)
    pnl_usdc: Mapped[float | None] = mapped_column(Float)
    roi_pct: Mapped[float | None] = mapped_column(Float)
    volume_usdc: Mapped[float | None] = mapped_column(Float)
    period: Mapped[str] = mapped_column(String(16), default="30D")
    source_method: Mapped[str] = mapped_column(String(64))
    extraction_method: Mapped[str] = mapped_column(String(64))
    source_payload_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    imported_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    validation_status: Mapped[str] = mapped_column(String(64))
    source_confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class LeaderboardWalletCandidate(Base):
    __tablename__ = "leaderboard_wallet_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    rank: Mapped[int | None] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(16), default="30D")
    account_value_usdc: Mapped[float | None] = mapped_column(Float)
    pnl_usdc: Mapped[float | None] = mapped_column(Float)
    roi_pct: Mapped[float | None] = mapped_column(Float)
    volume_usdc: Mapped[float | None] = mapped_column(Float)
    leaderboard_score: Mapped[float] = mapped_column(Float, default=0.0)
    selected_for_revalidation: Mapped[bool] = mapped_column(Boolean, default=False)
    selected_for_backfill: Mapped[bool] = mapped_column(Boolean, default=False)
    source_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text)


class ExplorerRun(Base):
    __tablename__ = "explorer_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    finished_at_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(64))
    endpoints_found: Mapped[int] = mapped_column(Integer, default=0)
    events_seen: Mapped[int] = mapped_column(Integer, default=0)
    transactions_stored: Mapped[int] = mapped_column(Integer, default=0)
    full_addresses_found: Mapped[int] = mapped_column(Integer, default=0)
    truncated_addresses_rejected: Mapped[int] = mapped_column(Integer, default=0)
    candidates_created: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class ExplorerEndpoint(Base):
    __tablename__ = "explorer_endpoints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    endpoint_url: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(16), default="GET")
    status: Mapped[str] = mapped_column(String(64))
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at_ms: Mapped[int] = mapped_column(Integer, index=True)


class ExplorerBlock(Base):
    __tablename__ = "explorer_blocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    block_number: Mapped[int | None] = mapped_column(Integer, index=True)
    timestamp_ms: Mapped[int | None] = mapped_column(Integer, index=True)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ExplorerTransaction(Base):
    __tablename__ = "explorer_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    tx_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    block: Mapped[int | None] = mapped_column(Integer, index=True)
    timestamp_ms: Mapped[int | None] = mapped_column(Integer, index=True)
    action_type: Mapped[str | None] = mapped_column(String(64))
    wallet_address: Mapped[str | None] = mapped_column(String(64), index=True)
    address_short: Mapped[str | None] = mapped_column(String(64))
    coin: Mapped[str | None] = mapped_column(String(32), index=True)
    side: Mapped[str | None] = mapped_column(String(16))
    size: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)
    value_usdc: Mapped[float | None] = mapped_column(Float)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    validation_status: Mapped[str] = mapped_column(String(64))
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at_ms: Mapped[int] = mapped_column(Integer, index=True)


class ExplorerEvent(Base):
    __tablename__ = "explorer_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    wallet_address: Mapped[str | None] = mapped_column(String(64), index=True)
    coin: Mapped[str | None] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(64))
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at_ms: Mapped[int] = mapped_column(Integer, index=True)


class ExplorerWalletCandidate(Base):
    __tablename__ = "explorer_wallet_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64), default="explorer")
    first_tx_hash: Mapped[str | None] = mapped_column(String(128))
    events_count: Mapped[int] = mapped_column(Integer, default=0)
    coins_json: Mapped[list] = mapped_column(JSON, default=list)
    activity_score: Mapped[float] = mapped_column(Float, default=0.0)
    selected_for_revalidation: Mapped[bool] = mapped_column(Boolean, default=True)
    validation_status: Mapped[str] = mapped_column(String(64), default="FULL_ADDRESS_OK")
    created_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class ExplorerRevalidationResult(Base):
    __tablename__ = "explorer_revalidation_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    method: Mapped[str] = mapped_column(String(64), default="info")
    checked_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ExplorerTransactionTape(Base):
    __tablename__ = "explorer_transaction_tape"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[int | None] = mapped_column(Integer, index=True)
    tx_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    block: Mapped[int | None] = mapped_column(Integer, index=True)
    action_type: Mapped[str | None] = mapped_column(String(64))
    wallet_address: Mapped[str | None] = mapped_column(String(64), index=True)
    coin: Mapped[str | None] = mapped_column(String(32), index=True)
    value_usdc: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(64))
    candidate_created: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at_ms: Mapped[int] = mapped_column(Integer, index=True)


class WalletBootstrapRun(Base):
    __tablename__ = "wallet_bootstrap_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    finished_at_ms: Mapped[int | None] = mapped_column(Integer)
    target_wallets: Mapped[int] = mapped_column(Integer, default=500)
    source: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64))
    candidates_seen: Mapped[int] = mapped_column(Integer, default=0)
    wallets_selected: Mapped[int] = mapped_column(Integer, default=0)
    truncated_rejected: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class TopWallet(Base):
    __tablename__ = "top_wallets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    rank: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    selected_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(64), default="selected")
    notes: Mapped[str | None] = mapped_column(Text)


class TopWalletSource(Base):
    __tablename__ = "top_wallet_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64))
    source_rank: Mapped[int | None] = mapped_column(Integer)
    source_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at_ms: Mapped[int] = mapped_column(Integer, index=True)


class WalletRevalidationResult(Base):
    __tablename__ = "wallet_revalidation_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    method: Mapped[str] = mapped_column(String(64), default="info")
    checked_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Top500Export(Base):
    __tablename__ = "top500_exports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(16))
    rows_exported: Mapped[int] = mapped_column(Integer, default=0)
    created_at_ms: Mapped[int] = mapped_column(Integer, index=True)


class WalletScanQueue(Base):
    __tablename__ = "wallet_scan_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64), default="QUEUED")
    queued_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    last_attempt_ms: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class WalletScanJob(Base):
    __tablename__ = "wallet_scan_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    finished_at_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(64))
    wallets_requested: Mapped[int] = mapped_column(Integer, default=0)
    wallets_scanned: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class WalletScanResult(Base):
    __tablename__ = "wallet_scan_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int | None] = mapped_column(Integer, index=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64))
    scanned_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    fills_count: Mapped[int] = mapped_column(Integer, default=0)
    deltas_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class WalletTradeLifecycle(Base):
    __tablename__ = "wallet_trade_lifecycles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str | None] = mapped_column(String(16))
    opened_at_ms: Mapped[int | None] = mapped_column(Integer)
    closed_at_ms: Mapped[int | None] = mapped_column(Integer)
    realized_pnl_usdc: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(64), default="OPEN")
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)


class WalletOpening(Base):
    __tablename__ = "wallet_openings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    opening_type: Mapped[str] = mapped_column(String(64))
    side: Mapped[str | None] = mapped_column(String(16))
    detected_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)


class WalletClosing(Base):
    __tablename__ = "wallet_closings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    closing_type: Mapped[str] = mapped_column(String(64))
    detected_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)


class WalletOpeningOutcome(Base):
    __tablename__ = "wallet_opening_outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    opening_type: Mapped[str] = mapped_column(String(64))
    pnl_usdc: Mapped[float | None] = mapped_column(Float)
    roi_pct: Mapped[float | None] = mapped_column(Float)
    hold_time_ms: Mapped[int | None] = mapped_column(Integer)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)


class WalletOpeningPatternStats(Base):
    __tablename__ = "wallet_opening_pattern_stats"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str | None] = mapped_column(String(64), index=True)
    coin: Mapped[str | None] = mapped_column(String(32), index=True)
    opening_type: Mapped[str] = mapped_column(String(64), index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float | None] = mapped_column(Float)
    expectancy: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    opening_pattern_score: Mapped[float] = mapped_column(Float, default=0.0)
    decision: Mapped[str] = mapped_column(String(64), default="OBSERVE_ONLY")
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)


class WalletClosingPatternStats(Base):
    __tablename__ = "wallet_closing_pattern_stats"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str | None] = mapped_column(String(64), index=True)
    coin: Mapped[str | None] = mapped_column(String(32), index=True)
    closing_type: Mapped[str] = mapped_column(String(64), index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    decision: Mapped[str] = mapped_column(String(64), default="OBSERVE_ONLY")
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)


class TradeLifecycleEvent(Base):
    __tablename__ = "trade_lifecycle_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    event_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class WalletMethodologyProfile(Base):
    __tablename__ = "wallet_methodology_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    primary_style: Mapped[str] = mapped_column(String(64), default="UNKNOWN")
    best_coins_json: Mapped[list] = mapped_column(JSON, default=list)
    worst_coins_json: Mapped[list] = mapped_column(JSON, default=list)
    best_opening_types_json: Mapped[list] = mapped_column(JSON, default=list)
    worst_opening_types_json: Mapped[list] = mapped_column(JSON, default=list)
    best_closing_types_json: Mapped[list] = mapped_column(JSON, default=list)
    average_hold_time_ms: Mapped[int | None] = mapped_column(Integer)
    scale_in_behavior: Mapped[str | None] = mapped_column(Text)
    reduce_behavior: Mapped[str | None] = mapped_column(Text)
    take_profit_behavior: Mapped[str | None] = mapped_column(Text)
    stop_behavior: Mapped[str | None] = mapped_column(Text)
    dca_behavior: Mapped[str | None] = mapped_column(Text)
    copyability_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    methodology_summary: Mapped[str] = mapped_column(Text)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)


class WalletPlaybook(Base):
    __tablename__ = "wallet_playbooks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str | None] = mapped_column(String(32), index=True)
    playbook_type: Mapped[str] = mapped_column(String(64))
    rule_summary: Mapped[str] = mapped_column(Text)
    opening_rules_json: Mapped[list] = mapped_column(JSON, default=list)
    closing_rules_json: Mapped[list] = mapped_column(JSON, default=list)
    risk_rules_json: Mapped[list] = mapped_column(JSON, default=list)
    copy_rules_json: Mapped[list] = mapped_column(JSON, default=list)
    rejected_rules_json: Mapped[list] = mapped_column(JSON, default=list)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(64), default="OBSERVE_ONLY")


class FollowSignal(Base):
    __tablename__ = "follow_signals"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str | None] = mapped_column(String(16))
    opening_type: Mapped[str | None] = mapped_column(String(64))
    created_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    signal_age_ms: Mapped[int] = mapped_column(Integer, default=0)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class FollowDecision(Base):
    __tablename__ = "follow_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(String(128), index=True)
    decision: Mapped[str] = mapped_column(String(64))
    allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)
    risk_level: Mapped[str] = mapped_column(String(64), default="OBSERVE_ONLY")
    computed_at_ms: Mapped[int] = mapped_column(Integer, index=True)


class PaperFollowOrder(Base):
    __tablename__ = "paper_follow_orders"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(128), index=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)
    coin: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str | None] = mapped_column(String(16))
    notional_usdc: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(64), default="SIMULATED")
    created_at_ms: Mapped[int] = mapped_column(Integer, index=True)


class FollowReconciliationEvent(Base):
    __tablename__ = "follow_reconciliation_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str | None] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    created_at_ms: Mapped[int] = mapped_column(Integer, index=True)


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


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    finished_at_ms: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(32))
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    wallets_count: Mapped[int] = mapped_column(Integer, default=0)
    coins_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class CollectionItem(Base):
    __tablename__ = "collection_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.id"), index=True)
    item_type: Mapped[str] = mapped_column(String(64), index=True)
    wallet_address: Mapped[str | None] = mapped_column(String(64), index=True)
    coin: Mapped[str | None] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)


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
    endpoint: Mapped[str] = mapped_column(String(128), default="/info")
    request_type: Mapped[str] = mapped_column(String(64), index=True)
    wallet_address: Mapped[str | None] = mapped_column(String(64), index=True)
    coin: Mapped[str | None] = mapped_column(String(32), index=True)
    request_payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    response_payload_json: Mapped[dict | list] = mapped_column(JSON, default=dict)
    response_hash: Mapped[str] = mapped_column(String(64), index=True)
    fetched_at_ms: Mapped[int] = mapped_column(Integer, index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str | None] = mapped_column(String(64))
    wallet: Mapped[str | None] = mapped_column(String(64), index=True)
    exchange_ts: Mapped[int | None] = mapped_column(Integer, index=True)
    local_received_ts: Mapped[int] = mapped_column(Integer, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
