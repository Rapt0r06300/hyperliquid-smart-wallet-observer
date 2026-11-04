from __future__ import annotations

import pytest

from hl_observer.event_intelligence import (
    UNMEASURABLE,
    SourceCatalogSnapshot,
    SourceDescriptor,
    SourceTier,
    StockPointInTimeObservation,
    study_stock_data,
)


def _catalog(*sources: SourceDescriptor) -> SourceCatalogSnapshot:
    return SourceCatalogSnapshot(version="test-v1", sources=tuple(sources))


def _stock_source(*, read_only: bool = True) -> SourceDescriptor:
    return SourceDescriptor(
        source_id="stock.test",
        role="stock_market_data",
        source_tier=SourceTier.PRIMARY_OFFICIAL,
        access_mode="github_hosted_api_only",
        primary=True,
        enabled_by_default=False,
        refresh_hint_s=60,
        license_policy="TEST_ONLY",
        attribution="Test source",
        read_only=read_only,
    )


def test_current_catalog_stays_unmeasurable_without_stock_source_or_observation() -> None:
    report = study_stock_data(_catalog())

    assert report.status == UNMEASURABLE
    assert report.observation_count == 0
    assert report.point_in_time_ready is False
    assert report.no_lookahead is False
    assert report.deployed is False
    assert "NO_READ_ONLY_STOCK_SOURCE_REGISTERED" in report.reasons
    assert "NO_SAFE_POINT_IN_TIME_STOCK_OBSERVATIONS" in report.reasons
    assert report.real_execution is False
    assert report.read_only is True


def test_stock_study_accepts_only_causal_provenance_linked_observations() -> None:
    source = _stock_source()
    observation = StockPointInTimeObservation(
        source_id=source.source_id,
        symbol="TEST",
        observed_ts_ms=100,
        received_ts_ms=110,
        raw_evidence_ref="sha256:" + "a" * 64,
        consumer="research_only.stock_study",
    )

    report = study_stock_data(_catalog(source), observations=[observation])

    assert report.status == "PROVEN"
    assert report.point_in_time_ready is True
    assert report.no_lookahead is True
    assert report.consumer_paths == ("research_only.stock_study",)
    assert report.deployed is False
    assert report.usable_for_signal is False


def test_stock_study_rejects_unknown_source_without_enabling_a_path() -> None:
    observation = StockPointInTimeObservation(
        source_id="stock.unknown",
        symbol="TEST",
        observed_ts_ms=100,
        received_ts_ms=110,
        raw_evidence_ref="sha256:" + "b" * 64,
        consumer="research_only.stock_study",
    )

    report = study_stock_data(_catalog(_stock_source()), observations=[observation])

    assert report.status == UNMEASURABLE
    assert "OBSERVATION_SOURCE_NOT_REGISTERED" in report.reasons
    assert report.deployed is False
    assert report.usable_for_signal is False


def test_stock_observation_rejects_lookahead() -> None:
    with pytest.raises(ValueError, match="observed_ts_ms"):
        StockPointInTimeObservation(
            source_id="stock.test",
            symbol="TEST",
            observed_ts_ms=111,
            received_ts_ms=110,
            raw_evidence_ref="sha256:" + "c" * 64,
            consumer="research_only.stock_study",
        )


@pytest.mark.parametrize("evidence_ref", ["ref:arbitrary", "sha256:short", "", "sha256:" + "g" * 64])
def test_stock_observation_rejects_unhashed_evidence_reference(evidence_ref: str) -> None:
    with pytest.raises(ValueError, match="raw_evidence_ref"):
        StockPointInTimeObservation(
            source_id="stock.test",
            symbol="TEST",
            observed_ts_ms=100,
            received_ts_ms=110,
            raw_evidence_ref=evidence_ref,
            consumer="research_only.stock_study",
        )
