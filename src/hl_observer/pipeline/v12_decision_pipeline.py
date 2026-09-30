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
from hl_observer.gating.filter_pipeline import ContexteDecision, appliquer_filtres
from hl_observer.risk.drawdown_scaling import facteur_capital
from hl_observer.models import DataQuality, Fill, SourceMeta
from hl_observer.normalization.fills import NormalizedFillResult, normalize_hyperliquid_fill
from hl_observer.paper_trading.execution_truth import ExecutionTruth
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
    top_depth_usdt: float | None = None
    wallet_score: float = 90.0
    signal_score: float = 85.0
    min_feed_quality_score: float = 75.0
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
    # --- Entrées OPTIONNELLES pour ACTIVER les gardes armés (X2). Absentes → garde en abstention. ---
    wallet_stats: dict[str, Any] | None = None            # G5 : winrate/pnl/n_trades → structurel ?
    reference_mids: dict[str, float] = field(default_factory=dict)   # G4 : prix de référence stale-tick
    edge_history_by_coin: dict[str, dict[str, float]] = field(default_factory=dict)  # S4 : {coin:{hist,recent}}
    execution_truth_by_coin: dict[str, ExecutionTruth] = field(default_factory=dict)


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
        etat_moteur = _etat_moteur(engine)                       # capital/marge/drawdown RÉELS (X2/X3)
        edge, gardes_ctx = _appliquer_gardes(edge, delta, mid, pipeline_input, cfg, etat_moteur)
        margin_scale = _facteur_sizing(etat_moteur)              # X3 : réduit la taille en drawdown
        edge_estimates[delta.delta_id] = edge
        if store is not None:
            store.upsert_edge_estimate(_edge_id(delta), edge, created_at_ms=pipeline_input.observed_at_ms)

        enriched_delta = delta
        if edge.reason_codes:
            enriched_delta = replace(delta, reason_codes=tuple(dict.fromkeys((*delta.reason_codes, *edge.reason_codes))))
        market_price = float(mid or 0.0)
        execution_truth = pipeline_input.execution_truth_by_coin.get(delta.coin.upper())
        measured_spread_bps = (
            execution_truth.spread_bps
            if execution_truth is not None
            else float(cfg.spread_bps or 0.0)
        )
        paper_result = engine.apply_delta(
            enriched_delta,
            market_price=market_price,
            observed_at_ms=pipeline_input.observed_at_ms,
            edge_remaining_bps=float(edge.net_edge_bps or 0.0),
            spread_bps=measured_spread_bps,
            estimated_slippage_bps=float(cfg.slippage_bps or 0.0),
            top_depth_usdt=cfg.top_depth_usdt,
            wallet_score=cfg.wallet_score,
            signal_score=cfg.signal_score,
            marks={delta.coin: market_price} if market_price > 0 else {},
            margin_scale=margin_scale,
            decision_context=gardes_ctx,
            execution_truth=execution_truth,
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


def _etat_moteur(engine: PaperEngine) -> dict[str, float | None]:
    """Capital, marge utilisée et drawdown DÉRIVÉS de l'état RÉEL du moteur paper (jamais devinés).
    Évolue au fil des ouvertures/fermetures dans la même passe → dé-risquage dynamique honnête."""
    cash = float(getattr(engine, "cash_usdt", 0.0) or 0.0)
    realized = float(getattr(engine, "realized_pnl_usdt", 0.0) or 0.0)
    equity = cash + realized                                  # approx. : unrealized capté à la clôture
    hw = float(getattr(engine, "_high_water_equity", equity) or equity)
    drawdown = 0.0 if hw <= 0 else max(0.0, (hw - equity) / hw)
    ecfg = getattr(engine, "config", None)
    levier = max(1.0, float(getattr(ecfg, "leverage", 1.0) or 1.0))
    cap = getattr(ecfg, "max_total_exposure_usdt", None)
    capital = float(cap) if isinstance(cap, (int, float)) and cap > 0 else None
    try:
        marge = sum(float(getattr(p, "notional_usdt", 0.0) or 0.0) for p in engine.positions) / levier
    except Exception:  # noqa: BLE001 — l'absence d'état positions ne casse jamais la décision
        marge = None
    return {"capital": capital, "marge_utilisee": marge, "drawdown_frac": drawdown}


def _facteur_sizing(etat: dict[str, float | None]) -> float:
    """X3 — facteur de taille CONSOMMÉ via margin_scale (pas mesuré puis jeté). En drawdown, la
    taille rétrécit continûment (drawdown_scaling.facteur_capital). drawdown 0 → 1.0 (neutre)."""
    dd = etat.get("drawdown_frac")
    if dd is None:
        return 1.0
    return float(facteur_capital(float(dd)))


def _appliquer_gardes(
    edge: EdgeNetV12Estimate,
    delta: LeaderDelta,
    current_mid: float | None,
    pipeline_input: "V12DecisionPipelineInput",
    cfg: V12DecisionPipelineConfig,
    etat: dict[str, float | None],
) -> tuple[EdgeNetV12Estimate, dict[str, object]]:
    """Applique le pipeline de FILTRES P1 à l'ENTRÉE. Un refus applicable dégrade l'edge SOUS le
    plancher → NO_TRADE par le MÊME chemin que l'edge (deny-by-default), motif dans reason_codes
    (→ evidence + no_trade_reasons). Les SORTIES ne sont jamais filtrées. On ne fabrique rien :
    une entrée absente laisse le garde correspondant en abstention. Retourne (edge, contexte_gardes)."""
    if delta.is_exit_or_reduce:
        return edge, {"gardes_sortie": True}
    coin = str(delta.coin).upper()
    univers = tuple(str(k).upper() for k in pipeline_input.market_mids.keys())
    age_s: float | None = None
    if pipeline_input.source_ts_ms is not None:
        # âge = horodatage local d'observation − horodatage venue de la donnée (fraîcheur réelle).
        age_s = max(0.0, (float(pipeline_input.observed_at_ms) - float(pipeline_input.source_ts_ms)) / 1000.0)
    ref = (pipeline_input.reference_mids or {}).get(coin, (pipeline_input.reference_mids or {}).get(str(delta.coin)))
    hist = (pipeline_input.edge_history_by_coin or {}).get(coin, {}) or {}
    ctx = ContexteDecision(
        coin=coin,
        est_sortie=False,
        univers=univers,
        ts_ms=pipeline_input.observed_at_ms,
        wallet=str(pipeline_input.wallet),
        mid=current_mid,
        age_signal_s=age_s,
        wallet_stats=pipeline_input.wallet_stats,                # G5 (actif si le caller le fournit)
        prix_reference=float(ref) if isinstance(ref, (int, float)) else None,  # G4
        marge_utilisee=etat.get("marge_utilisee"),               # S6 (actif depuis l'état moteur)
        capital=etat.get("capital"),
        edge_hist_bps=float(hist["hist"]) if isinstance(hist.get("hist"), (int, float)) else None,  # S4
        edge_recent_bps=float(hist["recent"]) if isinstance(hist.get("recent"), (int, float)) else None,
    )
    res = appliquer_filtres(ctx)
    contexte: dict[str, object] = {
        "gardes_refus": list(res.refus),
        "gardes_abstentions": list(res.abstentions),
    }
    if res.notes:
        contexte["gardes_notes"] = res.notes
    if res.accepte:
        return edge, contexte
    plancher = float(getattr(edge, "threshold_bps", cfg.min_edge_bps) or cfg.min_edge_bps)
    net_degrade = min(float(edge.net_edge_bps or 0.0), -abs(plancher) - 1.0)
    reasons = tuple(dict.fromkeys((*edge.reason_codes, *res.refus)))
    return replace(edge, accepted=False, net_edge_bps=net_degrade, reason_codes=reasons), contexte


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
