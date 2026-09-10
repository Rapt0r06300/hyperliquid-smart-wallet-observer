from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from hl_observer.alerts.read_model import build_materialized_alert_read_model
from hl_observer.alerts.spine import (
    AlertSpinePaths,
    CanonicalAlertWriter,
    build_alert_proposal,
)


def _receipt(source: str, *, content: str | None = None) -> dict[str, str]:
    return {
        "evidence_id": source,
        "source_uri": f"https://{source}.example.invalid/article",
        "content_hash": hashlib.sha256((content or source).encode()).hexdigest(),
    }


def _writer(root: Path, *, limit: int = 500) -> CanonicalAlertWriter:
    return CanonicalAlertWriter(
        AlertSpinePaths.from_root(root),
        clock_ms=lambda: 10_000,
        projection_limit=limit,
    )


def _submit(
    writer: CanonicalAlertWriter,
    source: str,
    *,
    refs: list[dict[str, str]] | None = None,
    content: str | None = None,
    payload: dict | None = None,
) -> None:
    receipt = _receipt(source, content=content)
    writer.producer(source).submit(
        build_alert_proposal(
            producer_id=source,
            producer_epoch="TEST_FIXTURE",
            producer_seq=0,
            source_id=source,
            source_uri=receipt["source_uri"],
            source_content_hash=receipt["content_hash"],
            observed_at_ms=1_000,
            fetched_at_ms=2_000,
            verified_at_ms=3_000,
            category="MARKET_EVENT",
            headline="TEST_FIXTURE: same reported event",
            dedup_key="same-story",
            entity_ids=["asset:btc"],
            evidence_refs=refs,
            policy_version="lineage-test.v1",
            ingestion_code_sha="a" * 40,
            payload=payload,
        )
    )


def _syndication(writer: CanonicalAlertWriter) -> None:
    _submit(writer, "reuters")
    _submit(writer, "yahoo", refs=[_receipt("reuters")])
    _submit(writer, "social", refs=[_receipt("yahoo")])
    _submit(writer, "blog", refs=[_receipt("reuters")])
    writer.process_pending()


def test_reuters_syndication_repost_and_citation_are_one_correlated_group(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path / "spine")
    _syndication(writer)

    lineage = writer.rebuild_projection()["materialized_read_model"].get("source_lineage", {})

    assert lineage.get("confirmation_count_upper_bound") == 1
    assert lineage["independent_confirmation_count"] is None
    assert lineage["total_groups"] == 1
    assert lineage["correlated_alert_count"] == 4
    group = lineage["groups"][0]
    assert group["lineage_state"] == "CORRELATED"
    assert group["source_ids"] == ["blog", "reuters", "social", "yahoo"]
    assert set(group["event_ids"]) == {event["event_id"] for event in writer.read_ledger()}


def test_different_publishers_and_self_receipts_do_not_prove_independence(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path / "spine")
    for source in ("reuters", "yahoo", "social", "blog"):
        _submit(writer, source, payload={"independent": True, "source_lineage": "ORIGINAL"})
    writer.process_pending()

    model = writer.rebuild_projection()["materialized_read_model"]
    lineage = model.get("source_lineage", {})

    assert lineage.get("independence_state") == "NOT_PROVEN"
    assert lineage["independent_confirmation_count"] is None
    assert lineage["confirmation_count_upper_bound"] == 4
    assert lineage["unknown_lineage_alert_count"] == 4
    assert all(group["lineage_state"] == "LINEAGE_UNKNOWN" for group in lineage["groups"])
    assert all(
        alert["source_lineage"]["independence_state"] == "NOT_PROVEN"
        for alert in model["latest_alerts"]["alerts"]
    )


def test_identical_content_on_different_urls_is_discounted_without_explicit_citation(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path / "spine")
    _submit(writer, "reuters", content="TEST_FIXTURE: identical wire text")
    _submit(writer, "mirror", content="TEST_FIXTURE: identical wire text")
    writer.process_pending()

    lineage = writer.rebuild_projection()["materialized_read_model"].get("source_lineage", {})

    assert lineage.get("confirmation_count_upper_bound") == 1
    assert lineage["groups"][0]["total_alerts"] == 2
    assert "SHARED_CONTENT_HASH" in lineage["groups"][0]["correlation_reasons"]


def test_shared_uri_links_different_snapshots_and_ignores_fragment(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine")
    first = _receipt("wire", content="first version")
    second = _receipt("wire", content="updated version")
    second["source_uri"] += "#quoted-paragraph"
    _submit(writer, "blog", refs=[first])
    _submit(writer, "social", refs=[second])
    writer.process_pending()

    lineage = writer.rebuild_projection()["materialized_read_model"].get("source_lineage", {})

    assert lineage.get("confirmation_count_upper_bound") == 1
    assert "SHARED_SOURCE_URI" in lineage["groups"][0]["correlation_reasons"]


def test_evidence_labels_and_same_story_are_not_provenance_identity(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine")
    first, second = _receipt("wire-a"), _receipt("wire-b")
    first["evidence_id"] = second["evidence_id"] = "article-1"
    _submit(writer, "publisher-a", refs=[first])
    _submit(writer, "publisher-b", refs=[second])
    writer.process_pending()

    lineage = writer.rebuild_projection()["materialized_read_model"].get("source_lineage", {})

    assert lineage.get("total_groups") == 2
    assert lineage["independent_confirmation_count"] is None
    assert lineage["unknown_lineage_alert_count"] == 2


def test_unadmitted_shared_upstream_and_duplicate_refs_still_count_once(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine")
    reference = _receipt("reuters")
    _submit(writer, "blog", refs=[reference, reference])
    _submit(writer, "yahoo", refs=[{**reference, "evidence_id": "local-citation-label"}])
    writer.process_pending()

    lineage = writer.rebuild_projection()["materialized_read_model"].get("source_lineage", {})

    assert lineage.get("confirmation_count_upper_bound") == 1
    assert lineage["groups"][0]["total_alerts"] == 2
    assert lineage["groups"][0]["source_ids"] == ["blog", "yahoo"]


def test_projection_truncation_keeps_transitive_links_from_the_full_prefix(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine", limit=2)
    _syndication(writer)
    model = writer.rebuild_projection()["materialized_read_model"]
    lineage = model.get("source_lineage", {})

    assert lineage.get("confirmation_count_upper_bound") == 1
    group = lineage["groups"][0]
    assert group["total_alerts"] == 4
    assert group["returned_alerts"] == 2
    assert group["omitted_alerts"] == 2
    assert len(group["event_ids"]) == 2
    assert group["total_sources"] == 4
    assert group["returned_sources"] == 2
    assert group["omitted_sources"] == 2
    assert len(group["source_ids"]) == 2
    assert model["latest_alerts"]["returned_alerts"] == 2
    for alert in model["latest_alerts"]["alerts"]:
        assert alert["source_lineage"]["group_id"] == group["group_id"]
        assert alert["source_lineage"]["corroboration_weight_upper_bound"] == 0.25
        assert alert["source_lineage"]["independence_state"] == "NOT_PROVEN"


def test_all_groups_are_counted_even_when_only_latest_groups_are_returned(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine", limit=2)
    for source in ("a", "b", "c", "d", "e"):
        _submit(writer, source)
    writer.process_pending()

    model = writer.rebuild_projection()["materialized_read_model"]
    lineage = model.get("source_lineage", {})

    assert lineage.get("total_groups") == 5
    assert lineage["returned_groups"] == 2
    assert lineage["omitted_groups"] == 3
    assert len(lineage["groups"]) == 2
    assert lineage["unknown_lineage_alert_count"] == 5
    assert {group["event_ids"][0] for group in lineage["groups"]} == {
        alert["event_id"] for alert in model["latest_alerts"]["alerts"]
    }


@pytest.mark.parametrize("missing", [None, {}, [], "unknown", 42])
def test_missing_or_malformed_legacy_provenance_never_proves_independence(
    tmp_path: Path, missing: object,
) -> None:
    writer = _writer(tmp_path / "spine")
    _submit(writer, "a")
    _submit(writer, "b")
    writer.process_pending()
    events = writer.read_ledger()
    for event in events:
        event["source_receipt"] = missing
        event["evidence_refs"] = missing
        event.pop("source_uri")
        event.pop("source_content_hash")

    lineage = build_materialized_alert_read_model(events).get("source_lineage", {})

    assert lineage.get("unknown_lineage_alert_count") == 2
    assert lineage["independent_confirmation_count"] is None
    assert lineage["total_groups"] == 2


def test_replay_is_deterministic_without_mutating_canonical_provenance(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine")
    _syndication(writer)
    events = writer.read_ledger()
    original = deepcopy(events)

    first = build_materialized_alert_read_model(events)
    second = build_materialized_alert_read_model(deepcopy(events))

    assert "source_lineage" in first
    assert first == second
    assert events == original
    assert first["paper_read_only"] is True
    assert first["real_execution"] is False


def test_empty_prefix_has_no_invented_confirmations() -> None:
    lineage = build_materialized_alert_read_model([]).get("source_lineage", {})

    assert lineage.get("total_groups") == 0
    assert lineage["groups"] == []
    assert lineage["confirmation_count_upper_bound"] == 0
    assert lineage["independent_confirmation_count"] is None
