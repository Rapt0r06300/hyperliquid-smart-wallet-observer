from __future__ import annotations

from hl_observer.collection.window_quality import PARTIAL, REJECT, SAFE, qualify_window


def test_clean_reconciled_window_is_safe() -> None:
    report = qualify_window(
        [
            {"exchange_ts_ms": 1_000, "receive_ts_ms": 1_010, "quality": "EXPLOITABLE"},
            {"exchange_ts_ms": 1_020, "receive_ts_ms": 1_030, "quality": "EXPLOITABLE"},
        ],
        reconciliation_status="MATCHED",
        allowed_receive_gap_ms=100,
    )
    assert report.status == SAFE
    assert report.validation_allowed


def test_missing_evidence_is_partial_and_gap_is_reject() -> None:
    partial = qualify_window(
        [{"receive_ts_ms": 1_010, "quality": "EXPLOITABLE"}],
        reconciliation_status="MATCHED",
    )
    assert partial.status == PARTIAL

    rejected = qualify_window(
        [
            {
                "exchange_ts_ms": 1_000,
                "receive_ts_ms": 1_010,
                "quality": "DESYNC",
                "gap_count": 1,
            }
        ],
        reconciliation_status="MISMATCH",
    )
    assert rejected.status == REJECT
