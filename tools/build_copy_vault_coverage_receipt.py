#!/usr/bin/env python3
"""Build the canonical Copy-Vault full-universe coverage receipt.

The receipt is selection/epoch scoped. Historical failed/superseded campaigns are
kept as evidence but cannot poison an unrelated frozen selection. Missing or
cutoff-unavailable lanes are explicit MORE_DATA/BLOCKED evidence, never silently
counted as collected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ACTIVE = {"PENDING", "RUNNING", "CONTINUATION_REQUIRED", "STUCK"}
TERMINAL = {"COMPLETE", "FAILED", "UNAVAILABLE", "PARTIAL", "REJECT"}
EXPECTED_CUTOFF_REASONS = {
    "COLLECTION_CUTOFF_BEFORE_CLAIM",
    "DRAIN_CUTOFF_INTERRUPTED_WITHOUT_DURABLE_PROGRESS",
    "DRAIN_CUTOFF_INTERRUPTED_AFTER_DURABLE_PROGRESS",
    "analysis_drain_deadline_expired_without_checkpoint",
    "analysis_drain_deadline_expired_with_checkpoint",
}
SUPERSEDED_REASONS = {
    "SUPERSEDED_BY_BOUNDED_V7_LANES",
    "SUPERSEDED_BY_BOUNDED_COPY_VAULT_LANES",
}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _publication_evidence(manifest: dict[str, Any]) -> tuple[int, int, int, int]:
    collected = published = qualified = units = 0
    for unit in (manifest.get("completed_units") or {}).values():
        if not isinstance(unit, dict):
            continue
        units += 1
        result = unit.get("result") if isinstance(unit.get("result"), dict) else {}
        if not isinstance(result, dict):
            continue
        if result.get("status") == "COMPLETE" or manifest.get("status") == "COMPLETE":
            collected += 1
        if result.get("durable_persisted") is True and (
            result.get("release_tag")
            or result.get("evidence_release_tag")
            or result.get("release_repository")
            or result.get("evidence_repository")
        ):
            published += 1
        qualified += int(result.get("safe_count") or 0)
    return collected, published, qualified, units


def _selection_count(path: Path) -> int | None:
    row = load(path)
    if not isinstance(row, dict):
        return None
    vaults = row.get("vaults")
    return len(vaults) if isinstance(vaults, list) else None


def build_receipt(*, campaign_dir: Path, phase_path: Path, output: Path) -> dict[str, Any]:
    phase = load(phase_path, {})
    source_epoch = (
        phase.get("source_collection_epoch")
        if phase.get("phase") == "ANALYZE"
        else phase.get("epoch")
    )
    candidates: list[dict[str, Any]] = []
    invalid_manifests: list[str] = []

    for path in sorted(campaign_dir.glob("copy-vault-*.json")):
        row = load(path)
        if not isinstance(row, dict):
            invalid_manifests.append(str(path))
            continue
        if row.get("kind") != "copy_vault_collection":
            continue
        if row.get("schema_version") != "alina.resumable_campaign.v2":
            continue
        if source_epoch is not None and int(row.get("phase_epoch") or 0) != int(source_epoch):
            continue
        cursor = row.get("cursor") if isinstance(row.get("cursor"), dict) else {}
        selection_sha = str(cursor.get("selection_sha256") or "")
        selection_file = str(cursor.get("selection_file") or "")
        shard_count = cursor.get("vault_shard_count")
        shard_index = cursor.get("vault_shard_index")
        universe_count = cursor.get("max_vaults")
        if (
            len(selection_sha) != 64
            or not selection_file
            or isinstance(shard_count, bool)
            or not isinstance(shard_count, int)
            or shard_count < 1
            or isinstance(shard_index, bool)
            or not isinstance(shard_index, int)
            or shard_index < 0
            or shard_index >= shard_count
            or isinstance(universe_count, bool)
            or not isinstance(universe_count, int)
            or universe_count < 1
        ):
            invalid_manifests.append(str(path))
            continue
        candidates.append({
            "path": path,
            "manifest": row,
            "selection_sha256": selection_sha,
            "selection_file": selection_file,
            "shard_count": shard_count,
            "shard_index": shard_index,
            "universe_count": universe_count,
            "created_at": str(row.get("created_at") or ""),
        })

    plans: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        plans[(row["selection_sha256"], row["shard_count"])].append(row)

    plan_summaries: list[dict[str, Any]] = []
    for (selection_sha, shard_count), rows in plans.items():
        rows.sort(key=lambda x: (x["created_at"], str(x["manifest"].get("campaign_id") or "")))
        universe_values = {int(x["universe_count"]) for x in rows}
        selection_files = {str(x["selection_file"]) for x in rows}
        indices = [int(x["shard_index"]) for x in rows]
        universe_count = max(universe_values) if universe_values else 0
        users_per_largest_lane = (
            (universe_count + shard_count - 1) // shard_count if shard_count else universe_count
        )

        selection_verified = False
        selected_count = None
        selection_path = None
        for raw_path in sorted(selection_files):
            candidate = Path(raw_path)
            if candidate.is_file():
                selection_path = candidate
                actual_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
                selected_count = _selection_count(candidate)
                selection_verified = (
                    actual_sha == selection_sha
                    and selected_count is not None
                    and selected_count == universe_count
                )
                if selection_verified:
                    break

        index_counts = Counter(indices)
        duplicate_indices = sorted(i for i, n in index_counts.items() if n > 1)
        missing_indices = sorted(set(range(shard_count)) - set(indices))
        out_of_range_indices = sorted(i for i in indices if i < 0 or i >= shard_count)

        collected_lanes = published_lanes = qualified_shards = completed_units = 0
        terminal_lanes = active_lanes = explicit_unavailable = 0
        unexpected_failures: list[dict[str, Any]] = []
        lane_rows: list[dict[str, Any]] = []

        for item in rows:
            manifest = item["manifest"]
            collected, published, qualified, units = _publication_evidence(manifest)
            collected_lanes += int(collected > 0)
            published_lanes += int(published > 0)
            qualified_shards += qualified
            completed_units += units
            status = str(manifest.get("status") or "")
            reason = str(manifest.get("status_reason") or "")
            if status in TERMINAL:
                terminal_lanes += 1
            if status in ACTIVE:
                active_lanes += 1
            if status in {"UNAVAILABLE", "PARTIAL"} and reason in EXPECTED_CUTOFF_REASONS:
                explicit_unavailable += 1
            elif status == "FAILED" and reason in SUPERSEDED_REASONS:
                pass
            elif status in {"FAILED", "STUCK", "REJECT"}:
                unexpected_failures.append({
                    "campaign_id": manifest.get("campaign_id"),
                    "status": status,
                    "reason": reason,
                })
            lane_rows.append({
                "campaign_id": manifest.get("campaign_id"),
                "shard_index": item["shard_index"],
                "status": status,
                "status_reason": reason or None,
                "completed_units": units,
                "collected": collected > 0,
                "published": published > 0,
            })

        plan_valid = (
            len(universe_values) == 1
            and len(selection_files) == 1
            and selection_verified
            and users_per_largest_lane <= 10
            and not duplicate_indices
            and not missing_indices
            and not out_of_range_indices
            and len(rows) == shard_count
        )
        no_silent_loss = (
            not duplicate_indices
            and not missing_indices
            and not out_of_range_indices
            and len(rows) == shard_count
            and terminal_lanes + active_lanes == len(rows)
        )
        fully_published = (
            plan_valid
            and no_silent_loss
            and collected_lanes == shard_count
            and published_lanes == shard_count
            and not unexpected_failures
        )
        if not plan_valid:
            status = "BLOCKED"
        elif fully_published:
            status = "OBSERVED"
        elif no_silent_loss:
            status = "MORE_DATA"
        else:
            status = "BLOCKED"

        plan_summaries.append({
            "selection_sha256": selection_sha,
            "selection_file": str(selection_path) if selection_path else sorted(selection_files)[0],
            "selection_verified": selection_verified,
            "selected_count": selected_count,
            "declared_universe_count": universe_count,
            "scheduled_lane_count": shard_count,
            "manifest_lane_count": len(rows),
            "users_per_largest_lane": users_per_largest_lane,
            "max_users_per_lane_contract": 10,
            "lane_indices": sorted(indices),
            "duplicate_lane_indices": duplicate_indices,
            "missing_lane_indices": missing_indices,
            "out_of_range_lane_indices": out_of_range_indices,
            "terminal_lane_count": terminal_lanes,
            "active_lane_count": active_lanes,
            "explicit_unavailable_lane_count": explicit_unavailable,
            "collected_lane_count": collected_lanes,
            "published_lane_count": published_lanes,
            "qualified_shard_count": qualified_shards,
            "completed_unit_count": completed_units,
            "unexpected_failures": unexpected_failures,
            "plan_valid": plan_valid,
            "no_silent_loss": no_silent_loss,
            "fully_published": fully_published,
            "status": status,
            "created_at_max": max(x["created_at"] for x in rows),
            "campaigns": lane_rows,
        })

    plan_summaries.sort(key=lambda x: (x["created_at_max"], x["scheduled_lane_count"]))
    # A malformed/superseded fan-out must remain visible evidence, but it must
    # not replace a newer-or-older structurally valid frozen-selection plan as
    # the authoritative coverage basis.  Prefer the latest valid plan and fail
    # closed only when no valid plan exists at all.
    valid_plans = [row for row in plan_summaries if row.get("plan_valid") is True]
    authoritative = valid_plans[-1] if valid_plans else (plan_summaries[-1] if plan_summaries else None)
    overall = str(authoritative["status"]) if authoritative else "UNAVAILABLE"

    body: dict[str, Any] = {
        "schema": "alina.copy_vault_coverage_receipt.v2",
        "phase": phase.get("phase"),
        "phase_epoch": phase.get("epoch"),
        "source_collection_epoch": source_epoch,
        "collection_cutoff_at_utc": phase.get("collection_cutoff_at_utc"),
        "candidate_campaign_count": len(candidates),
        "invalid_manifest_paths": sorted(invalid_manifests),
        "plans": plan_summaries,
        "authoritative_plan": authoritative,
        "reconciliation": {
            "selection_present": bool(authoritative),
            "selection_verified": bool(authoritative and authoritative["selection_verified"]),
            "sharding_present": bool(authoritative and authoritative["scheduled_lane_count"] > 0),
            "ten_user_limit_respected": bool(
                authoritative and authoritative["users_per_largest_lane"] <= 10
            ),
            "all_lane_indices_accounted": bool(
                authoritative
                and not authoritative["missing_lane_indices"]
                and not authoritative["duplicate_lane_indices"]
                and not authoritative["out_of_range_lane_indices"]
            ),
            "publication_complete": bool(authoritative and authoritative["fully_published"]),
            "no_silent_loss": bool(authoritative and authoritative["no_silent_loss"]),
        },
        "status": overall,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    body["receipt_digest"] = digest(body)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", default="catalog/campaigns")
    parser.add_argument("--phase-path", default="control/alina-phase.json")
    parser.add_argument("--output", default="catalog/COPY_VAULT_COVERAGE_RECEIPT.json")
    args = parser.parse_args()
    receipt = build_receipt(
        campaign_dir=Path(args.campaign_dir),
        phase_path=Path(args.phase_path),
        output=Path(args.output),
    )
    print(json.dumps({
        "status": receipt["status"],
        "source_collection_epoch": receipt["source_collection_epoch"],
        "candidate_campaign_count": receipt["candidate_campaign_count"],
        "receipt_digest": receipt["receipt_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
