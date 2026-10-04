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
