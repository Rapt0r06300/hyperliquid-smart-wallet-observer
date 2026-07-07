from hl_observer.signals.copy_decision import (
    CopyInputs,
    evaluate_copy_candidate,
)


def _ok(**over):
    base = dict(source_usable=True, quotes_agree=True, mid_available=True,
               signal_age_ms=1000, max_signal_age_ms=30000,
               liquidity_score=0.9, min_liquidity_score=0.2,
               spread_bps=2.0, max_spread_bps=20.0,
               net_edge_bps=25.0, min_edge_bps=10.0)
    base.update(over)
    return CopyInputs(**base)


def test_all_pass_accepts():
    d = evaluate_copy_candidate(_ok())
    assert d.accepted is True and d.reason is None
    assert "edge" in d.checks_passed


def test_source_unusable_blocks_first():
    d = evaluate_copy_candidate(_ok(source_usable=False))
    assert not d.accepted and d.reason_code == "INSUFFICIENT_DATA"


def test_lifecycle_unknown_blocks():
    d = evaluate_copy_candidate(_ok(lifecycle_action="UNKNOWN"))
    assert d.reason_code == "LIFECYCLE_UNKNOWN"


def test_quote_conflict_blocks():
    d = evaluate_copy_candidate(_ok(quotes_agree=False))
    assert d.reason_code == "SOURCE_CONFLICT"


def test_stale_signal_blocks():
    d = evaluate_copy_candidate(_ok(signal_age_ms=99999, max_signal_age_ms=30000))
    assert d.reason_code == "SIGNAL_TOO_OLD"


def test_liquidity_and_spread_and_edge():
    assert evaluate_copy_candidate(_ok(liquidity_score=0.1)).reason_code == "LIQUIDITY_TOO_LOW"
    assert evaluate_copy_candidate(_ok(spread_bps=99.0)).reason_code == "SPREAD_TOO_WIDE"
    assert evaluate_copy_candidate(_ok(net_edge_bps=1.0)).reason_code == "EDGE_REMAINING_TOO_LOW"
    assert evaluate_copy_candidate(_ok(net_edge_bps=None)).reason_code == "EDGE_UNMEASURABLE"


def test_deny_by_default_first_failing_gate_wins():
    # stale AND thin edge -> stale reported first (earlier gate)
    d = evaluate_copy_candidate(_ok(signal_age_ms=99999, net_edge_bps=1.0))
    assert d.reason_code == "SIGNAL_TOO_OLD"


def test_reason_carries_seven_attributes():
    d = evaluate_copy_candidate(_ok(net_edge_bps=1.0))
    assert set(d.reason.to_dict()) == {
        "reason_code", "severity", "is_retriable",
        "missing_data", "next_action", "evidence_refs", "dashboard_message",
    }


def test_missing_age_is_insufficient_data():
    d = evaluate_copy_candidate(_ok(signal_age_ms=None))
    assert d.reason_code == "INSUFFICIENT_DATA"
