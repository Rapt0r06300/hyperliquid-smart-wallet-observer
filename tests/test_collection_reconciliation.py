from __future__ import annotations

from hl_observer.collection.reconciliation import reconcile_records


def test_reconciliation_matches_same_event_ids() -> None:
    report = reconcile_records(
        [{"event_id": "a"}, {"event_id": "b"}],
        [{"event_id": "a"}, {"event_id": "b"}],
    )
    assert report.status == "MATCHED"
    assert report.matched_count == 2


def test_reconciliation_exposes_missing_records() -> None:
    report = reconcile_records(
        [{"event_id": "a"}],
        [{"event_id": "a"}, {"event_id": "b"}],
    )
    assert report.status == "PARTIAL"
    assert report.missing_from_live == 1
