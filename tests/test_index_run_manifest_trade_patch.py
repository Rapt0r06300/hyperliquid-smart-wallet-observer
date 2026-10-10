from tools.index_run_manifest import (
    BYBIT_IDENTITY_VERSION,
    _apply_replay_patch,
    _apply_trade_count_patch,
)


def test_replay_patch_cannot_overwrite_independent_exact_trade_count():
    manifest = {
        "dataset_id": "bybit-archive",
        "venue": "bybit",
        "sha256": "a" * 64,
        "trade_count": 190000,
        "trade_count_exact": True,
    }
    _apply_replay_patch(
        manifest,
        {
            "bybit-archive": {
                "asset_sha256": "a" * 64,
                "trade_count": 0,
                "trade_count_exact": False,
                "record_count": 190000,
                "replay_compatible": False,
                "replay_reason": "INVALID_RECORD",
            }
        },
    )
    assert manifest["trade_count"] == 190000
    assert manifest["trade_count_exact"] is True


def test_trade_count_patch_is_sha_bound_and_old_bybit_unique_is_fail_closed():
    manifest = {
        "dataset_id": "bybit-archive",
        "venue": "bybit",
        "sha256": "a" * 64,
        "trade_count": 0,
        "trade_count_exact": False,
        "unique_trade_count": 138698,
        "unique_trade_count_exact": True,
    }
    _apply_trade_count_patch(
        manifest,
        {
            "bybit-archive": {
                "asset_sha256": "a" * 64,
                "trade_count": 190000,
                "trade_count_exact": True,
                "unique_trade_count": 138698,
                "unique_trade_count_exact": True,
                "unique_identity_method": "full_native_or_deterministic_composite_string_v2",
            }
        },
    )
    assert manifest["trade_count"] == 190000
    assert manifest["trade_count_exact"] is True
    assert manifest["unique_trade_count"] is None
    assert manifest["unique_trade_count_exact"] is False

    current = dict(manifest)
    current["unique_trade_count"] = None
    _apply_trade_count_patch(
        current,
        {
            "bybit-archive": {
                "asset_sha256": "a" * 64,
                "trade_count": 190000,
                "trade_count_exact": True,
                "unique_trade_count": 190000,
                "unique_trade_count_exact": True,
                "unique_identity_method": BYBIT_IDENTITY_VERSION,
            }
        },
    )
    assert current["unique_trade_count"] == 190000
    assert current["unique_trade_count_exact"] is True



def test_compacted_run_manifest_normalizes_remote_release_alias_and_zip_member():
    from tools.index_run_manifest import _normalize_manifest, _valid_release_locator

    manifest = _normalize_manifest({
        "dataset_id": "bybit-trades-btc",
        "sha256": "a" * 64,
        "bytes": 100, "event_count": 10,
        "release_asset": "inner.jsonl.gz",
        "release": {
            "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "release_tag": "data-v2-real-data-tag",
            "asset_id": 100,
            "asset_name": "packed-shards-0000.zip",
            "member_name": "inner.jsonl.gz",
            "storage": "zip_entry",
            "remote_size": 1000,
            "remote_digest": "sha256:" + "b" * 64,
        },
    })
    assert manifest["release_tag"] == "data-v2-real-data-tag"
    assert manifest["release_asset"] == "inner.jsonl.gz"
    assert manifest["release_container_asset"] == "packed-shards-0000.zip"
    assert manifest["release_member"] == "inner.jsonl.gz"
    assert manifest["release_remote_size"] == 1000
    assert _valid_release_locator(manifest) is True


def test_compacted_safe_locator_requires_outer_remote_sha_not_just_inner_hash():
    from tools.index_run_manifest import _normalize_manifest, _valid_release_locator
    raw = {
        "sha256": "a" * 64, "release_asset": "inner.jsonl.gz",
        "release": {
            "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "release_tag": "data-v2-real",
            "asset_name": "packed-shards-0000.zip",
            "member_name": "inner.jsonl.gz",
            "storage": "zip_entry",
            "remote_size": 1234,
            "remote_digest": None,
        },
    }
    assert _valid_release_locator(_normalize_manifest(raw)) is False


def test_unpacked_release_tag_backcompat_kept():
    from tools.index_run_manifest import _normalize_manifest, _valid_release_locator
    raw = {
        "release_asset": "trades.jsonl.gz",
        "release": {
            "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "tag": "old-direct",
            "asset_name": "trades.jsonl.gz",
        },
    }
    manifest = _normalize_manifest(raw)
    assert manifest["release_tag"] == "old-direct"
    assert _valid_release_locator(manifest) is True



def test_compacted_publisher_keeps_canonical_manifest_release_independent_of_data_tag():
    from tools.index_run_manifest import _index_row, _normalize_manifest
    from pathlib import Path
    base = Path("/tmp/alina-test-case")
    raw = {
        "dataset_id": "immutable-trade",
        "release_asset": "immutable-trade.jsonl.gz",
        "release": {
            "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "release_tag": "data-v2-collection-part0",
            "asset_name": "packed-shards-0000.zip",
            "member_name": "immutable-trade.jsonl.gz",
            "storage": "zip_entry",
            "remote_size": 1000,
            "remote_digest": "sha256:" + "a" * 64,
        },
    }
    manifest = _normalize_manifest(raw)
    manifest["run_manifest_release_tag"] = "data-v2-collection-part0-manifest"
    row = _index_row(
        manifest, base / "datasets/safe/immutable-trade.manifest.json", base,
    )
    assert row["release_tag"] == "data-v2-collection-part0"
    assert row["run_manifest_release_tag"] == "data-v2-collection-part0-manifest"
    assert row["release_container_asset"] == "packed-shards-0000.zip"


def test_global_unique_patch_requires_same_asset_sha_and_exact_scan():
    from pathlib import Path
    from tools.index_run_manifest import _index_row
    base = Path("/tmp/alina-global-identity-contract")
    manifest = {
        "dataset_id": "reused-id", "family": "trades", "venue": "bybit",
        "sha256": "a" * 64, "trade_count": 10, "trade_count_exact": True,
        "unique_trade_count": 9, "unique_trade_count_exact": True,
    }
    dest = base / "datasets/safe/reused-id.manifest.json"
    evidence = {
        "asset_sha256": "a" * 64, "trade_count_scanned": 10,
        "unique_trade_count": 8, "unique_trade_count_exact": True,
    }
    valid = _index_row(manifest, dest, base, unique_patch_results={"reused-id": evidence})
    assert valid["unique_trade_count"] == 8
    for altered in (
        {**evidence, "asset_sha256": "b" * 64},
        {**evidence, "trade_count_scanned": 9},
        {**evidence, "unique_trade_count": 11},
        {k: v for k, v in evidence.items() if k != "asset_sha256"},
    ):
        invalid = _index_row(manifest, dest, base, unique_patch_results={"reused-id": altered})
        assert invalid["unique_trade_count"] == 9
        assert invalid["unique_trade_count_exact"] is True
