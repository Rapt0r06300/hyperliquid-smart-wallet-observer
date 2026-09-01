from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hl_observer.alerts.spine import (
    SCORE_POLICY_VERSION,
    AlertSpinePaths,
    AlertValidationError,
    CanonicalAlertWriter,
    CanonicalLedgerCorruption,
    build_alert_proposal,
)


def _writer(tmp_path: Path) -> CanonicalAlertWriter:
    return CanonicalAlertWriter(
        AlertSpinePaths.from_root(tmp_path / "alerts"),
        clock_ms=lambda: 10_000,
    )


def _proposal(
    sequence: int,
    *,
    model_opinion: dict | None = None,
    components: dict[str, float] | None = None,
    payload: dict | None = None,
) -> dict:
    return build_alert_proposal(
        producer_id="scored-source",
        producer_epoch="scoring-epoch-1",
        producer_seq=sequence,
        source_id="primary-score-source",
        source_uri="https://example.invalid/stable/scored-event",
        source_content_hash=hashlib.sha256(b"stable scored event").hexdigest(),
        source_event_id="stable-score-event-1",
        source_event_time_ms=500,
        observed_at_ms=1_000,
        fetched_at_ms=2_000,
        verified_at_ms=3_000,
        category="market_event",
        headline="Evidence-derived scored alert",
        dedup_key=None,
        entity_ids=["asset:btc"],
        normalized_tickers=["BTC"],
        source_health_state="HEALTHY",
        freshness_state="FRESH",
        deterministic_score_components=components
        or {"source_authority": 1.0, "freshness": 0.8},
        model_opinion=model_opinion,
        policy_version="scored-admission.v1",
        ingestion_code_sha="e" * 40,
        payload=payload or {"research_family": "lead_lag"},
    )


def test_score_est_versionne_ablated_et_n_est_pas_une_probabilite(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path)
    writer.producer("scored-source").submit(_proposal(0))
    writer.process_pending()
    event = writer.read_ledger()[0]
    receipt = event["deterministic_score_receipt"]

    assert event["deterministic_score"] == 0.25
    assert receipt["schema_version"] == SCORE_POLICY_VERSION
    assert receipt["score_bps"] == 2_500
    assert receipt["score_semantics"] == "RANKING_SCORE_NOT_PROBABILITY"
    assert receipt["model_inputs_used"] is False
    assert receipt["ablations"]["source_authority"] == {
        "removed_contribution_bps": 1_500,
        "score_without_component_bps": 1_000,
    }
    assert event["economic_admission_state"] == "NOT_EVALUATED"
    assert event["order_intent_allowed"] is False


def test_contre_factuel_llm_ne_change_ni_score_ni_admission(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    first = _proposal(
        0,
        model_opinion={
            "conviction": "HIGH",
            "summary": "strongly bullish",
            "dashboard_color": "green",
            "authoritative": True,
        },
    )
    counterfactual = _proposal(
        1,
        model_opinion={
            "conviction": "LOW",
            "summary": "strongly bearish",
            "dashboard_color": "red",
            "authoritative": True,
        },
    )
    writer.producer("scored-source").submit(first)
    writer.process_pending()
    admitted = writer.read_ledger()[0]
    writer.producer("scored-source").submit(counterfactual)
    receipt = writer.process_pending()

    assert receipt["accepted"] == 0
    assert receipt["deduplicated"] == 1
    assert len(writer.read_ledger()) == 1
    assert admitted["deterministic_score"] == first["deterministic_score"]
    assert admitted["deterministic_score"] == counterfactual["deterministic_score"]
    assert admitted["model_opinion"]["authoritative"] is False


@pytest.mark.parametrize(
    "components",
    [
        {"unknown_authority": 1.0},
        {"source_authority": 1.1},
        {"freshness": -0.01},
    ],
)
def test_composants_non_versionnes_ou_hors_bornes_sont_refuses(
    components: dict[str, float],
) -> None:
    with pytest.raises(
        AlertValidationError,
        match="DETERMINISTIC_SCORE_COMPONENTS_INVALID",
    ):
        _proposal(0, components=components)


def test_payload_alerte_ne_peut_pas_porter_une_capacite_d_ordre() -> None:
    with pytest.raises(AlertValidationError, match="ORDER_CAPABILITY_FORBIDDEN"):
        _proposal(0, payload={"nested": {"order_intent": {"side": "BUY"}}})


def test_score_altere_dans_le_ledger_est_refuse(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.producer("scored-source").submit(_proposal(0))
    writer.process_pending()
    event = writer.read_ledger()[0]
    event["deterministic_score"] = 0.99
    writer.paths.ledger_path.write_text(
        json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_SCORE_RECEIPT_INVALID",
    ):
        writer.read_ledger()
