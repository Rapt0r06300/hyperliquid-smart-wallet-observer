"""Safety and exact-byte regression tests for preservation inventory."""
from __future__ import annotations

import pytest

from tools.preservation_inventory import InventoryError, summarize

SHA_A = "a" * 64
SHA_B = "b" * 64


def row(ident: str, quality: str, *, replay: bool = True, **overrides):
    item = {
        "dataset_id": ident, "family": "l2book", "quality_status": quality,
        "replay_compatible": replay, "bytes": 100, "sha256": SHA_A,
        "release_tag": "tag", "release_asset": f"{ident}.jsonl.gz",
        "release_container_asset": "packed.zip", "release_remote_size": 400,
        "release_remote_digest": f"sha256:{SHA_B}",
    }
    item.update(overrides)
    return item


def proof(rows):
    return {"schema_version": "alina.data_metrics.v4", "source_index_sha256": SHA_A,
            "totals": {"TOTAL_SHARDS": len(rows), "GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE": False}}


def test_exact_outer_asset_dedup_keeps_ancillary_safe_data():
    rows = [row("a", "SAFE"), row("b", "SAFE"), row("c", "PARTIAL")]
    result = summarize({"shards": rows}, proof(rows), SHA_A)
    assert result["status"] == "CATALOG_CLASSIFIED_NOT_RESTORED"
    assert result["safe_replayable_shards"] == 2
    assert result["replay_required_unique_assets"] == 1
    assert result["replay_required_download_bytes"] == 400
    assert result["replay_shard_compressed_logical_bytes"] == 200
    assert result["quality_counts"]["PARTIAL"] == 1
    assert result["recovered_partial_shards"] is None
    assert result["all_exploitable_data_restored"] is False


def test_preserves_partial_rejected_without_false_recovery():
    rows = [row("a", "PARTIAL"), row("b", "REJECT")]
    result = summarize({"shards": rows}, proof(rows), SHA_A)
    assert result["replay_required_unique_assets"] == 0
    assert result["unresolved_unsafe_shards"] == 2
    assert result["definitively_irrecoverable_shards"] is None


def test_fails_closed_on_missing_safe_digest():
    rows = [row("a", "SAFE", release_remote_digest="")]
    with pytest.raises(InventoryError, match="SHA-256"):
        summarize({"shards": rows}, proof(rows), SHA_A)


def test_fails_closed_on_inconsistent_packed_identity():
    rows = [row("a", "SAFE"), row("b", "SAFE", release_remote_size=401)]
    with pytest.raises(InventoryError, match="conflicting"):
        summarize({"shards": rows}, proof(rows), SHA_A)


def test_fails_closed_on_stale_metrics_and_duplicate_rows():
    rows = [row("a", "SAFE")]
    with pytest.raises(InventoryError, match="does not match"):
        summarize({"shards": rows}, proof(rows), SHA_B)
    with pytest.raises(InventoryError, match="duplicate"):
        summarize({"shards": rows * 2}, proof(rows * 2), SHA_A)


def test_safe_non_replayable_is_explicitly_incomplete():
    rows = [row("a", "SAFE", replay=False)]
    report = summarize({"shards": rows}, proof(rows), SHA_A)
    assert report["status"] == "INCOMPLETE_SAFE_REPLAY_COVERAGE"
    assert report["safe_non_replayable_shards"] == 1
    assert report["replay_required_download_bytes"] == 0


def test_replay_ready_preflight_keeps_verified_cache(monkeypatch, tmp_path):
    from tools import restore_alina

    actual = {}

    def fake_restore(repository, destination, **options):
        actual["prune_unselected"] = options["prune_unselected"]
        return {"enough_disk_for_release_assets": True,
                "unverified_source_asset_count": 0}

    monkeypatch.setattr(restore_alina, "restore_everything", fake_restore)
    code = restore_alina.main([
        "--replay-ready", "--preflight-only", "--destination", str(tmp_path),
    ])
    assert code == 0
    assert actual["prune_unselected"] is False
