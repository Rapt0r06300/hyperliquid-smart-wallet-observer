#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
reg = json.loads((root / "catalog/DATA_QUALITY_REGISTRY.json").read_text())
cat = json.loads((root / "catalog/DATA_CATALOG.json").read_text())
index = json.loads((root / "catalog/DATA_INDEX.json").read_text())

statuses = set(reg["status_vocabulary"])
assert statuses == {"SAFE", "PARTIAL", "STALE", "REJECT", "NO_DATA"}
assert reg["validation_allowed_statuses"] == ["SAFE"]
assert reg["policy"]["legacy_import_allowed"] is False
assert reg["policy"]["secrets_forbidden"] is True
assert reg["policy"]["self_hosted_forbidden"] is True
assert reg["policy"]["user_pc_forbidden"] is True
assert cat["legacy_sources"]["enabled"] is False
assert cat["storage"]["replay_selection"] == "SAFE_MANIFEST_ONLY"

shards = index.get("shards") or []
assert isinstance(shards, list)
default_repo = index.get("release_repository_default")
assert default_repo in (None, "Rapt0r06300/hyperliquid-smart-wallet-observer")
for row in shards:
    assert row["quality_status"] in statuses
    if row["quality_status"] == "SAFE":
        for key in (
            "bytes",
            "sha256",
            "release_tag",
            "release_asset",
            "event_count",
        ):
            assert row.get(key) not in (None, ""), f"SAFE index row missing {key}"
        assert int(row["bytes"]) > 0
        assert int(row["event_count"]) > 0
        assert row.get("replay_compatible") is True, "SAFE must be explicitly replay-compatible"
        repository = row["release_repository"] if "release_repository" in row else default_repo
        assert repository == "Rapt0r06300/hyperliquid-smart-wallet-observer"
    manifest_path = root / row["manifest_path"]
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text())
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

expected_active = (
    "SAFE"
    if any(row["quality_status"] == "SAFE" for row in shards)
    else ("PARTIAL" if shards else "NO_DATA")
)
assert index["active_data_status"] == expected_active
assert reg["active_dataset"]["status"] == expected_active
assert reg["active_dataset"]["validation_allowed"] is (expected_active == "SAFE")
# Dataset integrity may authorize validation, but must never claim profitable PnL.
assert reg["active_dataset"]["proof_of_pnl_allowed"] is False
assert cat["active_data_status"] == expected_active
assert int(cat.get("indexed_shard_count") or 0) == len(shards)
assert int(cat.get("safe_shard_count") or 0) == sum(
    1 for row in shards if row["quality_status"] == "SAFE"
)
print("Alina dataset V2 policy: OK")