#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from tools.partitioned_data_index import iter_index_rows
except ModuleNotFoundError:
    from partitioned_data_index import iter_index_rows

parser = argparse.ArgumentParser(description="Validate the canonical dataset policy")
parser.add_argument(
    "--catalog-only",
    action="store_true",
    help="Validate the complete SHA-bound index and counters without materializing immutable manifest receipts",
)
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]
reg = json.loads((root / "catalog/DATA_QUALITY_REGISTRY.json").read_text(encoding="utf-8"))
cat = json.loads((root / "catalog/DATA_CATALOG.json").read_text(encoding="utf-8"))
index_path = root / "catalog/DATA_INDEX.json"
index_root = json.loads(index_path.read_text(encoding="utf-8"))


def _validate_manifest(root_path: Path, row: dict[str, object]) -> None:
    """Validate one immutable manifest without changing any SAFE data."""
    manifest_relative = row["manifest_path"]
    assert isinstance(manifest_relative, str)
    manifest_path = root_path / manifest_relative
    # read_bytes() is the authoritative fail-closed path and type check.
    # Skip redundant stat() for each of the million-plus indexed manifests.
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["dataset_id"] == row["dataset_id"]
    assert manifest["quality_status"] == row["quality_status"]
    if row["quality_status"] == "SAFE":
        assert manifest.get("sha256") == row["sha256"], "SAFE receipt sha mismatch"
        assert manifest.get("replay_compatible") is True, "SAFE replay proof missing"
        assert str(manifest.get("replay_schema_version") or ""), "SAFE replay schema missing"
        if row.get("replay_schema_version") is not None:
            assert row["replay_schema_version"] == manifest["replay_schema_version"], "SAFE replay schema mismatch"
    expected_validation = row["quality_status"] == "SAFE" and row.get("replay_compatible") is True
    assert manifest["validation_allowed"] is expected_validation

statuses = set(reg["status_vocabulary"])
assert statuses == {"SAFE", "PARTIAL", "STALE", "REJECT", "NO_DATA"}
assert reg["validation_allowed_statuses"] == ["SAFE"]
assert reg["policy"]["legacy_import_allowed"] is False
assert reg["policy"]["secrets_forbidden"] is True
assert reg["policy"]["self_hosted_forbidden"] is True
assert reg["policy"]["user_pc_forbidden"] is True
assert cat["legacy_sources"]["enabled"] is False
assert cat["storage"]["replay_selection"] == "SAFE_MANIFEST_ONLY"

default_repo = index_root.get("release_repository_default")
assert default_repo in (None, "Rapt0r06300/hyperliquid-smart-wallet-observer")
counts: Counter[str] = Counter()
indexed_shards = 0
has_safe = False
pending = deque()
manifest_workers = max(4, min(64, (os.cpu_count() or 4) * 4))

with ThreadPoolExecutor(max_workers=manifest_workers, thread_name_prefix="dataset-quality") as executor:
    for row in iter_index_rows(index_path):
        assert isinstance(row, dict)
        status = row["quality_status"]
        assert status in statuses
        if status == "SAFE":
            has_safe = True
            for key in ("bytes", "sha256", "release_tag", "release_asset", "event_count"):
                assert row.get(key) not in (None, ""), f"SAFE index row missing {key}"
            assert int(row["bytes"]) > 0
            assert int(row["event_count"]) > 0
            assert row.get("replay_compatible") is True, "SAFE must be explicitly replay-compatible"
            repository = row["release_repository"] if "release_repository" in row else default_repo
            assert repository == "Rapt0r06300/hyperliquid-smart-wallet-observer"
        manifest_relative = row.get("manifest_path")
        assert isinstance(manifest_relative, str) and manifest_relative.startswith("datasets/")
        if not args.catalog_only:
            pending.append(executor.submit(_validate_manifest, root, row))
            if len(pending) >= manifest_workers * 4:
                pending.popleft().result()
        counts[status] += 1
        indexed_shards += 1
    while pending:
        pending.popleft().result()

expected_active = "SAFE" if has_safe else ("PARTIAL" if indexed_shards else "NO_DATA")
assert index_root["active_data_status"] == expected_active
assert cat["active_data_status"] == expected_active
assert reg["active_dataset"]["status"] == expected_active
assert reg["active_dataset"]["validation_allowed"] is (expected_active == "SAFE")
# Dataset integrity may authorize validation, but must never claim profitable PnL.
assert reg["active_dataset"]["proof_of_pnl_allowed"] is False
assert int(cat.get("indexed_shard_count") or 0) == indexed_shards
# Never certify catalog-wide counters from a SAFE-only spot check.
# All four shard classes must agree with the exact SHA-bound index.
assert set(counts).issubset({"SAFE", "PARTIAL", "REJECT", "STALE"}), "index contains non-shard status"
assert sum(counts.values()) == indexed_shards
for status, catalog_key, registry_key in (
    ("SAFE", "safe_shard_count", "safe_count"),
    ("PARTIAL", "partial_shard_count", "partial_count"),
    ("REJECT", "reject_shard_count", "reject_count"),
    ("STALE", "stale_shard_count", "stale_count"),
):
    expected = counts[status]
    assert cat.get(catalog_key) == expected, f"catalog {status} count differs from index"
    assert reg["active_dataset"].get(registry_key) == expected, f"registry {status} count differs from index"
assert reg["active_dataset"].get("indexed_shards") == indexed_shards
print("Alina dataset V2 policy: OK (" + ("catalog-only" if args.catalog_only else "full-manifest") + ")")
