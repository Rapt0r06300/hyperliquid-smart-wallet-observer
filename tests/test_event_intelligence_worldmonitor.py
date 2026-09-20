from __future__ import annotations

from dataclasses import replace

import pytest

from hl_observer.event_intelligence import (
    ExternalEvent,
    ExternalEventType,
    PredictionShiftTracker,
    SourceTier,
    WorldMonitorAuthRequired,
    WorldMonitorEvent,
    WorldMonitorHTTPError,
    WorldMonitorReadOnlyClient,
    compute_news_flow_features,
    compute_news_velocity_zscore,
    normalize_cross_source_signals,
    normalize_news_digest,
)
from hl_observer.event_intelligence.worldmonitor import (
    CROSS_SOURCE_PATH,
    NEWS_DIGEST_PATH,
    PREDICTION_PATH,
)


class _FakeResponse:
    def __init__(self, payload, *, status_code: int = 200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload


class _FakeHTTP:
    def __init__(self, payload, *, status_code: int = 200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.calls = []

    def get(self, url, *, params, headers):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return _FakeResponse(
            self.payload,
            status_code=self.status_code,
            headers=self.headers,
        )


def _digest_item(
    *,
    source: str,
    title: str,
    link: str,
    published_at: int,
    first_seen: int,
    phase: str = "STORY_PHASE_BREAKING",
    corroboration: int = 1,
    source_count: int = 1,
    importance: int = 80,
    credibility: int = 90,
    category: str = "economic",
) -> dict:
    return {
        "source": source,
        "title": title,
        "link": link,
        "publishedAt": published_at,
        "isAlert": True,
        "importanceScore": importance,
        "credibilityScore": credibility,
        "corroborationCount": corroboration,
        "storyMeta": {
            "firstSeen": first_seen,
            "mentionCount": 2,
            "sourceCount": source_count,
            "phase": phase,
        },
        "threat": {
            "level": "THREAT_LEVEL_HIGH",
            "category": category,
            "confidence": 0.9,
            "source": "llm",
        },
        "locationName": "Global",
        "snippet": "THIS SOURCE TEXT MUST NEVER ENTER THE ARCHIVE RECORD",
        "tickers": ["BTC", "ETH"],
    }


def _news_row(event_id: str, *, ts_ms: int, publisher: str) -> WorldMonitorEvent:
    event = ExternalEvent(
        event_id=event_id,
        source="worldmonitor.news",
        event_type=ExternalEventType.NEWS,
        source_tier=SourceTier.AGGREGATOR,
        retrieval_ts_ms=ts_ms,
        ingest_ts_ms=ts_ms,
        methodology_version="test-v1",
        raw_evidence_ref=f"ref:{event_id}",
    )
    return WorldMonitorEvent(
        event=event,
        kind="news",
        publisher=publisher,
        story_phase="STORY_PHASE_BREAKING",
        source_count=1,
        importance_score=80.0,
        credibility_score=90.0,
        coverage_state="complete",
    )


def test_hosted_client_requires_key_before_any_network_call() -> None:
    fake = _FakeHTTP({})
    client = WorldMonitorReadOnlyClient(http_client=fake)

    with pytest.raises(WorldMonitorAuthRequired, match="WORLDMONITOR_API_KEY_REQUIRED"):
        client.list_cross_source_signals()

    assert fake.calls == []
    assert client.real_execution is False


def test_client_uses_only_documented_get_paths_and_auth_header() -> None:
    fake = _FakeHTTP({"signals": []})
    client = WorldMonitorReadOnlyClient(api_key="wm_test", http_client=fake)

    assert client.list_cross_source_signals() == {"signals": []}
    call = fake.calls[-1]
    assert call["url"].endswith(CROSS_SOURCE_PATH)
    assert call["headers"]["X-WorldMonitor-Key"] == "wm_test"

    fake.payload = {"categories": {}}
    client.list_feed_digest(variant="full", lang="en")
    assert fake.calls[-1]["url"].endswith(NEWS_DIGEST_PATH)
    assert fake.calls[-1]["params"] == {"variant": "full", "lang": "en"}

    fake.payload = {"dataAvailable": True, "fetchedAt": 1, "markets": []}
    client.list_prediction_markets(page_size=999, category="crypto")
    assert fake.calls[-1]["url"].endswith(PREDICTION_PATH)
    assert fake.calls[-1]["params"]["page_size"] == 100
    assert fake.calls[-1]["params"]["category"] == "crypto"


def test_http_failures_are_fail_closed_without_leaking_key() -> None:
    fake = _FakeHTTP(
        {"error": "too many"},
        status_code=429,
        headers={"Retry-After": "12"},
    )
    client = WorldMonitorReadOnlyClient(api_key="wm_super_secret", http_client=fake)

    with pytest.raises(WorldMonitorHTTPError) as exc:
        client.list_cross_source_signals()

    message = str(exc.value)
    assert "WORLDMONITOR_HTTP_429" in message
    assert "retry_after=12" in message
    assert "wm_super_secret" not in message


def test_cross_source_signal_becomes_structured_external_event() -> None:
    rows = normalize_cross_source_signals(
        {
            "evaluatedAt": 2_000,
            "signals": [
                {
                    "id": "gps-1",
                    "type": "CROSS_SOURCE_SIGNAL_TYPE_GPS_JAMMING",
                    "theater": "Eastern Mediterranean",
                    "severity": "CROSS_SOURCE_SIGNAL_SEVERITY_HIGH",
                    "severityScore": 83.5,
                    "detectedAt": 1_900,
                    "contributingTypes": ["GPS_JAMMING", "MILITARY_FLIGHT_SURGE"],
                    "signalCount": 3,
                }
            ],
        },
        received_ts_ms=2_100,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.event.event_type == ExternalEventType.MILITARY
    assert row.event.event_ts_ms == 1_900
    assert row.event.ingest_ts_ms == 2_100
    assert row.event.corroboration_count == 3
    assert row.event.severity == pytest.approx(0.75)
    assert row.severity_score_raw == pytest.approx(83.5)
    assert row.signal_count == 3


def test_news_digest_keeps_quant_facts_but_never_archives_source_text() -> None:
    payload = {
        "coverage": {"state": "complete"},
        "categories": {
            "finance": {
                "items": [
                    _digest_item(
                        source="Reuters",
                        title="Central bank surprise",
                        link="https://example.test/a",
                        published_at=1_800,
                        first_seen=1_900,
                        corroboration=4,
                        source_count=3,
                    )
                ]
            }
        },
    }
    rows = normalize_news_digest(payload, received_ts_ms=2_000)

    assert len(rows) == 1
    row = rows[0]
    assert row.event.event_type == ExternalEventType.MACRO
    assert row.publisher == "Reuters"
    assert row.story_phase == "STORY_PHASE_BREAKING"
    assert row.event.corroboration_count == 4
    assert row.source_count == 3
    assert row.importance_score == 80
    assert row.credibility_score == 90
    assert row.usable_for_signal is True

    archive = row.to_archive_record()
    forbidden = {"title", "headline", "snippet", "body", "content", "summary", "text"}
    assert forbidden.isdisjoint(archive)
    assert "THIS SOURCE TEXT" not in repr(archive)
    assert archive["publisher"] == "Reuters"
    assert archive["story_phase"] == "STORY_PHASE_BREAKING"


def test_stale_news_is_preserved_as_evidence_but_excluded_from_signal_features() -> None:
    payload = {
        "coverage": {"state": "stale"},
        "categories": {
            "finance": {
                "items": [
                    _digest_item(
                        source="Reuters",
                        title="Old event",
                        link="https://example.test/stale",
                        published_at=1_000,
                        first_seen=1_100,
                    )
                ]
            }
        },
    }
    rows = normalize_news_digest(payload, received_ts_ms=2_000)

    assert len(rows) == 1
    assert rows[0].usable_for_signal is False
    features = compute_news_flow_features(rows, as_of_ms=2_000, window_ms=5_000)
    assert features.event_count == 0
    assert features.velocity_per_min == 0.0


def test_prediction_tracker_emits_only_causal_material_probability_shifts() -> None:
    tracker = PredictionShiftTracker(min_abs_delta_pp=5.0)
    first = {
        "dataAvailable": True,
        "fetchedAt": 1_000,
        "markets": [
            {
                "id": "market-1",
                "source": "MARKET_SOURCE_POLYMARKET",
                "yesPrice": 0.40,
                "volume": 250_000,
                "category": "crypto",
                "url": "https://example.test/prediction",
            }
        ],
    }
    assert tracker.observe(first, received_ts_ms=1_100) == []

    small = {
        **first,
        "fetchedAt": 2_000,
        "markets": [{**first["markets"][0], "yesPrice": 0.44}],
    }
    assert tracker.observe(small, received_ts_ms=2_100) == []

    material = {
        **first,
        "fetchedAt": 3_000,
        "markets": [{**first["markets"][0], "yesPrice": 0.51}],
    }
    rows = tracker.observe(material, received_ts_ms=3_100)
    assert len(rows) == 1
    row = rows[0]
    assert row.event.event_type == ExternalEventType.PREDICTION
    assert row.probability == pytest.approx(0.51)
    assert row.probability_delta_pp == pytest.approx(7.0)
    assert row.prediction_source == "MARKET_SOURCE_POLYMARKET"
    assert row.event.ingest_ts_ms == 3_100
    assert row.event.real_execution is False

    assert tracker.observe(material, received_ts_ms=3_200) == []
    assert tracker.observe(
        {"dataAvailable": False, "fetchedAt": 0, "markets": []},
        received_ts_ms=4_000,
    ) == []


def test_news_flow_measures_velocity_diversity_and_corroboration() -> None:
    rows = [
        _news_row("a", ts_ms=9_000, publisher="Reuters"),
        _news_row("b", ts_ms=9_100, publisher="AP"),
        replace(
            _news_row("c", ts_ms=9_200, publisher="Reuters"),
            event=replace(
                _news_row("c", ts_ms=9_200, publisher="Reuters").event,
                corroboration_count=4,
            ),
            source_count=3,
            is_alert=True,
        ),
        _news_row("c", ts_ms=9_200, publisher="Reuters"),
    ]

    features = compute_news_flow_features(
        rows,
        as_of_ms=10_000,
        window_ms=60_000,
    )
    assert features.event_count == 3
    assert features.unique_publishers == 2
    assert features.source_diversity_ratio == pytest.approx(2 / 3)
    assert features.corroborated_events == 1
    assert features.max_corroboration_count == 4
    assert features.alert_events == 1
    assert features.velocity_per_min == pytest.approx(3.0)
    assert features.corroborated_velocity_per_min == pytest.approx(6.0)


def test_velocity_zscore_uses_only_prior_ingest_buckets() -> None:
    short = 1_000
    baseline_buckets = 8
    as_of = 10_000
    baseline_start = as_of - short - baseline_buckets * short
    rows = []
    for index in range(baseline_buckets):
        count = 1 if index % 2 == 0 else 2
        for offset in range(count):
            rows.append(
                _news_row(
                    f"base-{index}-{offset}",
                    ts_ms=baseline_start + index * short + 100 + offset,
                    publisher=f"P{offset}",
                )
            )
    for index in range(5):
        rows.append(
            _news_row(
                f"current-{index}",
                ts_ms=as_of - 900 + index * 100,
                publisher=f"C{index}",
            )
        )

    signal = compute_news_velocity_zscore(
        rows,
        as_of_ms=as_of,
        short_window_ms=short,
        baseline_window_ms=baseline_buckets * short,
        minimum_baseline_buckets=8,
    )
    assert signal.status == "OK"
    assert signal.current_count == 5
    assert signal.baseline_bucket_count == 8
    assert signal.baseline_mean_count == pytest.approx(1.5)
    assert signal.baseline_std_count == pytest.approx(0.5)
    assert signal.zscore == pytest.approx(7.0)
