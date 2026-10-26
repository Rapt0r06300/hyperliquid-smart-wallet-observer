from __future__ import annotations

import hashlib
import json

from tools.copy_vault_continuity import (
    load_history_checkpoints,
    load_release_history_audits,
)


def _completed_campaign(
    *,
    epoch: int = 7,
    status: str = "COMPLETE",
    durable: bool = True,
    end_ms: int = 2_000,
    gaps: list[dict] | None = None,
    report_overrides: dict | None = None,
) -> dict:
    address = "0x" + "a" * 40
    report = {
        "status": "PARTIAL" if gaps else "COMPLETE",
        "request_audit_status": "COMPLETE",
        "checkpoint_advance_allowed": True,
        "retention_cap_reached": False,
        "requested_start_ms": 1_000,
        "requested_end_ms": end_ms,
        "rows": 3,
        "requests": 1,
        "pending_windows": 0,
        "request_budget_exhausted": False,
        "invalid_fill_count": 0,
        "failed_windows": [],
        "cap_blocked_windows": [],
        "unresolved_gaps": gaps or [],
    }
    report.update(report_overrides or {})
    summary = {
        "historical_backfill": {address: report},
    }
    result = {
        "status": "COMPLETE",
        "durable_persisted": durable,
        "release_tag": "data-v2-campaign-copy-vault-test-u0",
        "stdout": json.dumps(summary),
    }
    digest = hashlib.sha256(
        json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    return {
        "campaign_id": "copy-vault-e7-test",
        "kind": "copy_vault_collection",
        "creation_phase": "COLLECT",
        "phase_epoch": epoch,
        "status": status,
        "completed_units": {"unit-0": {"sha256": digest, "result": result}},
    }


def test_history_checkpoints_require_durable_complete_same_epoch_results(tmp_path):
    campaign = _completed_campaign()
    (tmp_path / "copy-vault-campaign.json").write_text(json.dumps(campaign), encoding="utf-8")

    result = load_history_checkpoints(
        tmp_path,
        phase_epoch=7,
        addresses={"0x" + "a" * 40},
    )

    assert result["0x" + "a" * 40]["last_reconciled_end_ms"] == 2_000
    assert result["0x" + "a" * 40]["source_campaign_id"] == "copy-vault-e7-test"


def test_history_checkpoints_preserve_known_gaps_without_erasing_them(tmp_path):
    gap = {"start_ms": 500, "end_ms": 999, "reason": "LOOKBACK_LIMIT"}
    campaign = _completed_campaign(gaps=[gap])
    (tmp_path / "copy-vault-campaign.json").write_text(json.dumps(campaign), encoding="utf-8")

    result = load_history_checkpoints(
        tmp_path,
        phase_epoch=7,
        addresses={"0x" + "a" * 40},
    )

    assert result["0x" + "a" * 40]["unresolved_gaps"] == [gap]


def test_history_checkpoint_advances_after_audited_retention_cap_and_keeps_gap(tmp_path):
    gap = {"start_ms": 1_000, "end_ms": 1_499, "reason": "PUBLIC_10000_FILL_RETENTION_LIMIT"}
    campaign = _completed_campaign(
        report_overrides={
            "status": "PARTIAL",
            "request_audit_status": "PARTIAL",
            "retention_cap_reached": True,
            "oldest_fill_ts_ms": 1_500,
            "rows": 10_000,
            "unresolved_gaps": [gap],
        }
    )
    (tmp_path / "copy-vault-campaign.json").write_text(json.dumps(campaign), encoding="utf-8")

    result = load_history_checkpoints(
        tmp_path,
        phase_epoch=7,
        addresses={"0x" + "a" * 40},
    )

    assert result["0x" + "a" * 40]["last_reconciled_end_ms"] == 2_000
    assert result["0x" + "a" * 40]["unresolved_gaps"] == [gap]


def test_history_checkpoints_reject_wrong_epoch_non_durable_and_bad_digest(tmp_path):
    wrong_epoch = _completed_campaign(epoch=6)
    non_durable = _completed_campaign(durable=False)
    bad_digest = _completed_campaign()
    bad_digest["completed_units"]["unit-0"]["sha256"] = "0" * 64
    for name, row in (("old.json", wrong_epoch), ("not-durable.json", non_durable), ("bad.json", bad_digest)):
        (tmp_path / name).write_text(json.dumps(row), encoding="utf-8")

    assert load_history_checkpoints(
        tmp_path,
        phase_epoch=7,
        addresses={"0x" + "a" * 40},
    ) == {}


def test_history_checkpoints_select_latest_durable_end(tmp_path):
    for name, end in (("copy-vault-old.json", 2_000), ("copy-vault-new.json", 3_000)):
        (tmp_path / name).write_text(
            json.dumps(_completed_campaign(end_ms=end)), encoding="utf-8"
        )

    result = load_history_checkpoints(
        tmp_path,
        phase_epoch=7,
        addresses={"0x" + "a" * 40},
    )

    assert result["0x" + "a" * 40]["last_reconciled_end_ms"] == 3_000


def test_safe_release_without_matching_campaign_receipt_is_partial(tmp_path):
    result = load_release_history_audits(
        tmp_path,
        release_tags={"data-v2-campaign-unmatched"},
    )

    assert result["status"] == "PARTIAL"
    assert result["unknown_release_tags"] == ["data-v2-campaign-unmatched"]
    assert result["missing_durable_receipt_tags"] == ["data-v2-campaign-unmatched"]
    assert result["receipt_without_backfill_audit_tags"] == []


def test_durable_collection_receipt_without_backfill_report_is_not_a_missing_shard(tmp_path):
    campaign = _completed_campaign()
    payload = campaign["completed_units"]["unit-0"]["result"]
    stdout = json.loads(payload["stdout"])
    stdout.pop("historical_backfill", None)
    payload["stdout"] = json.dumps(stdout, sort_keys=True)
    import hashlib
    payload_digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    campaign["completed_units"]["unit-0"]["sha256"] = payload_digest
    (tmp_path / "copy-vault-campaign-receipt.json").write_text(
        json.dumps(campaign), encoding="utf-8"
    )

    result = load_release_history_audits(
        tmp_path,
        release_tags={"data-v2-campaign-copy-vault-test-u0"},
    )

    assert result["status"] == "PARTIAL"
    assert result["audited_release_count"] == 0
    assert result["durable_receipt_release_count"] == 1
    assert result["receipt_without_backfill_audit_tags"] == [
        "data-v2-campaign-copy-vault-test-u0"
    ]
    assert result["missing_durable_receipt_tags"] == []


def test_structured_backfill_audit_survives_truncated_campaign_stdout(tmp_path):
    campaign = _completed_campaign()
    unit = campaign["completed_units"]["unit-0"]
    payload = unit["result"]
    address = "0x" + "a" * 40
    report = {
        "status": "COMPLETE",
        "request_audit_status": "COMPLETE",
        "checkpoint_advance_allowed": True,
        "retention_cap_reached": False,
        "requested_start_ms": 1_000,
        "requested_end_ms": 2_000,
        "rows": 3,
        "pending_windows": 0,
        "request_budget_exhausted": False,
        "invalid_fill_count": 0,
        "failed_windows": [],
        "cap_blocked_windows": [],
        "unresolved_gaps": [],
    }
    reports = {address: report}
    payload["collection_metrics"] = {
        "historical_backfill_audit": {
            "schema": "alina.copy_vault.historical_backfill_audit.v1",
            "source": "BUNDLE_INDEX.json",
            "status": "COMPLETE",
            "report_count": 1,
            "reports_sha256": hashlib.sha256(
                json.dumps(
                    reports,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "reports": reports,
        }
    }
    payload["stdout"] = "{" + " " * 8_000
    unit["sha256"] = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    receipt = tmp_path / "copy-vault-campaign-receipt.json"
    receipt.write_text(json.dumps(campaign), encoding="utf-8")

    audited = load_release_history_audits(
        tmp_path,
        release_tags={"data-v2-campaign-copy-vault-test-u0"},
    )
    checkpoints = load_history_checkpoints(
        tmp_path,
        phase_epoch=7,
        addresses={address},
    )

    assert audited["status"] == "COMPLETE"
    assert audited["audited_release_count"] == 1
    assert checkpoints[address]["last_reconciled_end_ms"] == 2_000


def test_invalid_structured_backfill_digest_does_not_fall_back_to_stdout(tmp_path):
    campaign = _completed_campaign()
    unit = campaign["completed_units"]["unit-0"]
    unit["result"]["collection_metrics"] = {
        "historical_backfill_audit": {
            "schema": "alina.copy_vault.historical_backfill_audit.v1",
            "source": "BUNDLE_INDEX.json",
            "status": "COMPLETE",
            "report_count": 1,
            "reports_sha256": "0" * 64,
            "reports": {"0x" + "a" * 40: {"status": "COMPLETE"}},
        }
    }
    unit["sha256"] = hashlib.sha256(
        json.dumps(
            unit["result"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    (tmp_path / "copy-vault-campaign-receipt.json").write_text(
        json.dumps(campaign), encoding="utf-8"
    )

    audited = load_release_history_audits(
        tmp_path,
        release_tags={"data-v2-campaign-copy-vault-test-u0"},
    )
    checkpoints = load_history_checkpoints(
        tmp_path,
        phase_epoch=7,
        addresses={"0x" + "a" * 40},
    )

    assert audited["audited_release_count"] == 0
    assert audited["receipt_without_backfill_audit_tags"] == [
        "data-v2-campaign-copy-vault-test-u0"
    ]
    assert checkpoints == {}


def test_safe_release_receipt_requires_explicit_complete_audit_fields(tmp_path):
    campaign = _completed_campaign(
        report_overrides={"request_budget_exhausted": None}
    )
    (tmp_path / "copy-vault-campaign-receipt.json").write_text(
        json.dumps(campaign), encoding="utf-8"
    )

    result = load_release_history_audits(
        tmp_path,
        release_tags={"data-v2-campaign-copy-vault-test-u0"},
    )

    assert result["status"] == "PARTIAL"
    assert result["partial_report_count"] == 1


def test_safe_release_with_retention_cap_is_never_reported_as_complete(tmp_path):
    gap = {"start_ms": 1_000, "end_ms": 1_499, "reason": "PUBLIC_10000_FILL_RETENTION_LIMIT"}
    campaign = _completed_campaign(
        report_overrides={
            "status": "PARTIAL",
            "request_audit_status": "PARTIAL",
            "retention_cap_reached": True,
            "oldest_fill_ts_ms": 1_500,
            "rows": 10_000,
            "unresolved_gaps": [gap],
        }
    )
    (tmp_path / "copy-vault-campaign-receipt.json").write_text(
        json.dumps(campaign), encoding="utf-8"
    )

    result = load_release_history_audits(
        tmp_path,
        release_tags={"data-v2-campaign-copy-vault-test-u0"},
    )

    assert result["status"] == "PARTIAL"
    assert result["unresolved_gaps"] == [
        {
            "vault": "0x" + "a" * 40,
            "release_tag": "data-v2-campaign-copy-vault-test-u0",
            **gap,
        }
    ]
