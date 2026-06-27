"""V12 local decision pipeline.

This module wires the V12 vertical slice together without touching real money:

raw Hyperliquid fill payloads -> strict normalization -> lifecycle events ->
leader deltas -> cluster detection -> edge net -> RiskEngine/PaperEngine ->
evidence chain -> optional SQLite persistence.

Every missing market fact becomes an explicit NO_TRADE reason. The pipeline does
not fetch network data, does not sign, never calls venue write endpoints, and
never creates venue orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from typing import Any

from hl_observer.edge.edge_net_v12 import EdgeNetV12Estimate, EdgeNetV12Inputs, estimate_edge_net_v12
from hl_observer.evidence.decision_ledger import PaperDecisionEvidence, evidence_from_paper_result
from hl_observer.models import DataQuality, Fill, SourceMeta
from hl_observer.normalization.fills import NormalizedFillResult, normalize_hyperliquid_fill
from hl_observer.paper_trading.paper_engine import PaperDecisionResult, PaperEngine, PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction, LifecycleEvent, event_from_fill
from hl_observer.signals.cluster_detector import ClusterConfig, SignalCluster, detect_signal_clusters
from hl_observer.signals.leader_delta import LeaderDelta, leader_delta_from_lifecycle_event
from hl_observer.storage.raw_store import RawStore, make_raw_event
from hl_observer.storage.run_context import RunContext
from hl_observer.storage.v12_sqlite_store import V12SQLiteStore


@dataclass(frozen=True, slots=True)
class V12DecisionPipelineConfig:
    source_endpoint: str = "/info:userFillsByTime"
    source_id: str = "hyperliquid_info_user_fills_by_time"
    min_edge_bps: float = 30.0
    max_copy_degradation_bps: float = 40.0
    spread_bps: float | None = 2.0
    slippage_bps: float | None = 2.0
    fee_bps: float | None = 4.5
    funding_estimate_bps: float | None = 0.0
    latency_penalty_bps: float = 0.0
    copy_degradation_bps: float = 0.0
    liquidity_penalty_bps: float = 0.0
    volatility_penalty_bps: float = 0.0
    adverse_selection_penalty_bps: float = 0.0
    crowding_penalty_bps: float = 0.0
    top_depth_usdt: float | None = 100_000.0
    wallet_score: float = 90.0
    signal_score: float = 85.0
    cluster_config: ClusterConfig = field(default_factory=ClusterConfig)
    paper_config: PaperEngineConfig = field(default_factory=PaperEngineConfig)


@dataclass(frozen=True, slots=True)
class V12DecisionPipelineInput:
    wallet: str
    raw_fills: tuple[dict[str, Any], ...]
    observed_at_ms: int
    market_mids: dict[str, float]
    leader_expected_edge_bps_by_coin: dict[str, float] = field(default_factory=dict)
    run_context: RunContext = RunContext.LIVE
    request_id: str | None = None
    source_ts_ms: int | None = None


@dataclass(frozen=True, slots=True)
class V12DecisionPipelineResult:
    normalized: tuple[NormalizedFillResult, ...]
    fills: tuple[Fill, ...]
    lifecycle_events: tuple[LifecycleEvent, ...]
    leader_deltas: tuple[LeaderDelta, ...]
    clusters: tuple[SignalCluster, ...]
    edge_estimates: dict[str, EdgeNetV12Estimate]
    paper_results: tuple[PaperDecisionResult, ...]
    evidences: tuple[PaperDecisionEvidence, ...]
    no_trade_reasons: tuple[str, ...]
    raw_events_stored: int
    persisted_counts: dict[str, int] = field(default_factory=dict)


def run_v12_decision_pipeline(
    pipeline_input: V12DecisionPipelineInput,
    *,
    config: V12DecisionPipelineConfig | None = None,
    paper_engine: PaperEngine | None = None,
    store: V12SQLiteStore | None = None,
    raw_store: RawStore | None = None,
) -> V12DecisionPipelineResult:
    """Run one local, read-only V12 decision slice from already collected data."""

    cfg = config or V12DecisionPipelineConfig()
    engine = paper_engine or PaperEngine(config=cfg.paper_config)
    if store is not None:
        store.initialize()

    normalized: list[NormalizedFillResult] = []
    raw_events_stored = 0
    no_trade_reasons: list[str] = []
    for idx, raw in enumerate(pipeline_input.raw_fills):
        raw_hash = _raw_hash(raw)
        if raw_store is not None:
            stored = raw_store.put(
                make_raw_event(
                    source_id=cfg.source_id,
                    kind=cfg.source_endpoint,
                    payload=raw,
                    fetched_at_ms=pipeline_input.observed_at_ms,
                    context=pipeline_input.run_context,
                    source_ts_ms=pipeline_input.source_ts_ms,
                    item_count=1,
                    request_id=pipeline_input.request_id or f"v12-pipeline:{idx}",
                )
            )
            raw_events_stored += 1 if stored else 0
        meta = SourceMeta(
            source_endpoint=cfg.source_endpoint,
            source_ts=pipeline_input.source_ts_ms,
            local_received_ts=pipeline_input.observed_at_ms,
            raw_hash=raw_hash,
            data_quality=DataQuality.OK,
            schema_version="v12",
            adapter_version="hl_observer.v12_decision_pipeline",
        )
        try:
            result = normalize_hyperliquid_fill(raw, wallet=pipeline_input.wallet, meta=meta)
        except Exception as exc:  # pydantic validation should become visible evidence, not a crash.
            result = NormalizedFillResult(
                fill=None,
                dedupe_key=f"invalid:{raw_hash[:16]}",
                signed_size_delta=None,
                resulting_position=None,
                warnings=(f"NORMALIZATION_EXCEPTION:{type(exc).__name__}",),
                raw_ref=f"raw:{raw_hash[:16]}",
            )
        normalized.append(result)
        no_trade_reasons.extend(result.warnings)

    fills = tuple(result.fill for result in normalized if result.fill is not None)
    lifecycle_events = tuple(event_from_fill(fill) for fill in fills)
    deltas = tuple(
        leader_delta_from_lifecycle_event(event, observed_at_ms=pipeline_input.observed_at_ms, source="v12_decision_pipeline")
        for event in lifecycle_events
    )
    clusters = tuple(
        detect_signal_clusters(list(deltas), observed_at_ms=pipeline_input.observed_at_ms, config=cfg.cluster_config)
    )
    if store is not None:
        for cluster in clusters:
            store.upsert_signal_cluster(cluster)

    events_by_delta = {delta.delta_id: event for delta, event in zip(deltas, lifecycle_events, strict=True)}
    edge_estimates: dict[str, EdgeNetV12Estimate] = {}
    paper_results: list[PaperDecisionResult] = []
    evidences: list[PaperDecisionEvidence] = []
    for delta in deltas:
        event = events_by_delta[delta.delta_id]
        mid = _mid_for(delta.coin, pipeline_input.market_mids)
        leader_expected_edge = pipeline_input.leader_expected_edge_bps_by_coin.get(delta.coin.upper())
        edge = _estimate_edge(delta, event, mid, leader_expected_edge, cfg)
        edge_estimates[delta.delta_id] = edge
        if store is not None:
            store.upsert_edge_estimate(_edge_id(delta), edge, created_at_ms=pipeline_input.observed_at_ms)

        enriched_delta = delta
        if edge.reason_codes:
            enriched_delta = replace(delta, reason_codes=tuple(dict.fromkeys((*delta.reason_codes, *edge.reason_codes))))
        market_price = float(mid or 0.0)
        paper_result = engine.apply_delta(
            enriched_delta,
            market_price=market_price,
            observed_at_ms=pipeline_input.observed_at_ms,
            edge_remaining_bps=float(edge.net_edge_bps or 0.0),
            spread_bps=float(cfg.spread_bps or 0.0),
            estimated_slippage_bps=float(cfg.slippage_bps or 0.0),
            top_depth_usdt=cfg.top_depth_usdt,
            wallet_score=cfg.wallet_score,
            signal_score=cfg.signal_score,
            marks={delta.coin: market_price} if market_price > 0 else {},
        )
        paper_results.append(paper_result)
        evidence = evidence_from_paper_result(
            enriched_delta,
            paper_result,
            source_refs=("normalized_fill", "position_lifecycle", "leader_delta", "edge_net_v12", "risk_engine", "paper_engine"),
        )
        evidences.append(evidence)
        if store is not None:
            store.upsert_decision_evidence(evidence, created_at_ms=pipeline_input.observed_at_ms)
        no_trade_reasons.extend(edge.reason_codes)
        no_trade_reasons.extend(paper_result.reason_codes)

    persisted_counts = {}
    if store is not None:
        for table in ("v12_signal_clusters", "v12_edge_estimates", "v12_decision_evidence"):
            persisted_counts[table] = store.count(table)

    return V12DecisionPipelineResult(
        normalized=tuple(normalized),
        fills=fills,
        lifecycle_events=lifecycle_events,
        leader_deltas=deltas,
        clusters=clusters,
        edge_estimates=edge_estimates,
        paper_results=tuple(paper_results),
        evidences=tuple(evidences),
        no_trade_reasons=tuple(dict.fromkeys(reason for reason in no_trade_reasons if reason)),
        raw_events_stored=raw_events_stored,
        persisted_counts=persisted_counts,
    )


def _estimate_edge(
    delta: LeaderDelta,
    event: LifecycleEvent,
    current_mid: float | None,
    leader_expected_edge_bps: float | None,
    cfg: V12DecisionPipelineConfig,
) -> EdgeNetV12Estimate:
    if delta.is_exit_or_reduce:
        # Exits are risk-reducing local paper actions. They still require a real
        # current mid, but they should not depend on a fresh entry edge estimate.
        return estimate_edge_net_v12(
            EdgeNetV12Inputs(
                leader_reference_price=event.price,
                current_mid=current_mid,
                leader_expected_edge_bps=max(cfg.min_edge_bps + 1.0, 1.0),
                spread_bps=cfg.spread_bps,
                slippage_bps=cfg.slippage_bps,
                fee_bps=cfg.fee_bps,
                funding_estimate_bps=cfg.funding_estimate_bps,
                min_edge_bps=0.0,
                max_copy_degradation_bps=cfg.max_copy_degradation_bps,
            )
        )
    return estimate_edge_net_v12(
        EdgeNetV12Inputs(
            leader_reference_price=event.price,
            current_mid=current_mid,
            leader_expected_edge_bps=leader_expected_edge_bps,
            spread_bps=cfg.spread_bps,
            slippage_bps=cfg.slippage_bps,
            fee_bps=cfg.fee_bps,
            latency_penalty_bps=cfg.latency_penalty_bps,
            copy_degradation_bps=cfg.copy_degradation_bps,
            liquidity_penalty_bps=cfg.liquidity_penalty_bps,
            volatility_penalty_bps=cfg.volatility_penalty_bps,
            adverse_selection_penalty_bps=cfg.adverse_selection_penalty_bps,
            crowding_penalty_bps=cfg.crowding_penalty_bps,
            funding_estimate_bps=cfg.funding_estimate_bps,
            min_edge_bps=cfg.min_edge_bps,
            max_copy_degradation_bps=cfg.max_copy_degradation_bps,
        )
    )


def _mid_for(coin: str, mids: dict[str, float]) -> float | None:
    value = mids.get(coin.upper(), mids.get(coin, None))
    try:
        parsed = None if value is None else float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed and parsed > 0 else None


def _raw_hash(payload: object) -> str:
    return sha256(repr(sorted(payload.items()) if isinstance(payload, dict) else payload).encode("utf-8")).hexdigest()


def _edge_id(delta: LeaderDelta) -> str:
    return "edge:" + sha256(delta.delta_id.encode("utf-8")).hexdigest()[:24]


__all__ = [
    "V12DecisionPipelineConfig",
    "V12DecisionPipelineInput",
    "V12DecisionPipelineResult",
    "run_v12_decision_pipeline",
]
