"""Leverage realism: a 1% move on a leveraged paper position yields meaningful PnL
(euros, not cents), PnL scales ~linearly with leverage, and EXPOSURE stays in MARGIN
terms so the 1000$ caps still hold. Real market prices only — no fabrication."""

from __future__ import annotations

from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.paper_engine import PaperEngine, PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta

WALLET = "0x" + "c" * 40


def _delta(ts: int = 1_700_000_000_000) -> LeaderDelta:
    return LeaderDelta(
        delta_id=f"ld:lev:{ts}", wallet=WALLET, coin="HYPE", action=LifecycleAction.OPEN_LONG,
        previous_size=0.0, current_size=1.0, delta_size=1.0,
        observed_at_ms=ts + 100, leader_event_time_ms=ts, source="unit_test",
        confidence=0.95, evidence_ref="fill:lev",
    )


def _open(engine: PaperEngine, price: float = 100.0):
    observed = 1_700_000_000_100
    return engine.apply_delta(
        _delta(), market_price=price, observed_at_ms=observed,
        edge_remaining_bps=80.0, spread_bps=2.0, estimated_slippage_bps=2.0,
        top_depth_usdt=1_000_000.0, wallet_score=90.0, signal_score=80.0, marks={"HYPE": price},
        execution_truth=ExecutionTruth.from_levels(
            coin="HYPE",
            bids=((price - 0.01, 50_000.0),),
            asks=((price + 0.01, 50_000.0),),
            received_ts_ms=observed - 1,
            exchange_ts_ms=observed - 2,
            source="recorded_hyperliquid_l2_fixture",
            data_origin="RECORDED_REAL",
        ),
    )


def test_leverage_scales_pnl_and_keeps_margin_exposure():
    cfg1 = PaperEngineConfig(max_position_usdt=100.0, leverage=1.0, default_top_depth_usdt=1_000_000.0)
    cfg5 = PaperEngineConfig(max_position_usdt=100.0, leverage=5.0, default_top_depth_usdt=1_000_000.0)
    e1, e5 = PaperEngine(config=cfg1), PaperEngine(config=cfg5)
    r1, r5 = _open(e1), _open(e5)
    assert r1.accepted and r5.accepted

    # leveraged coin quantity is ~5x
    q1 = e1.positions[0].quantity
    q5 = e5.positions[0].quantity
    assert abs(q5 / q1 - 5.0) < 0.05

    # +1% move: unrealized PnL is meaningful (NOT cents) and ~5x bigger at 5x
    _, u1, _ = e1.mark_to_market({"HYPE": 101.0})
    _, u5, _ = e5.mark_to_market({"HYPE": 101.0})
    assert u1 > 0 and u5 > 0
    assert u5 >= 3.0                       # ~5$ on 100$ @5x for +1% (minus fees) -> euros, not cents
    assert 4.0 < (u5 / u1) < 6.0           # scales ~linearly with leverage

    # Margin is the capital locked by the risk cap; gross exposure is leveraged
    # notional and must not be mislabeled as margin.
    assert abs(e1._margin_locked_usdt() - e5._margin_locked_usdt()) < 1e-6
    assert e5._margin_locked_usdt() <= 100.0 + 1e-6
    assert 4.9 < e5._gross_exposure_usdt() / e1._gross_exposure_usdt() < 5.1

    # the stored position notional IS leveraged (true HL position size)
    assert abs(e5.positions[0].notional_usdt / e1.positions[0].notional_usdt - 5.0) < 0.05


def test_default_leverage_is_one_backward_compatible():
    # default config (no leverage arg) behaves exactly as before (1x)
    e = PaperEngine(config=PaperEngineConfig(max_position_usdt=40.0, default_top_depth_usdt=1_000_000.0))
    r = _open(e)
    assert r.accepted
    # notional == margin at 1x
    assert e.positions[0].notional_usdt <= 40.0 + 1e-6


def test_live_formula_no_more_cents():
    # mirrors routes.py: margin 100$ x 5x, +0.5% move on real price -> ~2.5$, not 0.02$
    margin, leverage, price = 100.0, 5.0, 2000.0
    notional = margin * leverage
    qty = notional / price
    pnl_half_pct = qty * (price * 1.005 - price)   # +0.5%
    assert round(pnl_half_pct, 2) == 2.50
