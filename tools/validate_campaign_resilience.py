#!/usr/bin/env python3
"""Build a fail-closed resilience receipt from Dataset V2 campaign lineage.

Historical V1 manifests are immutable evidence, not current resumable campaigns.
They are reported separately and only block closure if they are still mutable
(non-terminal or leased). Current resilience is proven only from V2 lineage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_V1 = "alina.resumable_campaign.v1"
SCHEMA_V2 = "alina.resumable_campaign.v2"
LEGACY_TERMINAL_STATUSES = {"COMPLETE", "FAILED", "UNAVAILABLE", "PARTIAL", "REJECT"}


def _unit_requires_publication_receipt(unit) -> bool:
    """Require a receipt only for a unit that claims durable publication.

    A COMPLETE adapter result is not by itself proof that bytes were durably
    published. The worker annotates successful durable publication with
    durable_persisted=true before checkpointing, and the canonical publication
    reconciler uses the same predicate. Missing receipts for those durable units
    remain fail-closed; historical COMPLETE checkpoints without a durable claim
    are not retroactively treated as published.
    """
    if not isinstance(unit, dict):
        return False
    result = unit.get("result")
    return (
        isinstance(result, dict)
        and result.get("status") == "COMPLETE"
        and result.get("durable_persisted") is True
    )


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", default="catalog/campaigns")
    parser.add_argument("--output", default="catalog/CAMPAIGN_RESILIENCE_RECEIPT.json")
    args = parser.parse_args()

    rows = []
    historical_v1 = []
    violations = []

    for path in sorted(Path(args.campaign_dir).glob("*.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            violations.append({"path": str(path), "code": "INVALID_MANIFEST", "detail": str(exc)})
            continue

        if not isinstance(manifest, dict):
            violations.append({"path": str(path), "code": "INVALID_MANIFEST_TYPE"})
            continue

        campaign_id = str(manifest.get("campaign_id") or path.stem)
        schema = manifest.get("schema_version")
        status = str(manifest.get("status") or "")
        lease = manifest.get("lease")

        if campaign_id.startswith("operator-") and not re.fullmatch(
            r"[0-9a-f]{64}", str(manifest.get("operator_request_id") or "")
        ):
            violations.append({"campaign_id": campaign_id, "code": "OPERATOR_REQUEST_ID_INVALID"})

        if any(
            manifest.get(flag) is not expected
            for flag, expected in (
                ("paper_only", True),
                ("read_only", True),
                ("real_execution", False),
            )
        ):
            violations.append({"campaign_id": campaign_id, "code": "UNSAFE_EXECUTION_IDENTITY"})

        # Canonical spec: V1 is immutable historical evidence. Do not demand
        # modern V2 recovery fields from terminal history, but never allow a
        # V1 manifest to remain mutable under the current controller.
        if schema == SCHEMA_V1:
            historical_v1.append(
                {
                    "campaign_id": campaign_id,
                    "status": status,
                    "schema_version": schema,
                    "has_lease": lease is not None,
                    "completed_unit_count": len(manifest.get("completed_units") or {}),
                    "history_count": len(manifest.get("history") or []),
                }
            )
            if status not in LEGACY_TERMINAL_STATUSES:
                violations.append(
                    {
                        "campaign_id": campaign_id,
                        "code": "LEGACY_V1_MUTABLE_STATE",
                        "status": status or None,
                    }
                )
            if lease is not None and status not in LEGACY_TERMINAL_STATUSES:
                violations.append({"campaign_id": campaign_id, "code": "LEGACY_V1_LEASE_ACTIVE"})
            continue

        if schema != SCHEMA_V2:
            violations.append(
                {
                    "campaign_id": campaign_id,
                    "code": "UNSUPPORTED_CAMPAIGN_SCHEMA",
                    "schema_version": schema,
                }
            )
            continue

        required = {
            "schema_version",
            "status",
            "history",
            "completed_units",
            "checkpoint_lineage",
            "limits",
            "attempts",
            "chunk_index",
            "no_progress_count",
            "consecutive_failures",
        }
        missing = sorted(required - set(manifest))
        if missing:
            violations.append(
                {"campaign_id": campaign_id, "code": "RECOVERY_FIELDS_MISSING", "fields": missing}
            )
            continue

        if manifest.get("creation_phase") == "ANALYZE":
            expected_stage = {
                "replay": "REPLAY",
                "backtest": "BACKTEST",
                "oos": "OOS",
                "forward_paper": "FORWARD_PAPER",
                "module_pnl_proof": "PNL_PROOF",
                "scoreboard": "SCOREBOARD",
            }.get(str(manifest.get("kind") or ""))
            if expected_stage and manifest.get("analysis_stage") not in (None, expected_stage):
                violations.append({"campaign_id": campaign_id, "code": "ANALYSIS_STAGE_MISMATCH"})

        for field in ("history", "completed_units", "checkpoint_lineage"):
            if not isinstance(manifest.get(field), (list, dict)):
                violations.append(
                    {"campaign_id": campaign_id, "code": f"{field.upper()}_TYPE_INVALID"}
                )

        if status == "COMPLETE" and not manifest.get("terminal_evidence_digest"):
            violations.append({"campaign_id": campaign_id, "code": "TERMINAL_EVIDENCE_REQUIRED"})

        units = manifest.get("completed_units") or {}
        for unit_id, unit in units.items():
            if not isinstance(unit, dict) or len(str(unit.get("sha256") or "")) != 64:
                violations.append(
                    {
                        "campaign_id": campaign_id,
                        "code": "CHECKPOINT_DIGEST_INVALID",
                        "unit_id": str(unit_id),
                    }
                )
            receipt_path = Path("catalog/receipts") / f"{campaign_id}-u{unit_id}.json"
            if _unit_requires_publication_receipt(unit) and not receipt_path.is_file():
                violations.append(
                    {
                        "campaign_id": campaign_id,
                        "code": "PUBLICATION_RECEIPT_MISSING",
                        "unit_id": str(unit_id),
                    }
                )

        if manifest.get("checkpoint_lineage") and not (
            isinstance(manifest.get("cursor"), dict)
            and manifest["cursor"].get("checkpoint_id")
        ):
            violations.append({"campaign_id": campaign_id, "code": "CHECKPOINT_CURSOR_MISSING"})

        if lease is not None:
            required_lease = {"owner_run_id", "lease_token_sha256", "acquired_at", "expires_at"}
            if not isinstance(lease, dict) or required_lease - set(lease):
                violations.append({"campaign_id": campaign_id, "code": "LEASE_LINEAGE_INVALID"})

        rows.append(
            {
                "campaign_id": campaign_id,
                "status": status,
                "schema_version": schema,
                "analysis_stage": manifest.get("analysis_stage"),
                "terminal_evidence_digest": manifest.get("terminal_evidence_digest"),
                "checkpoint_count": len(manifest.get("checkpoint_lineage") or []),
                "completed_unit_count": len(units),
                "history_count": len(manifest.get("history") or []),
                "has_lease": lease is not None,
                "migrated_from_v1_sha256": manifest.get("migrated_from_v1_sha256"),
                "migrated_from_v1_history_path": manifest.get("migrated_from_v1_history_path"),
            }
        )

    if not rows:
        violations.append({"code": "NO_V2_RESILIENCE_EVIDENCE"})

    receipt = {
        "schema": "alina.campaign_resilience_receipt.v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "campaign_count": len(rows) + len(historical_v1),
        "v2_campaign_count": len(rows),
        "historical_v1_count": len(historical_v1),
        "campaigns": rows,
        "historical_v1_campaigns": historical_v1,
        "violations": violations,
        "failure_matrix": {
            "before_checkpoint_write": {
                "required_evidence": "durable_v2_campaign_manifest",
                "convergence_rule": "resume_from_last_durable_cursor",
                "observed": bool(rows)
                and not any(
                    v.get("code") in {"RECOVERY_FIELDS_MISSING", "NO_V2_RESILIENCE_EVIDENCE"}
                    for v in violations
                ),
            },
            "after_checkpoint_before_lease_release": {
                "required_evidence": "checkpoint_lineage_and_lease_validation",
                "convergence_rule": "same_unit_digest_is_idempotent",
                "observed": bool(rows)
                and not any(v.get("code") == "CHECKPOINT_CURSOR_MISSING" for v in violations),
            },
            "during_publish": {
                "required_evidence": "publication_receipt",
                "convergence_rule": "receipt_identity_conflict_refuses_publish",
                "observed": bool(rows)
                and not any(v.get("code") == "PUBLICATION_RECEIPT_MISSING" for v in violations),
            },
            "after_publish_before_terminal_manifest": {
                "required_evidence": "terminal_artifact_and_manifest_reconciliation",
                "convergence_rule": "published_artifact_adopted_without_duplicate",
                "observed": bool(rows)
                and not any(v.get("code") == "TERMINAL_EVIDENCE_REQUIRED" for v in violations),
            },
            "lease_expiry": {
                "required_evidence": "lease_token_and_expiry",
                "convergence_rule": "stale_lease_refused",
                "observed": bool(rows)
                and not any(v.get("code") == "LEASE_LINEAGE_INVALID" for v in violations),
            },
            "duplicate_worker_wakeup": {
                "required_evidence": "completed_unit_digest",
                "convergence_rule": "duplicate_unit_wakeup_no_duplicate_publication",
                "observed": bool(rows)
                and not any(v.get("code") == "CHECKPOINT_DIGEST_INVALID" for v in violations),
            },
        },
        "failure_matrix_status": "READY" if not violations else "BLOCKED",
        "status": "BLOCKED" if violations else "READY",
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    receipt["receipt_digest"] = hashlib.sha256(canonical(receipt).encode()).hexdigest()

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "campaigns": len(rows),
                "historical_v1": len(historical_v1),
                "violations": len(violations),
                "status": receipt["status"],
                "receipt_digest": receipt["receipt_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
