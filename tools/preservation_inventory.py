#!/usr/bin/env python3
"""Read-only, fail-closed inventory of the canonical Alina preservation corpus.

Reports exactly what is indexed, what is eligible for SAFE replay restoration,
and what must remain quarantined for later repair. Never downloads or deletes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.partitioned_data_index import read_index
except ModuleNotFoundError:
    from partitioned_data_index import read_index

REPO = Path(__file__).resolve().parents[1]
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
STATUSES = {"SAFE", "PARTIAL", "REJECT", "STALE", "NO_DATA"}


class InventoryError(ValueError):
    """Insufficient or contradictory evidence: never certify coverage."""


def summarize(index: Mapping[str, Any], metrics: Mapping[str, Any], index_digest: str) -> dict[str, Any]:
    rows = index.get("shards")
    totals = metrics.get("totals")
    if not isinstance(rows, list) or not isinstance(totals, Mapping):
        raise InventoryError("catalog/metrics missing verified shard list or totals")
    if (metrics.get("source_index_sha256") != index_digest
            or metrics.get("schema_version") != "alina.data_metrics.v4"
            or type(totals.get("TOTAL_SHARDS")) is not int
            or totals["TOTAL_SHARDS"] != len(rows)):
        raise InventoryError("DATA_METRICS does not match canonical DATA_INDEX")

    counts: Counter[str] = Counter()
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    seen_ids: set[str] = set()
    outer: dict[tuple[str, str], tuple[int, str]] = {}
    replay_shards = 0
    replay_logical_bytes = 0
    safe_not_replayable = 0
    recoverable_unknown = 0
    quality_bytes_known: Counter[str] = Counter()
    quality_bytes_unknown: Counter[str] = Counter()
    unresolved_with_source = 0
    unresolved_without_source = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise InventoryError("invalid shard row")
        ident = row.get("dataset_id")
        if not isinstance(ident, str) or not ident or ident in seen_ids:
            raise InventoryError("duplicate or missing dataset_id")
        seen_ids.add(ident)
        status = row.get("quality_status")
        if status not in STATUSES:
            raise InventoryError(f"unrecognized quality_status for {ident}")
        family = row.get("family")
        if not isinstance(family, str) or not family:
            raise InventoryError(f"missing family for {ident}")
        counts[status] += 1
        by_family[family][status] += 1
        size = row.get("bytes")
        if type(size) is int and size >= 0:
            quality_bytes_known[status] += size
        else:
            quality_bytes_unknown[status] += 1
        if status in ("PARTIAL", "REJECT", "STALE"):
            # Source identity is a prerequisite for repair, not proof of recovery.
            recoverable_unknown += 1
            tag = row.get("release_tag")
            member = row.get("release_asset")
            sha = row.get("sha256")
            if (isinstance(tag, str) and tag
                    and isinstance(member, str) and member
                    and isinstance(sha, str) and SHA256.fullmatch(sha.lower())):
                unresolved_with_source += 1
            else:
                unresolved_without_source += 1
        if status != "SAFE":
            continue
        if row.get("replay_compatible") is not True:
            safe_not_replayable += 1
            continue
        tag = row.get("release_tag")
        member = row.get("release_asset")
        container = row.get("release_container_asset")
        logical_size = row.get("bytes")
        digest = row.get("sha256")
        if (not isinstance(tag, str) or not tag
                or not isinstance(member, str) or not member
                or type(logical_size) is not int or logical_size < 0
                or not isinstance(digest, str) or not SHA256.fullmatch(digest.lower())):
            raise InventoryError(f"SAFE replayable shard has incomplete identity: {ident}")
        if container:
            if not isinstance(container, str):
                raise InventoryError(f"invalid packed asset reference: {ident}")
            outer_size = row.get("release_remote_size")
            outer_digest = str(row.get("release_remote_digest") or "").removeprefix("sha256:").lower()
            key = (tag, container)
        else:
            outer_size = logical_size
            outer_digest = digest.lower()
            key = (tag, member)
        if (type(outer_size) is not int or outer_size < 0
                or not SHA256.fullmatch(outer_digest)):
            raise InventoryError(f"missing SHA-256/size for Release asset: {ident}")
        evidence = (outer_size, outer_digest)
        if key in outer and outer[key] != evidence:
            raise InventoryError(f"conflicting immutable Release asset: {key}")
        outer[key] = evidence
        replay_shards += 1
        replay_logical_bytes += logical_size

    # Deduplicate packed ZIPs: a single outer asset may hold many SAFE shards.
    result = {
        "schema": "alina.preservation_inventory.v1",
        "status": "CATALOG_CLASSIFIED_NOT_RESTORED",
        "catalog_index_sha256": index_digest,
        "indexed_shards": len(rows),
        "quality_counts": {k: counts[k] for k in sorted(STATUSES)},
        "safe_replayable_shards": replay_shards,
        "safe_non_replayable_shards": safe_not_replayable,
        "replay_required_unique_assets": len(outer),
        "replay_required_download_bytes": sum(size for size, _ in outer.values()),
        "replay_shard_compressed_logical_bytes": replay_logical_bytes,
        "unresolved_unsafe_shards": recoverable_unknown,
        "unresolved_with_source_identity": unresolved_with_source,
        "unresolved_missing_source_identity": unresolved_without_source,
        "compressed_logical_bytes_known_by_status": {
            k: quality_bytes_known[k] for k in sorted(STATUSES)
        },
        "shards_missing_logical_byte_size_by_status": {
            k: quality_bytes_unknown[k] for k in sorted(STATUSES)
        },
        "by_family": {name: dict(sorted(c.items())) for name, c in sorted(by_family.items())},
        "global_trade_uniqueness_certified": totals.get("GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE") is True,
        "all_exploitable_data_restored": False,
        "recovered_partial_shards": None,
        "definitively_irrecoverable_shards": None,
        "notes": [
            "Catalog classification is not byte-level restoration certification.",
            "PARTIAL, STALE and REJECT remain preserved for evidence-based review; never delete on this report.",
            "Known logical compressed bytes are per-shard, not deduplicated outer Release download size.",
            "A traceable non-SAFE source is not yet certified repairable; missing byte size is never imputed as zero.",
            "Ancillary SAFE market data (L2/BBO/capacity/tickers) is included even if it has zero trades.",
            "Never promote an unsafe shard without a new immutable manifest and strict validation.",
        ],
    }
    if replay_shards != counts["SAFE"]:
        result["status"] = "INCOMPLETE_SAFE_REPLAY_COVERAGE"
    return result



def iter_recovery_triage(index: Mapping[str, Any]):
    """Yield indexed repair candidates, without declaring them usable or recoverable.

    This is a planning receipt, not proof that a remote asset still exists.
    The source requirements match the immutable outer-asset evidence used by
    replay-ready selection; nothing is downloaded, deleted or reclassified.
    """
    default_repository = index.get("release_repository_default")
    for row in index["shards"]:
        status = row["quality_status"]
        if status not in ("PARTIAL", "REJECT", "STALE") and not (
            status == "SAFE" and row.get("replay_compatible") is not True
        ):
            continue
        missing = []
        for field in ("release_tag", "release_asset", "sha256"):
            value = row.get(field)
            if (not isinstance(value, str) or not value
                    or (field == "sha256" and not SHA256.fullmatch(value.lower()))):
                missing.append(field)
        size = row.get("bytes")
        if type(size) is not int or size < 0:
            missing.append("bytes")
        container = row.get("release_container_asset")
        if container is not None and container != "":
            if not isinstance(container, str):
                missing.append("release_container_asset")
            remote_size = row.get("release_remote_size")
            remote_digest = row.get("release_remote_digest")
            if type(remote_size) is not int or remote_size < 0:
                missing.append("release_remote_size")
            if (not isinstance(remote_digest, str)
                    or not SHA256.fullmatch(remote_digest.removeprefix("sha256:").lower())):
                missing.append("release_remote_digest")
        repository = row.get("release_repository") or default_repository
        if repository not in (None, "Rapt0r06300/hyperliquid-smart-wallet-observer"):
            missing.append("canonical_release_repository")
        raw_reasons = row.get("quality_reasons")
        reasons = sorted({str(x) for x in raw_reasons if str(x)}) if isinstance(raw_reasons, list) else []
        yield {
            "dataset_id": row["dataset_id"],
            "quality_status": status,
            "family": row["family"],
            "manifest_path": row.get("manifest_path"),
            "release_tag": row.get("release_tag"),
            "release_asset": row.get("release_asset"),
            "release_container_asset": container,
            "sha256": row.get("sha256"),
            "compressed_logical_bytes": size if "bytes" not in missing else None,
            "quality_reasons": reasons,
            "replay_compatible": row.get("replay_compatible") is True,
            "source_evidence": "INDEX_IDENTITY_COMPLETE_NOT_VERIFIED" if not missing else "INDEX_IDENTITY_INCOMPLETE",
            "missing_evidence": sorted(missing),
            "recovery_status": "NOT_ASSESSED",
            "validation_allowed": False,
        }


def write_recovery_triage(index: Mapping[str, Any], report: Mapping[str, Any], target: Path) -> dict[str, Any]:
    """Write a SHA-bound, self-checksummed JSONL ledger without overwriting evidence."""
    target = Path(target)
    if target.is_symlink() or target.exists():
        raise InventoryError("triage destination already exists; refusing overwrite")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise InventoryError("triage parent must be an existing non-symlink directory")
    checksum = hashlib.sha256()
    count = 0
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=target.parent,
            prefix=".alina-triage-", suffix=".tmp", delete=False,
        ) as out:
            temp_path = Path(out.name)
            header = {
                "kind": "header", "schema": "alina.recovery_triage.v1",
                "catalog_index_sha256": report["catalog_index_sha256"],
                "catalog_status": report["status"],
                "recoverability_certified": False,
            }
            out.write(json.dumps(header, sort_keys=True) + "\n")
            for candidate in iter_recovery_triage(index):
                line = json.dumps({"kind": "candidate", **candidate}, sort_keys=True) + "\n"
                out.write(line)
                checksum.update(line.encode("utf-8"))
                count += 1
            expected = report["unresolved_unsafe_shards"] + report["safe_non_replayable_shards"]
            if count != expected:
                raise InventoryError("triage candidate count diverges from indexed census")
            out.write(json.dumps({
                "kind": "footer", "candidate_count": count,
                "candidates_sha256": checksum.hexdigest(),
            }, sort_keys=True) + "\n")
            out.flush()
            os.fsync(out.fileno())
        # Link atomically without replacing any already-existing user file.
        os.link(temp_path, target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return {"triage_path": str(target), "candidate_count": count,
            "candidates_sha256": checksum.hexdigest()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=REPO / "catalog/DATA_INDEX.json")
    parser.add_argument("--metrics", type=Path, default=REPO / "catalog/DATA_METRICS.json")
    parser.add_argument("--triage-jsonl", type=Path, help="Create a non-destructive, SHA-bound repair candidate ledger")
    args = parser.parse_args(argv)
    try:
        raw = args.index.read_bytes()
        index = read_index(args.index)
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        report = summarize(index, metrics, hashlib.sha256(raw).hexdigest())
        if args.triage_jsonl is not None:
            report["triage"] = write_recovery_triage(index, report, args.triage_jsonl)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "INVENTORY_INCOMPLETE", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "CATALOG_CLASSIFIED_NOT_RESTORED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
