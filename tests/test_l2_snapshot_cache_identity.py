from __future__ import annotations

from hl_observer.collection import l2_snapshot_cache


def test_execution_book_cache_preserves_case_sensitive_native_symbols() -> None:
    cache = l2_snapshot_cache._book_cache
    cache.clear()
    try:
        lower = l2_snapshot_cache.push_book(
            "kPEPE",
            [(0.00001, 10_000_000.0)],
            [(0.00002, 10_000_000.0)],
            received_ts_ms=1_800_000_000_001,
            exchange_ts_ms=1_800_000_000_000,
        )
        upper = l2_snapshot_cache.push_book(
            "KPEPE",
            [(0.00003, 10_000_000.0)],
            [(0.00004, 10_000_000.0)],
            received_ts_ms=1_800_000_000_001,
            exchange_ts_ms=1_800_000_000_000,
        )

        assert lower.coin == "kPEPE"
        assert upper.coin == "KPEPE"
        assert l2_snapshot_cache.live_execution_truth_for(
            "kPEPE",
            decision_ts_ms=1_800_000_000_002,
            require_consume_flag=False,
        ) is lower
        assert l2_snapshot_cache.live_execution_truth_for(
            "KPEPE",
            decision_ts_ms=1_800_000_000_002,
            require_consume_flag=False,
        ) is upper
        assert l2_snapshot_cache.live_execution_truth_for(
            "Kpepe",
            decision_ts_ms=1_800_000_000_002,
            require_consume_flag=False,
        ) is None
    finally:
        cache.clear()
