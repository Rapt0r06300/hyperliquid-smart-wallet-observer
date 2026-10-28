from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.research.decision_explainer import (  # noqa: E402, I001
    build_leader_review,
    explain_decision,
)
from hl_observer.research.leader_review_ledger import (
    LeaderReviewLedgerError,
    append_copy_vault_v9_leader_reviews,
    append_leader_review,
    load_leader_reviews,
    summarize_leader_reviews,
)


AS_OF = 2_000_000
REF = "safe-shard:leader-1:fill-7"


def _evidence(**overrides):
    row = {
        "ref": REF,
        "leader_id": "leader-1",
        "source": "copy_vault_fills",
        "source_sha256": "a" * 64,
        "quality": "SAFE",
        "manifest_verified": True,
        "replay_compatible": True,
        "observed_at_ms": 1_999_000,
        "received_at_ms": 1_999_010,
        "period_start_ms": 1_998_000,
        "period_end_ms": 1_999_000,
    }
    row.update(overrides)
    return row


def _review(**overrides):
    values = {
        "leader_id": "leader-1",
        "outcome": "RETAINED",
        "as_of_ms": AS_OF,
        "max_evidence_age_ms": 10_000,
        "favorable": [
            {"finding_key": "post_fill_markout", "summary": "Markout positif", "evidence_refs": [REF]}
        ],
        "counterevidence": [],
        "unknowns": ["Capacité long terme non mesurée"],
        "falsification_condition": "Rétrograder si le markout OOS devient négatif.",
        "evidence": [_evidence()],
    }
    values.update(overrides)
    return build_leader_review(**values)


def test_leader_review_is_structured_and_consultative_only():
    result = _review()

    assert result["review_status"] == "CONSULTATIVE_REVIEWABLE"
    assert result["favorable"][0]["evidence_refs"] == [REF]
    assert result["unknowns"] == ["Capacité long terme non mesurée"]
    assert result["falsification_condition"].startswith("Rétrograder")
    assert result["evidence"][0]["source_sha256"] == "a" * 64
    assert result["verification_scope"] == "STRUCTURAL_RECEIPT_VALIDATION_ONLY"
    assert result["source_bytes_rehashed_here"] is False
    assert result["canonical_safe_audit_required"] is True
    assert result["consultative_only"] is True
    assert result["can_change_decision"] is False
    assert result["can_modify_frozen_candidate"] is False
    assert result["can_modify_oos_forward_splits"] is False
    assert result["can_select_champion"] is False
    assert result["can_prove_pnl"] is False


def test_leader_review_fails_closed_for_stale_evidence_even_if_received_recently():
    stale = _evidence(
        observed_at_ms=1_000,
        received_at_ms=AS_OF - 1,
        period_start_ms=1,
        period_end_ms=1_000,
    )

    result = _review(max_evidence_age_ms=100, evidence=[stale])

    assert result["review_status"] == "UNMEASURABLE"
    assert "EVIDENCE_0_EVIDENCE_STALE" in result["issues"]


def test_leader_review_fails_closed_on_future_or_non_safe_evidence():
    future = _evidence(observed_at_ms=AS_OF + 1)
    unsafe = _evidence(ref="unsafe", quality="UNVERIFIED")

    result = _review(evidence=[future, unsafe])

    assert result["review_status"] == "UNMEASURABLE"
    assert "EVIDENCE_0_EVIDENCE_NOT_CAUSAL_OR_PERIOD_INVALID" in result["issues"]
    assert "EVIDENCE_1_EVIDENCE_NOT_SAFE" in result["issues"]


def test_leader_review_detects_conflicting_findings_and_invalid_refs():
    result = _review(
        counterevidence=[
            {
                "finding_key": "post_fill_markout",
                "summary": "Markout négatif sur autre fenêtre",
                "evidence_refs": ["missing"],
            }
        ]
    )

    assert result["review_status"] == "UNMEASURABLE"
    assert result["contradictory_findings"] == ["post_fill_markout"]
    assert "CONTRADICTORY_FINDINGS" in result["issues"]
    assert "COUNTEREVIDENCE_ITEM_0_EVIDENCE_UNVERIFIED" in result["issues"]


def test_leader_review_never_accepts_unhashed_or_unbound_rows():
    result = _review(evidence=[_evidence(source_sha256="", leader_id="someone-else")])

    assert result["review_status"] == "UNMEASURABLE"
    assert any("SOURCE_SHA256_INVALID" in issue for issue in result["issues"])
    assert any("LEADER_ID_MISMATCH" in issue for issue in result["issues"])


def test_leader_review_requires_manifest_and_replay_compatibility_proofs():
    result = _review(
        evidence=[_evidence(manifest_verified=False, replay_compatible=False)]
    )

    assert result["review_status"] == "UNMEASURABLE"
    assert "EVIDENCE_0_EVIDENCE_MANIFEST_UNVERIFIED" in result["issues"]
    assert "EVIDENCE_0_EVIDENCE_NOT_REPLAY_COMPATIBLE" in result["issues"]


def test_explain_decision_does_not_treat_truthy_strings_as_acceptance():
    result = explain_decision({"accepted": "false"}, evidence_refs="not-a-reference-list")

    assert result["accepted"] is False
    assert result["decision_status_valid"] is False
    assert result["summary"].startswith("DECISION_STATUS_UNVERIFIABLE:")
    assert result["evidence_refs"] == []
    assert result["evidence_refs_valid"] is False
    assert result["context_only"] is True
    assert result["changes_decision"] is False


def test_decision_explainer_carries_the_leader_review_without_authority():
    payload = {
        "leader_id": "leader-1",
        "outcome": "DEMOTED",
        "as_of_ms": AS_OF,
        "max_evidence_age_ms": 10_000,
        "favorable": [],
        "counterevidence": [
            {"finding_key": "net_markout", "summary": "Net markout négatif", "evidence_refs": [REF]}
        ],
        "unknowns": [],
        "falsification_condition": "Réexaminer après nouvelle fenêtre SAFE.",
        "evidence": [_evidence()],
    }
    decision = {"accepted": False, "reason_code": "LEADER_QUALITY_DEGRADED"}

    result = explain_decision(decision, evidence_refs=[REF], leader_review_payload=payload)

    assert result["leader_review"]["review_status"] == "CONSULTATIVE_REVIEWABLE"
    assert decision == {"accepted": False, "reason_code": "LEADER_QUALITY_DEGRADED"}
    assert result["changes_decision"] is False
    assert result["leader_review_persistence_status"] == "NOT_REQUESTED"


def _safe_inventory():
    import hashlib

    asset = {
        "dataset_id": "safe-fill-dataset-1",
        "family": "copy_vault_fills",
        "release_tag": "safe-release-1",
        "release_asset": "fills.jsonl",
        "manifest_path": "datasets/safe/manifests/fills.json",
        "bytes": 128,
        "sha256": "a" * 64,
    }
    catalog_sha = "c" * 64
    inventory_material = "\n".join(
        "\0".join(
            str(asset.get(key) if asset.get(key) is not None else "<MISSING>")
            for key in (
                "dataset_id", "family", "release_tag", "release_asset",
                "manifest_path", "bytes", "sha256",
            )
        )
        for asset in [asset]
    )
    inventory_sha = hashlib.sha256(inventory_material.encode("utf-8")).hexdigest()
    selection_material = catalog_sha + "\n" + f"{asset['dataset_id']}\0{asset['sha256']}"
    selection_sha = hashlib.sha256(selection_material.encode("utf-8")).hexdigest()
    return {
        "safe_catalog_status": "SAFE_COMPLETE",
        "data_complete": True,
        "paper_read_only": True,
        "real_execution": False,
        "verified_source_assets": [asset],
        "source_asset_inventory_count": 1,
        "source_asset_inventory_complete": True,
        "source_asset_inventory_sha256": inventory_sha,
        "source_index_sha256": catalog_sha,
        "selection_digest": selection_sha,
        "missing_shards": 0,
        "rejected_assets": 0,
        "continuity_evidence_missing_shards": 0,
        "payload_rejected_records": 0,
        "historical_coverage_audit": {"status": "COMPLETE"},
    }


def _durable_review_payload(**overrides):
    payload = {
        "leader_id": "leader-1",
        "outcome": "RETAINED",
        "as_of_ms": AS_OF,
        "max_evidence_age_ms": 10_000,
        "favorable": [
            {"finding_key": "post_fill_markout", "summary": "Markout positif", "evidence_refs": [REF]}
        ],
        "counterevidence": [],
        "unknowns": ["Capacité long terme non mesurée"],
        "falsification_condition": "Rétrograder si le markout OOS devient négatif.",
        "evidence": [
            _evidence(
                source_dataset_id="safe-fill-dataset-1",
                source_family="copy_vault_fills",
                source_catalog_sha256="c" * 64,
            )
        ],
    }
    payload.update(overrides)
    return payload


def test_durable_leader_review_is_bound_to_verified_safe_inventory_and_hash_chain(tmp_path):
    path = tmp_path / "leader-reviews.jsonl"
    inventory = _safe_inventory()
    payload = _durable_review_payload()

    saved = append_leader_review(
        path,
        payload,
        safe_inventory=inventory,
        reviewer_id="codex-local-reviewer",
        review_id="review-001",
    )

    assert saved["review_status"] == "CONSULTATIVE_REVIEWABLE"
    assert saved["safe_inventory"]["source_asset_inventory_sha256"] == inventory[
        "source_asset_inventory_sha256"
    ]
    assert saved["safe_evidence_assets"] == [
        {
            "ref": REF,
            "dataset_id": "safe-fill-dataset-1",
            "family": "copy_vault_fills",
            "sha256": "a" * 64,
            "source_catalog_sha256": "c" * 64,
            "release_tag": "safe-release-1",
            "release_asset": "fills.jsonl",
            "manifest_path": "datasets/safe/manifests/fills.json",
            "bytes": 128,
        }
    ]
    assert saved["review"]["evidence"][0]["ref"] == REF
    assert saved["consultative_only"] is True
    assert saved["can_change_decision"] is False
    assert saved["can_modify_frozen_candidate"] is False
    assert saved["can_modify_oos_forward_splits"] is False
    assert saved["can_select_champion"] is False
    assert saved["can_prove_pnl"] is False
    assert "pnl" not in saved and "candidate" not in saved
    assert saved["previous_receipt_sha256"] == "0" * 64
    assert len(saved["receipt_sha256"]) == 64
    assert load_leader_reviews(path) == [saved]
    report = summarize_leader_reviews(path)
    assert report["status"] == "AVAILABLE"
    assert report["receipt_count"] == 1
    assert report["reviewable_count"] == 1
    assert report["recent_receipts"][0]["leader_id"] == "leader-1"
    assert report["recent_receipts"][0]["favorable"][0]["finding_key"] == "post_fill_markout"
    assert report["recent_receipts"][0]["unknowns"] == ["Capacité long terme non mesurée"]
    assert report["recent_receipts"][0]["falsification_condition"].startswith("Rétrograder")
    assert report["recent_receipts"][0]["safe_evidence_assets"][0]["manifest_path"] == (
        "datasets/safe/manifests/fills.json"
    )


def test_explain_decision_can_persist_consultative_review_without_changing_decision(tmp_path):
    decision = {"accepted": False, "reason_code": "LEADER_QUALITY_DEGRADED"}
    original = dict(decision)

    result = explain_decision(
        decision,
        evidence_refs=[REF],
        leader_review_payload=_durable_review_payload(),
        leader_review_ledger_path=str(tmp_path / "leader-reviews.jsonl"),
        leader_review_safe_inventory=_safe_inventory(),
        leader_review_reviewer_id="codex-local-reviewer",
        leader_review_id="review-from-explainer",
    )

    assert result["leader_review_persistence_status"] == "PERSISTED"
    assert result["leader_review_receipt"]["review_status"] == "CONSULTATIVE_REVIEWABLE"
    assert decision == original
    assert result["changes_decision"] is False


def test_durable_review_replay_is_idempotent_and_conflicting_id_fails(tmp_path):
    path = tmp_path / "leader-reviews.jsonl"
    args = {
        "safe_inventory": _safe_inventory(),
        "reviewer_id": "codex-local-reviewer",
        "review_id": "review-001",
    }
    first = append_leader_review(path, _durable_review_payload(), **args)
    replay = append_leader_review(path, _durable_review_payload(), **args)

    assert replay == first
    assert len(load_leader_reviews(path)) == 1
    with pytest.raises(LeaderReviewLedgerError, match="REVIEW_ID_CONFLICT"):
        append_leader_review(
            path,
            _durable_review_payload(outcome="DEMOTED"),
            **args,
        )
    assert len(load_leader_reviews(path)) == 1


def test_durable_review_fails_closed_and_retains_stale_contradictory_or_unbound_evidence(tmp_path):
    payload = _durable_review_payload(
        counterevidence=[
            {"finding_key": "post_fill_markout", "summary": "Markout négatif", "evidence_refs": [REF]}
        ],
        evidence=[
            _evidence(
                source_dataset_id="safe-fill-dataset-1",
                source_family="copy_vault_fills",
                source_catalog_sha256="c" * 64,
                period_end_ms=1_000,
                observed_at_ms=900,
                received_at_ms=910,
                period_start_ms=800,
            )
        ],
    )
    record = append_leader_review(
        tmp_path / "leader-reviews.jsonl",
        payload,
        safe_inventory=_safe_inventory(),
        reviewer_id="codex-local-reviewer",
        review_id="review-uncertain",
    )

    assert record["review_status"] == "UNMEASURABLE"
    assert "CONTRADICTORY_FINDINGS" in record["issues"]
    assert any("EVIDENCE_STALE" in issue for issue in record["issues"])
    assert record["consultative_only"] is True
    assert record["can_select_champion"] is False


def test_durable_review_inventory_mismatch_cannot_become_reviewable(tmp_path):
    inventory = _safe_inventory()
    inventory["source_asset_inventory_sha256"] = "d" * 64

    record = append_leader_review(
        tmp_path / "leader-reviews.jsonl",
        _durable_review_payload(),
        safe_inventory=inventory,
        reviewer_id="codex-local-reviewer",
        review_id="review-bad-inventory",
    )

    assert record["review_status"] == "UNMEASURABLE"
    assert "SAFE_SOURCE_ASSET_INVENTORY_DIGEST_MISMATCH" in record["issues"]
    assert record["safe_evidence_assets"] == []


def test_durable_review_missing_safe_evidence_or_external_source_fails_closed(tmp_path):
    absent = append_leader_review(
        tmp_path / "missing-evidence.jsonl",
        _durable_review_payload(evidence=[]),
        safe_inventory=_safe_inventory(),
        reviewer_id="codex-local-reviewer",
    )
    assert absent["review_status"] == "UNMEASURABLE"
    assert "SAFE_EVIDENCE_MISSING" in absent["issues"]

    external = append_leader_review(
        tmp_path / "external-source.jsonl",
        _durable_review_payload(
            evidence=[
                _evidence(
                    source="paid_external_feed",
                    source_dataset_id="safe-fill-dataset-1",
                    source_family="copy_vault_fills",
                    source_catalog_sha256="c" * 64,
                )
            ]
        ),
        safe_inventory=_safe_inventory(),
        reviewer_id="codex-local-reviewer",
    )
    assert external["review_status"] == "UNMEASURABLE"
    assert "SAFE_EVIDENCE_0_SOURCE_MISMATCH" in external["issues"]
    assert external["safe_evidence_assets"] == []


def test_durable_review_ledger_detects_receipt_tampering(tmp_path):
    path = tmp_path / "leader-reviews.jsonl"
    append_leader_review(
        path,
        _durable_review_payload(),
        safe_inventory=_safe_inventory(),
        reviewer_id="codex-local-reviewer",
        review_id="review-001",
    )
    path.write_text(path.read_text(encoding="utf-8").replace("RETAINED", "REJECTED"), encoding="utf-8")

    with pytest.raises(LeaderReviewLedgerError, match="RECEIPT_HASH_MISMATCH"):
        load_leader_reviews(path)
    assert summarize_leader_reviews(path)["status"] == "INVALID"


def test_durable_review_fails_closed_when_coverage_is_unknown_or_family_is_invalid(tmp_path):
    incomplete = _safe_inventory()
    incomplete.pop("historical_coverage_audit")
    unknown_coverage = append_leader_review(
        tmp_path / "unknown-coverage.jsonl",
        _durable_review_payload(),
        safe_inventory=incomplete,
        reviewer_id="codex-local-reviewer",
    )
    assert unknown_coverage["review_status"] == "UNMEASURABLE"
    assert "HISTORICAL_COVERAGE_UNKNOWN" in unknown_coverage["issues"]

    invalid_family = _safe_inventory()
    invalid_family["verified_source_assets"][0]["family"] = []
    invalid_receipt = append_leader_review(
        tmp_path / "invalid-family.jsonl",
        _durable_review_payload(),
        safe_inventory=invalid_family,
        reviewer_id="codex-local-reviewer",
    )
    assert invalid_receipt["review_status"] == "UNMEASURABLE"
    assert "SAFE_SOURCE_ASSET_INVENTORY_ROW_INVALID" in invalid_receipt["issues"]


def test_v9_train_decisions_are_persisted_with_provenance_and_idempotency(tmp_path):
    path = tmp_path / "leader-reviews.jsonl"
    inventory = _safe_inventory()
    evidence = _evidence(
        ref="v9:trade-1:LEADER_FILL:safe-fill-dataset-1:event-1",
        source_dataset_id="safe-fill-dataset-1",
        source_family="copy_vault_fills",
        source_catalog_sha256="c" * 64,
        observed_at_ms=AS_OF - 500,
        received_at_ms=AS_OF - 490,
        period_start_ms=AS_OF - 600,
        period_end_ms=AS_OF - 500,
    )
    analysis = {
        "schema_version": "hypersmart.copy_vault_v9_online_leader_quality_train.v1",
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "leader_decision_traces": {
            "schema_version": "copy_vault.leader_quality_decision_trace.v1",
            "scope": "TRAIN_ONLY_PRE_FREEZE",
            "traces": [
                {
                    "minimum_prior_closed": 1,
                    "history_window": 5,
                    "candidate_decision_count": 2,
                    "decisions": [
                        {
                            "candidate_trade_id": "trade-1",
                            "leader_id": "leader-1",
                            "as_of_ms": AS_OF,
                            "outcome": "RETAINED",
                            "reason": "POSITIVE_PRIOR_NET_MEAN",
                            "prior_count": 1,
                            "prior_mean_net_pnl_usd": 0.25,
                            "evidence_refs": [evidence],
                            "evidence_status": "SAFE_CAUSAL_COMPLETE",
                        },
                        {
                            "candidate_trade_id": "trade-2",
                            "leader_id": "leader-2",
                            "as_of_ms": AS_OF,
                            "outcome": "REJECTED",
                            "reason": "INSUFFICIENT_PRIOR_CLOSED_HISTORY",
                            "prior_count": 0,
                            "prior_mean_net_pnl_usd": None,
                            "evidence_refs": [],
                            "evidence_status": "INCOMPLETE_OR_UNVERIFIED",
                        },
                    ],
                }
            ],
        },
    }

    first = append_copy_vault_v9_leader_reviews(
        path,
        analysis,
        safe_inventory=inventory,
        reviewer_id="copy-vault-v9-test",
        max_evidence_age_ms=10_000,
        engine_sha256="f" * 64,
    )
    replay = append_copy_vault_v9_leader_reviews(
        path,
        analysis,
        safe_inventory=inventory,
        reviewer_id="copy-vault-v9-test",
        max_evidence_age_ms=10_000,
        engine_sha256="f" * 64,
    )

    records = load_leader_reviews(path)
    assert first["decision_count"] == 2
    assert first["created_count"] == 2
    assert first["reviewable_count"] == 1
    assert first["unmeasurable_count"] == 1
    assert replay["created_count"] == 0
    assert replay["reused_count"] == 2
    assert len(records) == 2
    retained = next(row for row in records if row["review"]["leader_id"] == "leader-1")
    assert retained["review"]["outcome_observed"] == "RETAINED"
    assert retained["review"]["favorable"][0]["evidence_refs"] == [evidence["ref"]]
    assert retained["context"]["candidate_trade_id"] == "trade-1"
    rejected = next(row for row in records if row["review"]["leader_id"] == "leader-2")
    assert rejected["review_status"] == "UNMEASURABLE"
    assert rejected["review"]["unknowns"]
