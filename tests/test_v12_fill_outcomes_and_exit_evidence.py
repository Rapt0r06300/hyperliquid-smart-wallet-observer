import json

from hl_observer.evidence.exit_evidence import ExitKind, exit_evidence_row
from hl_observer.paper_trading.fill_outcomes import (
    FillOutcome,
    funding_cost_bps,
    resolve_fill,
)


def test_taker_fills_fully():
    r = resolve_fill(notional_usdc=100.0, is_maker=False)
    assert r.outcome == FillOutcome.FILLED and r.fill_fraction == 1.0 and r.filled_notional_usdc == 100.0


def test_maker_front_of_queue_fills():
    r = resolve_fill(notional_usdc=100.0, is_maker=True, queue_ratio=0.3)
    assert r.outcome == FillOutcome.FILLED


def test_maker_mid_queue_partial():
    r = resolve_fill(notional_usdc=100.0, is_maker=True, queue_ratio=0.75)
    assert r.outcome == FillOutcome.PARTIAL
    assert abs(r.fill_fraction - 0.25) < 1e-9 and abs(r.filled_notional_usdc - 25.0) < 1e-6


def test_maker_back_of_queue_missed():
    r = resolve_fill(notional_usdc=100.0, is_maker=True, queue_ratio=1.4)
    assert r.outcome == FillOutcome.MISSED and r.fill_fraction == 0.0


def test_maker_unknown_queue_is_missed_deny_by_default():
    r = resolve_fill(notional_usdc=100.0, is_maker=True, queue_ratio=None)
    assert r.outcome == FillOutcome.MISSED


def test_funding_cost_math():
    assert funding_cost_bps(1.0, 3_600_000) == 1.0     # 1 bps/h for 1h
    assert funding_cost_bps(2.0, 1_800_000) == 1.0     # 2 bps/h for 0.5h
    assert funding_cost_bps(1.0, 0) == 0.0


def test_exit_evidence_take_profit_and_liquidation():
    tp = exit_evidence_row(ExitKind.TAKE_PROFIT, coin="btc", side="long",
                           realized_net_pnl_usdc=1.2345678, exit_price=60100.0, now_ms=10)
    assert tp["exit_kind"] == "TAKE_PROFIT" and tp["coin"] == "BTC" and tp["side"] == "LONG"
    assert tp["realized_net_pnl_usdc"] == 1.234568
    liq = exit_evidence_row("liquidation", coin="ETH", side="SHORT", realized_net_pnl_usdc=-5.0)
    assert liq["exit_kind"] == "LIQUIDATION" and liq["realized_net_pnl_usdc"] == -5.0
    json.dumps(tp); json.dumps(liq)
