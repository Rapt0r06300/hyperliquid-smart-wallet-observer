from __future__ import annotations

import pytest

from hl_observer.event_intelligence.archive import EventIntelligenceArchive
from hl_observer.event_intelligence.coverage import IDEA_COVERAGE, coverage_summary
from hl_observer.event_intelligence.candidates import EventLeadLagCandidate
from hl_observer.event_intelligence.direct_sources import (
    DirectSourceError,
    DirectSourceReadOnlyClient,
    gdacs_query_params,
    gdelt_query_params,
    normalize_eonet,
    normalize_fred_observations,
    normalize_gdacs,
    normalize_gdelt_articles,
    normalize_usgs,
)
from hl_observer.event_intelligence.external_event import (
    ExternalEvent,
    ExternalEventType,
    SourceTier,
)
from hl_observer.event_intelligence.health import (
    coverage_by_family,
    detect_intelligence_gap,
)
from hl_observer.event_intelligence.macro import MacroEventClock, ScheduledMacroEvent
from hl_observer.event_intelligence.market_context import (
    AuxMarketMetrics,
    compare_event_market_context,
)
from hl_observer.event_intelligence.market_features import (
    MarketStateObservation,
    measure_event_market_features,
)
from hl_observer.event_intelligence.module_bridges import (
    LeaderAction,
    build_cross_venue_event_context,
    build_lead_lag_event_context,
    measure_copy_vault_event_reactions,
)
from hl_observer.event_intelligence.outcomes import EventCandidateMarkout
from hl_observer.event_intelligence.provenance import (
    cluster_external_events,
    score_provenance,
)
from hl_observer.event_intelligence.protocol import (
    assert_forward_after_freeze,
    freeze_event_research,
)
from hl_observer.event_intelligence.regimes import (
    EventRegime,
    classify_event_regime,
    map_event_to_assets,
)
from hl_observer.event_intelligence.scoreboard import (
    ScoredEventOutcome,
    build_event_scoreboard,
)
from hl_observer.event_intelligence.source_catalog import (
    ClassificationEnvelope,
    build_source_catalog,
    source_pair_role,
)
from hl_observer.event_intelligence.sequences import (
    PropagationStage,
    StageObservation,
    build_propagation_pattern,
    summarize_patterns,
)
from hl_observer.event_intelligence.validation import (
    EventStudyObservation,
    bootstrap_mean_ci,
    chronological_split,
    compare_source_latency,
    independent_event_count,
    bootstrap_mean_ci,
    compare_source_latency,
    market_session_utc,
    permute_event_labels,
    placebo_timestamps,
    purged_chronological_split,
    select_no_event_controls,
    stratify_numeric,
)
from hl_observer.event_intelligence.worldmonitor import WorldMonitorEvent
from hl_observer.collection.native_venue_market import MarketLevel, NativeMarketSnapshot
from hl_observer.event_intelligence.features import compute_entity_velocity


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _HTTP:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params):
        self.calls.append((url, dict(params)))
        return _Response(self.payload)


def _external(
    *,
    event_id: str = "evt-1",
    event_type: ExternalEventType = ExternalEventType.NEWS,
    ts: int = 1_000,
    entities: tuple[str, ...] = ("BTC",),
    revision: int = 0,
    supersedes_revision: int | None = None,
) -> ExternalEvent:
    return ExternalEvent(
        event_id=event_id,
        source="worldmonitor.news",
        event_type=event_type,
        source_tier=SourceTier.AGGREGATOR,
        retrieval_ts_ms=ts,
        ingest_ts_ms=ts,
        methodology_version="test-v1",
        raw_evidence_ref=f"ref:{event_id}:{revision}",
        entities=entities,
        classification_confidence=0.9,
        corroboration_count=2,
        revision=revision,
        supersedes_revision=supersedes_revision,
    )


def _wm(
    *,
    kind: str = "news",
    event_type: ExternalEventType = ExternalEventType.NEWS,
    ts: int = 1_000,
    entities: tuple[str, ...] = ("BTC",),
) -> WorldMonitorEvent:
    return WorldMonitorEvent(
        event=_external(event_type=event_type, ts=ts, entities=entities),
        kind=kind,
        publisher="Reuters",
        importance_score=80.0,
        credibility_score=90.0,
        coverage_state="complete",
    )


def _markout(
    *,
    event_id: str,
    ts: int,
    sample_net_bps: float,
    pnl: float,
) -> EventCandidateMarkout:
    return EventCandidateMarkout(
        event_id=event_id,
        event_kind="news",
        coin="BTC",
        direction="UPWARD_HL_LAG",
        decision_ts_ms=ts,
        horizon_ms=1_000,
        status="MEASURED",
        reason="EXECUTABLE_MARKOUT_MEASURED",
        entry_ts_ms=ts + 10,
        exit_ts_ms=ts + 1_010,
        entry_mid=100.0,
        exit_mid=100.1,
        entry_executable_px=100.01,
        exit_executable_px=100.09,
        gross_mid_bps=10.0,
        executable_markout_bps=8.0,
        spread_bps=2.0,
        fees_bps=1.0,
        slippage_bps=1.0,
        latency_bps=1.0,
        total_cost_bps=5.0,
        net_bps=sample_net_bps,
        notional_usd=50.0,
        net_pnl_usd=pnl,
        capacity_usd=500.0,
        fill_ratio=1.0,
        entry_latency_ms=10,
    )


def test_direct_source_client_is_allowlisted_and_fred_requires_key() -> None:
    fake = _HTTP({"observations": []})
    client = DirectSourceReadOnlyClient(http_client=fake)

    with pytest.raises(DirectSourceError, match="FRED_API_KEY_REQUIRED"):
        client.get_json("fred", params={"series_id": "CPIAUCSL"})

    with pytest.raises(ValueError, match="DIRECT_SOURCE_NOT_ALLOWLISTED"):
        client.get_json("unknown")

    result = client.get_json("usgs_earthquakes")
    assert result == {"observations": []}
    assert fake.calls
    assert client.real_execution is False


def test_usgs_eonet_gdacs_gdelt_and_fred_normalize_to_external_events() -> None:
    usgs = normalize_usgs(
        {
            "features": [
                {
                    "id": "quake-1",
                    "properties": {
                        "mag": 6.0,
                        "time": 900,
                        "updated": 950,
                        "place": "Test Region",
                        "url": "https://example.test/q",
                    },
                }
            ]
        },
        received_ts_ms=1_000,
    )
    assert usgs[0].event_type == ExternalEventType.NATURAL
    assert usgs[0].available_ts_ms == 1_000

    eonet = normalize_eonet(
        {
            "events": [
                {
                    "id": "EONET_1",
                    "link": "https://example.test/e",
                    "categories": [{"id": "severeStorms"}],
                    "geometry": [{"date": "1970-01-01T00:00:00.900Z"}],
                }
            ]
        },
        received_ts_ms=1_000,
    )
    assert eonet[0].event_type == ExternalEventType.WEATHER

    gdacs = normalize_gdacs(
        {
            "features": [
                {
                    "properties": {
                        "eventid": "123",
                        "eventtype": "TC",
                        "alertlevel": "Red",
                        "country": "Testland",
                        "fromdate": "1970-01-01T00:00:00.800+00:00",
                    }
                }
            ]
        },
        received_ts_ms=1_000,
    )
    assert gdacs[0].severity == pytest.approx(1.0)

    gdelt = normalize_gdelt_articles(
        {
            "articles": [
                {
                    "url": "https://example.test/news",
                    "seendate": "19700101T000000Z",
                    "domain": "example.test",
                    "language": "English",
                }
            ]
        },
        received_ts_ms=1_000,
    )
    assert gdelt[0].event_type == ExternalEventType.NEWS

    fred = normalize_fred_observations(
        {"observations": [{"date": "2026-09-01", "value": "2.9"}]},
        received_ts_ms=1_000,
        series_id="CPIAUCSL",
    )
    assert fred[0].event_type == ExternalEventType.MACRO
    assert "CPIAUCSL" in fred[0].entities


def test_direct_source_query_helpers_are_bounded() -> None:
    gdelt = gdelt_query_params("bitcoin", max_records=999)
    assert gdelt["maxrecords"] == 250
    assert gdelt["timespan"] == "15min"

    gdacs = gdacs_query_params(event_types=("EQ", "TC"), alert_levels=("red",))
    assert gdacs["eventlist"] == "EQ;TC"
    assert gdacs["alertlevel"] == "red"


def test_event_revisions_have_distinct_dedupe_keys_and_archive_records(tmp_path) -> None:
    first = _external(revision=0)
    corrected = _external(revision=1, supersedes_revision=0)
    assert first.dedupe_key != corrected.dedupe_key

    archive = EventIntelligenceArchive(tmp_path / "events.jsonl")
    assert archive.append(WorldMonitorEvent(event=first, kind="news")).appended
    assert archive.append(WorldMonitorEvent(event=corrected, kind="news")).appended
    assert archive.count == 2

    reopened = EventIntelligenceArchive(tmp_path / "events.jsonl")
    assert reopened.count == 2


def test_event_regime_is_causal_and_never_backfills_late_news() -> None:
    event = _wm(event_type=ExternalEventType.GEOPOLITICAL)
    label = classify_event_regime(
        event,
        market_moved=True,
        event_available_before_move=False,
    )
    assert label.regime == EventRegime.MICROSTRUCTURE_LED

    label = classify_event_regime(
        event,
        market_moved=True,
        event_available_before_move=True,
    )
    assert label.regime == EventRegime.GEOPOLITICAL_LED


def test_asset_relevance_uses_direct_entities_and_context_only() -> None:
    event = _wm(
        event_type=ExternalEventType.CYBER,
        entities=("SOL", "exchange"),
    )
    relevance = map_event_to_assets(
        event,
        available_assets=("BTC", "ETH", "SOL", "USDC"),
    )
    assert "SOL" in relevance.assets
    assert "BTC" in relevance.assets
    assert "infrastructure" in relevance.categories


def test_macro_clock_separates_pre_event_and_post_release_surprise() -> None:
    event = ScheduledMacroEvent(
        event_id="cpi-1",
        name="CPI",
        scheduled_ts_ms=10_000,
        source="official",
        expected_value=3.0,
        actual_value=3.3,
        released_ts_ms=10_050,
    )
    clock = MacroEventClock([event])
    pre = clock.nearest_window(as_of_ms=9_900, pre_window_ms=500)
    assert pre is not None and pre.phase == "PRE_EVENT"

    post = clock.nearest_window(as_of_ms=10_100, post_window_ms=500)
    assert post is not None and post.phase == "POST_RELEASE"
    assert post.surprise_score == pytest.approx(0.1)


def test_freeze_contract_blocks_pre_freeze_forward_rows() -> None:
    freeze = freeze_event_research(
        {"threshold_bps": 5.0, "window_ms": 30_000},
        training_cutoff_ms=10_000,
        created_at_ms=11_000,
        methodology_version="v1",
    )
    assert len(freeze.config_sha256) == 64
    with pytest.raises(ValueError, match="FORWARD_OBSERVATION_NOT_POST_FREEZE"):
        assert_forward_after_freeze(freeze, observation_ts_ms=10_000)
    assert_forward_after_freeze(freeze, observation_ts_ms=10_001)


def test_no_event_placebo_purge_and_label_permutation_are_deterministic() -> None:
    controls = select_no_event_controls(
        event_timestamps_ms=(1_000, 5_000),
        candidate_timestamps_ms=(500, 1_100, 2_000, 6_000),
        exclusion_window_ms=200,
    )
    assert controls == (500, 2_000, 6_000)

    placebos = placebo_timestamps(
        (10_000,),
        shifts_ms=(-2_000, 2_000),
        minimum_separation_ms=100,
    )
    assert placebos == (8_000, 12_000)

    rows = tuple(
        EventStudyObservation(
            observation_id=str(i),
            ts_ms=i * 1_000,
            end_ts_ms=i * 1_000 + (2_000 if i == 2 else 100),
            event_family="news" if i % 2 else "prediction",
            asset="BTC",
            net_bps=1.0,
            net_pnl_usd=0.01,
        )
        for i in range(1, 7)
    )
    split = chronological_split(rows, train_fraction=0.5, oos_fraction=0.25)
    assert split.train and split.oos and split.forward

    purged = purged_chronological_split(
        rows,
        train_fraction=0.5,
        oos_fraction=0.25,
    )
    assert len(purged.train) <= len(split.train)

    perm_a = permute_event_labels(rows, seed=7)
    perm_b = permute_event_labels(rows, seed=7)
    assert [row.event_family for row in perm_a] == [
        row.event_family for row in perm_b
    ]
    assert [row.net_bps for row in perm_a] == [row.net_bps for row in rows]


def test_sessions_and_independence_count_support_robustness_slices() -> None:
    assert market_session_utc(2 * 3_600_000) == "ASIA"
    assert market_session_utc(10 * 3_600_000) == "EUROPE"
    assert market_session_utc(16 * 3_600_000) == "US"

    rows = [
        EventStudyObservation("a", 1_000, "news", "BTC", 1.0, 0.01),
        EventStudyObservation("b", 1_100, "news", "BTC", 2.0, 0.02),
        EventStudyObservation("c", 10_000, "news", "BTC", 3.0, 0.03),
    ]
    assert independent_event_count(rows, independence_window_ms=500) == 2


def test_event_scoreboard_reuses_canonical_cost_and_oos_rules() -> None:
    rows = [
        ScoredEventOutcome(_markout(event_id="a", ts=1_000, sample_net_bps=5.0, pnl=0.03), "news", sample="train"),
        ScoredEventOutcome(_markout(event_id="b", ts=10_000, sample_net_bps=4.0, pnl=0.02), "news", sample="oos"),
        ScoredEventOutcome(_markout(event_id="c", ts=20_000, sample_net_bps=3.0, pnl=0.01), "news", sample="forward"),
    ]
    controls = [
        EventStudyObservation("ctrl", 30_000, "news", "BTC", 0.5, 0.001)
    ]
    placebos = [
        EventStudyObservation("pl", 40_000, "news", "BTC", 0.2, 0.001)
    ]
    bundle = build_event_scoreboard(
        rows,
        strategy="event-intel",
        event_family="news",
        asset="BTC",
        controls=controls,
        placebos=placebos,
        roi_denominator_usd=1_000.0,
    )
    assert bundle.measured_count == 3
    assert bundle.scoreboard.costs_bps == pytest.approx(5.0)
    assert bundle.scoreboard.oos_net_bps == pytest.approx(4.0)
    assert bundle.scoreboard.forward_net_bps == pytest.approx(3.0)
    assert bundle.scoreboard.verdict == "MORE_DATA"
    assert bundle.incremental.incremental_vs_control_bps is not None


def test_module_bridges_do_not_bypass_native_economics() -> None:
    event = _wm()
    candidate = EventLeadLagCandidate(
        event_id=event.event.event_id,
        event_kind="news",
        coin="BTC",
        decision_ts_ms=1_100,
        status="CANDIDATE",
        reason="EVENT_CONFIRMED_EXECUTABLE_LAG",
        event_age_ms=100,
        leader_venue="binance",
        confirming_venues=("binance",),
        research_direction="UPWARD_HL_LAG",
        net_room_bps=2.0,
    )
    lead = build_lead_lag_event_context(
        event,
        candidate,
        available_assets=("BTC", "ETH"),
    )
    assert lead.replay_eligible is True
    assert lead.may_bypass_native_economics is False

    cross = build_cross_venue_event_context(
        event,
        decision_ts_ms=1_200,
        available_assets=("BTC", "ETH"),
    )
    assert cross.filter_only is True
    assert cross.may_bypass_costs is False
    assert cross.may_bypass_capacity is False


def test_copy_vault_event_reaction_stats_measure_leader_speed_not_motive() -> None:
    event = _wm(ts=1_000, entities=("BTC",))
    stats = measure_copy_vault_event_reactions(
        [event],
        [
            LeaderAction("leader-a", 1_500, "BTC", "BUY"),
            LeaderAction("leader-b", 2_500, "BTC", "BUY"),
        ],
        event_family="news",
        market_first_reaction_ms={event.event.event_id: 2_000},
        max_reaction_ms=5_000,
        fast_threshold_ms=1_000,
    )
    assert stats["leader-a"].median_reaction_ms == pytest.approx(500)
    assert stats["leader-a"].reacted_before_market_ratio == pytest.approx(1.0)
    assert stats["leader-b"].reacted_before_market_ratio == pytest.approx(0.0)


def test_propagation_patterns_capture_prediction_news_market_hl_sequence() -> None:
    pattern = build_propagation_pattern(
        [
            StageObservation(PropagationStage.PREDICTION, 1_000),
            StageObservation(PropagationStage.NEWS, 2_000),
            StageObservation(PropagationStage.MARKET_LEADER, 2_100),
            StageObservation(PropagationStage.HYPERLIQUID, 2_300),
        ]
    )
    assert pattern is not None
    assert pattern.causal is True
    assert pattern.total_latency_ms == 1_300
    assert pattern.inter_stage_ms == (1_000, 100, 200)

    stats = summarize_patterns([pattern])
    assert stats[pattern.pattern_id].observations == 1



def test_retained_idea_registry_is_exactly_120_and_all_implemented() -> None:
    summary = coverage_summary()
    assert summary["count"] == 120
    assert summary["min_id"] == 1
    assert summary["max_id"] == 120
    assert summary["unique_ids"] == 120
    assert summary["all_implemented"] is True
    assert [row.idea_id for row in IDEA_COVERAGE] == list(range(1, 121))
    assert all(row.component for row in IDEA_COVERAGE)


def test_source_catalog_is_versioned_unique_read_only_and_evidence_bound() -> None:
    catalog = build_source_catalog(version="test-v1")
    assert catalog.version == "test-v1"
    assert len(catalog.source_ids) == len(set(catalog.source_ids))
    assert "worldmonitor.news" in catalog.source_ids
    assert "usgs_earthquakes" in catalog.source_ids

    primary = catalog.get("usgs_earthquakes")
    aggregator = catalog.get("worldmonitor.news")
    assert primary is not None and primary.primary is True
    assert aggregator is not None and aggregator.primary is False
    assert primary.read_only is True
    assert aggregator.read_only is True
    assert source_pair_role(primary, aggregator) == (
        "PRIMARY_SPEED_PLUS_AGGREGATOR_CORROBORATION"
    )

    with pytest.raises(ValueError, match="source evidence refs"):
        ClassificationEnvelope(
            label="macro_shock",
            confidence=0.8,
            methodology_version="v1",
            evidence_refs=(),
            model_id="classifier-v1",
        )

    envelope = ClassificationEnvelope(
        label="macro_shock",
        confidence=0.8,
        methodology_version="v1",
        evidence_refs=("fred:CPI:2026-09",),
        model_id="classifier-v1",
    )
    assert envelope.evidence_refs == ("fred:CPI:2026-09",)


def test_event_market_features_measure_spread_depth_ofi_oi_funding_and_liquidations() -> None:
    rows = [
        MarketStateObservation(
            ts_ms=900,
            venue="hyperliquid",
            asset="BTC",
            bid=99.99,
            ask=100.01,
            bid_depth_usd=500.0,
            ask_depth_usd=500.0,
            aggressive_buy_usd=100.0,
            aggressive_sell_usd=100.0,
            open_interest_usd=1_000_000.0,
            funding_rate=0.0001,
            liquidation_long_usd=0.0,
            liquidation_short_usd=0.0,
        ),
        MarketStateObservation(
            ts_ms=1_100,
            venue="hyperliquid",
            asset="BTC",
            bid=99.95,
            ask=100.05,
            bid_depth_usd=250.0,
            ask_depth_usd=250.0,
            aggressive_buy_usd=300.0,
            aggressive_sell_usd=100.0,
            open_interest_usd=1_050_000.0,
            funding_rate=0.0002,
            liquidation_long_usd=25_000.0,
            liquidation_short_usd=5_000.0,
        ),
    ]
    delta = measure_event_market_features(
        rows,
        event_ts_ms=1_000,
        venue="hyperliquid",
        asset="BTC",
        pre_window_ms=500,
        post_window_ms=500,
    )
    assert delta is not None
    assert delta.spread_expansion_bps is not None
    assert delta.spread_expansion_bps > 0
    assert delta.depth_change_usd == pytest.approx(-500.0)
    assert delta.depth_withdrawal_ratio == pytest.approx(0.5)
    assert delta.order_flow_imbalance_change == pytest.approx(0.5)
    assert delta.aggressive_volume_change_usd == pytest.approx(200.0)
    assert delta.open_interest_change_usd == pytest.approx(50_000.0)
    assert delta.funding_change == pytest.approx(0.0001)
    assert delta.liquidation_long_change_usd == pytest.approx(25_000.0)
    assert delta.liquidation_short_change_usd == pytest.approx(5_000.0)


def test_source_latency_bootstrap_and_numeric_slices_are_causal_research_tools() -> None:
    primary = ExternalEvent(
        event_id="same",
        source="usgs.earthquakes",
        event_type=ExternalEventType.NATURAL,
        source_tier=SourceTier.PRIMARY_OFFICIAL,
        retrieval_ts_ms=1_000,
        ingest_ts_ms=1_000,
        methodology_version="v1",
        raw_evidence_ref="primary",
    )
    aggregator = ExternalEvent(
        event_id="same",
        source="worldmonitor.cross_source",
        event_type=ExternalEventType.NATURAL,
        source_tier=SourceTier.AGGREGATOR,
        retrieval_ts_ms=1_500,
        ingest_ts_ms=1_500,
        methodology_version="v1",
        raw_evidence_ref="wm",
    )
    comparison = compare_source_latency(primary, aggregator)
    assert comparison.aggregator_lag_ms == 500

    ci = bootstrap_mean_ci([1.0, 2.0, 3.0, 4.0], resamples=500, seed=7)
    assert ci is not None
    assert ci[0] <= 2.5 <= ci[1]

    rows = [
        EventStudyObservation(
            "a", 1_000, "news", "BTC", 1.0, 0.01, velocity_zscore=0.5
        ),
        EventStudyObservation(
            "b", 2_000, "news", "BTC", 2.0, 0.02, velocity_zscore=4.0
        ),
    ]
    slices = stratify_numeric(
        rows,
        field="velocity_zscore",
        thresholds=(1.0, 3.0),
    )
    assert sum(len(group) for group in slices.values()) == 2



def test_provenance_cluster_counts_independent_sources_and_triangulation() -> None:
    primary = ExternalEvent(
        event_id="same-story-primary",
        source="official",
        event_type=ExternalEventType.GEOPOLITICAL,
        source_tier=SourceTier.PRIMARY_OFFICIAL,
        retrieval_ts_ms=1_000,
        ingest_ts_ms=1_000,
        methodology_version="v1",
        raw_evidence_ref="official:1",
        entities=("BTC",),
        regions=("MENA",),
    )
    wire = ExternalEvent(
        event_id="same-story-wire",
        source="wire",
        event_type=ExternalEventType.GEOPOLITICAL,
        source_tier=SourceTier.WIRE,
        retrieval_ts_ms=1_100,
        ingest_ts_ms=1_100,
        methodology_version="v1",
        raw_evidence_ref="wire:1",
        entities=("BTC",),
        regions=("MENA",),
    )
    score = score_provenance([primary, wire])
    assert score.independent_sources == 2
    assert score.triangulated is True
    assert score.corroboration_latency_ms == 100

    clusters = cluster_external_events([primary, wire], time_bucket_ms=5_000)
    assert len(clusters) == 1
    assert clusters[0].provenance.independent_sources == 2


def test_health_tracks_gaps_and_family_coverage() -> None:
    gap = detect_intelligence_gap(
        source="gdelt",
        last_success_ms=1_000,
        now_ms=3_000,
        max_age_ms=500,
        fetch_ok=True,
    )
    assert gap is not None
    assert gap.reason == "SOURCE_STALE"

    report = coverage_by_family(
        [_wm(kind="news")],
        expected_families=("news", "prediction", "cross_source"),
    )
    assert report.coverage_ratio == pytest.approx(1 / 3)
    assert set(report.missing_families) == {"prediction", "cross_source"}


def test_primary_vs_worldmonitor_latency_is_measured_not_assumed() -> None:
    primary = _external(ts=1_000)
    aggregator = ExternalEvent(
        event_id="agg",
        source="worldmonitor",
        event_type=ExternalEventType.NEWS,
        source_tier=SourceTier.AGGREGATOR,
        retrieval_ts_ms=1_250,
        ingest_ts_ms=1_250,
        methodology_version="v1",
        raw_evidence_ref="agg:1",
    )
    comparison = compare_source_latency(primary, aggregator)
    assert comparison.aggregator_lag_ms == 250


def test_bootstrap_ci_and_numeric_strata_are_deterministic() -> None:
    ci_a = bootstrap_mean_ci([1.0, 2.0, 3.0, 4.0], resamples=200, seed=4)
    ci_b = bootstrap_mean_ci([1.0, 2.0, 3.0, 4.0], resamples=200, seed=4)
    assert ci_a == ci_b
    assert ci_a is not None and ci_a[0] <= 2.5 <= ci_a[1]

    rows = [
        EventStudyObservation(
            "a", 1_000, "news", "BTC", 1.0, 0.01, velocity_zscore=0.5
        ),
        EventStudyObservation(
            "b", 2_000, "news", "BTC", 1.0, 0.01, velocity_zscore=3.0
        ),
    ]
    groups = stratify_numeric(rows, field="velocity_zscore", thresholds=(1.0, 2.0))
    assert sum(len(value) for value in groups.values()) == 2


def test_entity_velocity_detects_entity_specific_spike() -> None:
    rows = []
    for index in range(8):
        ts = 1_000 + index * 1_000
        rows.append(_wm(ts=ts, entities=("BTC",)))
    rows.extend(
        [
            _wm(ts=10_100, entities=("BTC",)),
            _wm(ts=10_200, entities=("BTC",)),
            _wm(ts=10_300, entities=("BTC",)),
        ]
    )
    signal = compute_entity_velocity(
        rows,
        as_of_ms=10_500,
        entity="BTC",
        short_window_ms=1_000,
        baseline_window_ms=8_000,
    )
    assert signal.current_mentions == 3
    assert signal.entity == "BTC"


def test_market_context_measures_spread_depth_obi_oi_funding_and_liquidations() -> None:
    pre = NativeMarketSnapshot.build(
        venue="hyperliquid",
        coin="BTC",
        exchange_symbol="BTC",
        bid=99.9,
        ask=100.1,
        exchange_ts_ms=900,
        receive_ts_ms=900,
        now_ms=900,
        bids=(MarketLevel(99.9, 2.0),),
        asks=(MarketLevel(100.1, 1.0),),
        volume_24h=1_000.0,
        open_interest=500.0,
        funding_rate=0.0001,
    )
    post = NativeMarketSnapshot.build(
        venue="hyperliquid",
        coin="BTC",
        exchange_symbol="BTC",
        bid=99.8,
        ask=100.2,
        exchange_ts_ms=1_100,
        receive_ts_ms=1_100,
        now_ms=1_100,
        bids=(MarketLevel(99.8, 1.0),),
        asks=(MarketLevel(100.2, 3.0),),
        volume_24h=1_200.0,
        open_interest=550.0,
        funding_rate=0.0002,
    )
    delta = compare_event_market_context(
        pre,
        post,
        pre_aux=AuxMarketMetrics(
            aggressive_buy_usd=100,
            aggressive_sell_usd=80,
            liquidation_usd=10,
        ),
        post_aux=AuxMarketMetrics(
            aggressive_buy_usd=200,
            aggressive_sell_usd=50,
            liquidation_usd=60,
        ),
    )
    assert delta.spread_delta_bps > 0
    assert delta.bid_depth_delta_usd < 0
    assert delta.ask_depth_delta_usd > 0
    assert delta.obi_delta is not None
    assert delta.open_interest_delta == pytest.approx(50.0)
    assert delta.funding_rate_delta == pytest.approx(0.0001)
    assert delta.aggressive_flow_delta_usd == pytest.approx(130.0)
    assert delta.liquidation_delta_usd == pytest.approx(50.0)
