from tools.audit_mixed_release_assets import inventory


def _row(dataset_id, status, asset, size=100):
    return {
        "dataset_id": dataset_id,
        "quality_status": status,
        "release_tag": "one-release",
        "release_container_asset": asset,
        "release_remote_size": size,
        "release_remote_digest": "sha256:" + "a" * 64,
    }


def test_audit_counts_mixed_physical_assets_once():
    rows = [
        _row("safe", "SAFE", "both.zip"),
        _row("rejected", "REJECT", "both.zip"),
        _row("p", "PARTIAL", "both.zip"),
        _row("only-reject", "REJECT", "bad.gz"),
        _row("only-safe", "SAFE", "good.gz"),
    ]
    result = inventory(rows)
    assert result["indexed_shards"] == 5
    assert result["physical_assets_with_indexed_members"] == 3
    assert result["assets_with_reject_members"] == 2
    assert result["reject_only_assets"] == 1
    assert result["safe_and_reject_assets"] == 1
    assert result["mixed_status_assets"] == 1
    assert result["mixed_samples"][0]["member_status_counts"] == {"PARTIAL": 1, "REJECT": 1, "SAFE": 1}


def test_audit_fails_closed_on_ambiguous_locator_and_identity():
    rows = [
        _row("safe", "SAFE", "packed.zip"),
        _row("reject", "REJECT", "packed.zip", size=101),
        {"dataset_id": "no-release", "quality_status": "REJECT"},
    ]
    result = inventory(rows)
    assert result["mixed_with_inconsistent_remote_identity"] == 1
    assert result["shards_without_canonical_physical_locator"] == {"REJECT": 1}
