from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hl_observer.alerts.freshness import (
    DEGRADED_MAX_AGE_MS,
    DETECTION_TO_DISPLAY_SLO_MS,
    FRESHNESS_POLICY_VERSION,
)
from hl_observer.alerts.spine import (
    AlertSpinePaths,
    AlertValidationError,
    CanonicalAlertWriter,
    build_alert_proposal,
)


def _writer(root: Path, *, now_ms: int) -> CanonicalAlertWriter:
    return CanonicalAlertWriter(
        AlertSpinePaths.from_root(root / "alerts"),
        clock_ms=lambda: now_ms,
    )


def _proposal(
    sequence: int,
    *,
    category: str = "MARKET_EVENT",
    source_health_state: str = "HEALTHY",
    freshness_state: str = "FRESH",
    observed_at_ms: int = 1_000,
    fetch_delay_ms: int = 100,
    parsed_at_ms: int | None = 1_200,
    verified_at_ms: int = 1_300,
    source_event_time_ms: int = 500,
    source_publish_time_ms: int = 600,
    source_available_time_ms: int = 700,
) -> dict:
    return build_alert_proposal(
        producer_id="fresh-source",
        producer_epoch="freshness-epoch-1",
        producer_seq=sequence,
        source_id="fresh-wire",
        source_uri=f"https://example.invalid/fresh/{sequence}",
        source_content_hash=hashlib.sha256(f"fresh:{sequence}".encode()).hexdigest(),
        source_event_id=f"fresh-event-{sequence}",
        source_event_time_ms=source_event_time_ms,
        source_publish_time_ms=source_publish_time_ms,
        source_available_time_ms=source_available_time_ms,
        observed_at_ms=observed_at_ms,
        fetched_at_ms=observed_at_ms + fetch_delay_ms,
        parsed_at_ms=parsed_at_ms,
        verified_at_ms=verified_at_ms,
        category=category,
        headline=f"Freshness event {sequence}",
        dedup_key=None,
        entity_ids=["asset:btc"],
        normalized_tickers=["BTC"],
        source_health_state=source_health_state,
        freshness_state=freshness_state,
        deterministic_score_components={"freshness": 1.0},
        policy_version="freshness-admission.v1",
        ingestion_code_sha="f" * 40,
        payload={"sequence": sequence},
    )


def test_clocks_separes_et_metriques_de_latence_sont_exposes(tmp_path: Path) -> None:
    writer = _writer(tmp_path, now_ms=2_000)
    writer.producer("fresh-source").submit(_proposal(0))
    writer.process_pending()
    event = writer.read_ledger()[0]
    projection = writer.rebuild_projection(displayed_at_ms=3_000)
    state = projection["freshness"]["event_states"][event["event_id"]]

    assert event["source_event_time_ms"] == 500
    assert event["source_publish_time_ms"] == 600
    assert event["source_available_time_ms"] == 700
    assert event["observed_at_ms"] == 1_000
    assert event["fetched_at_ms"] == 1_100
    assert event["parsed_at_ms"] == 1_200
    assert event["verified_at_ms"] == 1_300
    assert event["admitted_at_ms"] == 2_000
    assert state["latency"] == {
        "source_to_observation_ms": 500,
        "availability_to_observation_ms": 300,
        "observation_to_fetch_ms": 100,
        "fetch_to_parse_ms": 100,
        "parse_to_verify_ms": 100,
        "verify_to_admit_ms": 700,
        "admit_to_projection_ms": 0,
        "detection_to_display_ms": 2_000,
    }
    assert state["display_slo_state"] == "MEETS_SLO"
    assert projection["freshness"]["schema_version"] == FRESHNESS_POLICY_VERSION


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"source_publish_time_ms": 400}, "SOURCE_PUBLISH_BEFORE_EVENT"),
        ({"source_available_time_ms": 550}, "SOURCE_AVAILABLE_BEFORE_PUBLISH"),
        ({"parsed_at_ms": 1_050}, "PARSED_TIMESTAMP_ORDER_INVALID"),
    ],
)
def test_clocks_impossibles_sont_refuses(
    overrides: dict[str, int],
    error: str,
) -> None:
    with pytest.raises(AlertValidationError, match=error):
        _proposal(0, **overrides)


def test_source_gelee_devient_stale_sans_faux_no_news(tmp_path: Path) -> None:
    writer = _writer(tmp_path, now_ms=2_000)
    writer.producer("fresh-source").submit(_proposal(0))
    writer.process_pending()

    frozen_now = 1_000 + DEGRADED_MAX_AGE_MS + 5_000
    frozen_projection = _writer(tmp_path, now_ms=frozen_now).rebuild_projection()
    source = frozen_projection["freshness"]["source_health"]["fresh-wire"]

    assert source["effective_health_state"] == "STALE"
    assert source["effective_freshness_state"] == "STALE"
    assert source["stale_source_duration_ms"] == 5_000
    assert frozen_projection["alerts"][0]["effective_source_health_state"] == "STALE"
    assert all(alert["category"] != "NO_NEWS" for alert in frozen_projection["alerts"])

    historical_no_news = _writer(tmp_path / "no-news", now_ms=2_000)
    historical_no_news.producer("fresh-source").submit(
        _proposal(0, category="NO_NEWS")
    )
    historical_no_news.process_pending()
    stale_no_news = _writer(tmp_path / "no-news", now_ms=frozen_now).rebuild_projection()
    assert stale_no_news["alerts"][0]["no_news_conclusion_valid"] is False

    with pytest.raises(
        AlertValidationError,
        match="NO_NEWS_REQUIRES_HEALTHY_FRESH_SOURCE",
    ):
        _proposal(
            1,
            category="NO_NEWS",
            source_health_state="STALE",
            freshness_state="STALE",
        )


def test_distributions_et_gap_rate_sont_calcules_par_source_et_categorie(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path, now_ms=3_000)
    writer.producer("fresh-source").submit(
        _proposal(0, fetch_delay_ms=100, parsed_at_ms=1_200)
    )
    writer.producer("fresh-source").submit(
        _proposal(2, fetch_delay_ms=300, parsed_at_ms=1_400, verified_at_ms=1_500)
    )
    writer.process_pending()
    projection = writer.rebuild_projection()
    source_metrics = projection["freshness"]["latency_distributions"]["source"][
        "fresh-wire"
    ]
    health = projection["freshness"]["source_health"]["fresh-wire"]

    assert source_metrics["observation_to_fetch_ms"] == {
        "count": 2,
        "p50_ms": 100,
        "p95_ms": 300,
        "p99_ms": 300,
    }
    assert health["gap_count"] == 1
    assert health["missed_poll_or_gap_rate"] == 0.333333


def test_slo_detection_affichage_signale_un_depassement(tmp_path: Path) -> None:
    writer = _writer(tmp_path, now_ms=2_000)
    writer.producer("fresh-source").submit(_proposal(0))
    writer.process_pending()
    displayed_at = 1_000 + DETECTION_TO_DISPLAY_SLO_MS + 1
    projection = writer.rebuild_projection(displayed_at_ms=displayed_at)
    event_id = writer.read_ledger()[0]["event_id"]

    assert projection["freshness"]["event_states"][event_id][
        "display_slo_state"
    ] == "BREACH"
