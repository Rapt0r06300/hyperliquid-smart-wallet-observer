from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hl_observer.alerts.read_model import (
    READ_MODEL_SCHEMA,
    AlertReadModelError,
    build_materialized_alert_read_model,
)
from hl_observer.alerts.spine import (
    AlertSpinePaths,
    CanonicalAlertWriter,
    build_alert_proposal,
)


def _writer(
    root: Path,
    *,
    now_ms: int = 10_000,
    limit: int = 2,
) -> CanonicalAlertWriter:
    return CanonicalAlertWriter(
        AlertSpinePaths.from_root(root),
        clock_ms=lambda: now_ms,
        projection_limit=limit,
    )


def _proposal(
    sequence: int,
    *,
    source_id: str,
    category: str,
    family: str,
    entity_id: str,
    research_summary: str | None = None,
    revision_of: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"alert_family": family}
    if research_summary is not None:
        payload["research_summary"] = research_summary
    return build_alert_proposal(
        producer_id="read-model-producer",
        producer_epoch="read-model-epoch-1",
        producer_seq=sequence,
        source_id=source_id,
        source_uri=f"https://example.invalid/{source_id}/{sequence}",
        source_content_hash=hashlib.sha256(
            f"{source_id}:{sequence}".encode()
        ).hexdigest(),
        observed_at_ms=1_000 + sequence,
        fetched_at_ms=2_000 + sequence,
        verified_at_ms=3_000 + sequence,
        category=category,
        headline=f"Read model alert {sequence}",
        dedup_key=f"read-model:{sequence}",
        policy_version="alert-read-model-test.v1",
        ingestion_code_sha="c" * 40,
        entity_ids=[entity_id],
        normalized_tickers=[entity_id.split(":")[-1]],
        source_health_state="HEALTHY",
        freshness_state="FRESH",
        revision_of=revision_of,
        payload=payload,
    )


def test_modele_materialise_couvre_toutes_les_vues_et_conflits(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path / "spine")
    producer = writer.producer("read-model-producer")
    producer.submit(
        _proposal(
            0,
            source_id="wire-a",
            category="MARKET_EVENT",
            family="macro",
            entity_id="asset:btc",
            research_summary="Synthese primaire",
        )
    )
    writer.process_pending()
    target_id = writer.read_ledger()[0]["event_id"]
    producer.submit(
        _proposal(
            1,
            source_id="wire-a",
            category="MARKET_EVENT",
            family="macro",
            entity_id="asset:btc",
            revision_of=target_id,
        )
    )
    producer.submit(
        _proposal(
            2,
            source_id="wire-b",
            category="MARKET_EVENT",
            family="macro",
            entity_id="asset:btc",
            revision_of=target_id,
        )
    )
    producer.submit(
        _proposal(
            3,
            source_id="wire-b",
            category="RISK_EVENT",
            family="risk",
            entity_id="asset:eth",
            research_summary="Synthese risque",
        )
    )

    writer.process_pending()
    projection = writer.rebuild_projection()
    read_model = projection["materialized_read_model"]

    assert read_model["schema_version"] == READ_MODEL_SCHEMA
    assert read_model["ledger_sequence"] == 4
    assert read_model["latest_alerts"]["returned_alerts"] == 2
    assert read_model["latest_alerts"]["omitted_alerts"] == 2
    assert set(read_model["alerts_by_family"]["buckets"]) == {"MACRO", "RISK"}
    assert set(read_model["alerts_by_entity"]["buckets"]) == {
        "asset:btc",
        "asset:eth",
    }
    assert set(read_model["alerts_by_category"]["buckets"]) == {
        "MARKET_EVENT",
        "RISK_EVENT",
    }
    assert set(read_model["current_source_health"]["sources"]) == {
        "wire-a",
        "wire-b",
    }
    conflicts = read_model["unresolved_corrections_conflicts"]
    assert conflicts["total_items"] == 1
    assert conflicts["items"][0]["kind"] == "MULTIPLE_ACTIVE_REVISIONS"
    assert read_model["research_summaries"]["total_summaries"] == 2
    assert read_model["freshness_metrics"]["source"]
    assert read_model["paper_read_only"] is True
    assert read_model["real_execution"] is False


def test_hash_rejoue_reste_identique_malgre_horloge_affichage(
    tmp_path: Path,
) -> None:
    root = tmp_path / "spine"
    writer = _writer(root, now_ms=10_000)
    writer.producer("read-model-producer").submit(
        _proposal(
            0,
            source_id="wire-a",
            category="MARKET_EVENT",
            family="macro",
            entity_id="asset:btc",
        )
    )
    writer.process_pending()
    first = writer.rebuild_projection()
    writer.paths.projection_path.unlink()

    rebuilt = _writer(root, now_ms=1_000_000).rebuild_projection()
    persisted = json.loads(
        writer.paths.projection_path.read_text(encoding="utf-8")
    )

    assert rebuilt["materialized_read_model_hash"] == first[
        "materialized_read_model_hash"
    ]
    assert rebuilt["canonical_projection_hash"] == first[
        "canonical_projection_hash"
    ]
    assert rebuilt["alerts"][0]["effective_freshness_state"] == "STALE"
    assert first["alerts"][0]["effective_freshness_state"] == "FRESH"
    assert persisted["materialized_read_model_hash"] == rebuilt[
        "materialized_read_model_hash"
    ]


def test_toutes_les_vues_restent_bornees_et_comptent_les_omissions(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path / "spine", limit=2)
    producer = writer.producer("read-model-producer")
    for sequence in range(5):
        producer.submit(
            _proposal(
                sequence,
                source_id=f"wire-{sequence}",
                category=f"CATEGORY_{sequence}",
                family=f"family-{sequence}",
                entity_id=f"asset:{sequence}",
                research_summary=f"summary-{sequence}",
            )
        )
    writer.process_pending()

    read_model = writer.rebuild_projection()["materialized_read_model"]

    for name in ("alerts_by_family", "alerts_by_entity", "alerts_by_category"):
        assert read_model[name]["returned_buckets"] == 2
        assert read_model[name]["omitted_buckets"] == 3
        assert len(read_model[name]["buckets"]) == 2
    assert read_model["current_source_health"]["returned_sources"] == 2
    assert read_model["current_source_health"]["omitted_sources"] == 3
    assert read_model["research_summaries"]["returned_summaries"] == 2
    assert read_model["research_summaries"]["omitted_summaries"] == 3
    assert writer.rebuild_projection()["returned_alert_count"] == 2


def test_modele_de_lecture_refuse_toute_capacite_reelle(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine")
    writer.producer("read-model-producer").submit(
        _proposal(
            0,
            source_id="wire-a",
            category="MARKET_EVENT",
            family="macro",
            entity_id="asset:btc",
        )
    )
    writer.process_pending()
    event = writer.read_ledger()[0]
    event["paper_read_only"] = False
    event["real_execution"] = True

    with pytest.raises(
        AlertReadModelError,
        match="READ_MODEL_PAPER_READ_ONLY_REQUIRED",
    ):
        build_materialized_alert_read_model([event])
