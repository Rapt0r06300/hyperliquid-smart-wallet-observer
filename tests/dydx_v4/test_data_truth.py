from __future__ import annotations

from hyper_smart_observer.dydx_v4.data_truth import (
    classify_entry_source,
    classify_signal_origin,
    summarize_position_truth,
)


def test_classify_entry_source_real_and_non_real() -> None:
    assert classify_entry_source("orderbook_real").real_data is True
    assert classify_entry_source("REAL_INDEXER").real_data is True
    assert classify_entry_source("DEMO_SYNTHETIC").real_data is False
    assert classify_entry_source("FALLBACK_ESTIMATED").real_data is False
    assert classify_entry_source("unknown").real_data is False


def test_classify_signal_origin_real_and_non_real() -> None:
    assert classify_signal_origin("stream").real_data is True
    assert classify_signal_origin("flow").real_data is True
    assert classify_signal_origin("demo").real_data is False
    assert classify_signal_origin("synthetic").real_data is False


def test_summarize_position_truth_flags_non_real_entries() -> None:
    status = {
        "positions": [
            {"data_source": "orderbook_real"},
            {"data_source": "DEMO_SYNTHETIC"},
        ]
    }

    summary = summarize_position_truth(status)

    assert summary["positions_checked"] == 2
    assert summary["all_real_data"] is False
    assert summary["read_only"] is True
    assert summary["paper_only"] is True
