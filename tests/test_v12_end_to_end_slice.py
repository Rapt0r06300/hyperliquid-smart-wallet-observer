"""End-to-end vertical slice (V12): raw fills -> lifecycle -> decision -> funnel.
Proves the chain is wired and consistent on realistic fixtures. Pure, no network."""

from hl_observer.signals.copy_decision import CopyInputs, evaluate_copy_candidate
from hl_observer.signals.decision_funnel import build_decision_funnel
from hl_observer.signals.source_reconcile import reconcile_quotes
from hl_observer.wallets.position_delta_engine import (
    PositionAction,
    build_position_delta_from_fill,
)


def test_raw_fill_to_lifecycle():
    open_fill = {"coin": "BTC", "px": "60000", "sz": "0.1", "side": "b", "time": 1}
    rec = build_position_delta_from_fill("0xlead", open_fill, previous_size=0.0)
    assert rec.action == PositionAction.OPEN and rec.coin == "BTC"
    close_fill = {"coin": "BTC", "px": "60500", "sz": "0.1", "side": "a", "time": 2}
    rec2 = build_position_delta_from_fill("0xlead", close_fill, previous_size=0.1)
    assert rec2.action == PositionAction.CLOSE


def test_lifecycle_to_decision_to_funnel():
    fresh = build_position_delta_from_fill(
        "0xlead", {"coin": "BTC", "px": "60000", "sz": "0.1", "side": "b", "time": 1}, previous_size=0.0
    )
    decisions = [
        evaluate_copy_candidate(CopyInputs(
            lifecycle_action=fresh.action.value, has_known_position=False,
            signal_age_ms=2000, max_signal_age_ms=45000,
            liquidity_score=0.9, min_liquidity_score=0.2,
            net_edge_bps=25.0, min_edge_bps=10.0)),                       # accept
        evaluate_copy_candidate(CopyInputs(signal_age_ms=99999, max_signal_age_ms=45000)),  # SIGNAL_TOO_OLD
        evaluate_copy_candidate(CopyInputs(signal_age_ms=1000, net_edge_bps=1.0, min_edge_bps=10.0)),  # edge
    ]
    assert decisions[0].accepted is True
    funnel = build_decision_funnel(decisions)
    assert funnel["total"] == 3 and funnel["accepted"] == 1 and funnel["blocked"] == 2
    codes = {r["reason_code"] for r in funnel["blocking_reasons"]}
    assert "SIGNAL_TOO_OLD" in codes and "EDGE_REMAINING_TOO_LOW" in codes


def test_quote_conflict_blocks_decision():
    # REST vs WS mids diverge -> SOURCE_CONFLICT -> decision refuses
    recon = reconcile_quotes({"BTC": "60000"}, {"BTC": "60500"}, max_dev_bps=5.0)
    assert recon.agree is False and recon.reason_code == "SOURCE_CONFLICT"
    d = evaluate_copy_candidate(CopyInputs(quotes_agree=recon.agree, signal_age_ms=1000,
                                           net_edge_bps=25.0, min_edge_bps=10.0))
    assert d.accepted is False and d.reason_code == "SOURCE_CONFLICT"
