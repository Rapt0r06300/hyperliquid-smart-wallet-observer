from hl_observer.signals.copy_decision import CopyInputs, evaluate_copy_candidate
from hl_observer.signals.decision_funnel import build_decision_funnel


def _ok(**over):
    base = dict(source_usable=True, quotes_agree=True, mid_available=True,
               signal_age_ms=1000, max_signal_age_ms=30000,
               liquidity_score=0.9, min_liquidity_score=0.2,
               spread_bps=2.0, max_spread_bps=20.0,
               net_edge_bps=25.0, min_edge_bps=10.0)
    base.update(over)
    return evaluate_copy_candidate(CopyInputs(**base))


def test_empty_is_honest():
    f = build_decision_funnel([])
    assert f["empty"] is True and f["total"] == 0 and f["acceptance_rate"] == 0.0
    assert f["blocking_reasons"] == []


def test_mixed_funnel_counts_and_rate():
    decisions = [
        _ok(),                                   # accept
        _ok(),                                   # accept
        _ok(signal_age_ms=99999),                # SIGNAL_TOO_OLD
        _ok(net_edge_bps=1.0),                   # EDGE_REMAINING_TOO_LOW
        _ok(signal_age_ms=99999),                # SIGNAL_TOO_OLD (again)
    ]
    f = build_decision_funnel(decisions)
    assert f["total"] == 5 and f["accepted"] == 2 and f["blocked"] == 3
    assert f["acceptance_rate"] == 0.4
    codes = {r["reason_code"]: r["count"] for r in f["blocking_reasons"]}
    assert codes["SIGNAL_TOO_OLD"] == 2 and codes["EDGE_REMAINING_TOO_LOW"] == 1


def test_all_accepted_has_no_blocking_reasons():
    f = build_decision_funnel([_ok(), _ok()])
    assert f["accepted"] == 2 and f["blocked"] == 0 and f["blocking_reasons"] == []


def test_categories_present():
    f = build_decision_funnel([_ok(signal_age_ms=99999), _ok(spread_bps=99.0)])
    assert "SIGNAL" in f["by_category"] and "MARKET" in f["by_category"]
