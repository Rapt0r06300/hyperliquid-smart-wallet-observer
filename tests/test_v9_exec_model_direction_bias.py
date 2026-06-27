import pytest

from hl_observer.paper_trading.exec_model import (
    ExecModelConfig,
    estimate_slippage_bps,
    round_trip_cost_bps,
    simulate_execution,
)
from hl_observer.features.direction import (
    DOWN,
    FLAT,
    UP,
    DirectionConfig,
    aligns_with,
    multi_tf_direction,
    timeframe_direction,
)
from hl_observer.edge.bias_model import bias_from_closes, directional_bias_bps


# ---------------- exec_model ----------------

def test_taker_costs_fee_plus_slippage():
    cfg = ExecModelConfig(taker_fee_bps=4.5, half_spread_bps=1.0, impact_coef_bps=10.0)
    r = simulate_execution(side="LONG", notional_usdc=50, mid_price=100.0,
                           top_depth_usdc=50_000, is_maker=False, config=cfg)
    assert not r.is_maker
    # slippage = half_spread + impact*(50/50000) ~ 1.01 bps ; fee 4.5
    assert r.slippage_bps == pytest.approx(1.0 + 10.0 * (50 / 50000), abs=1e-6)
    assert r.fee_bps == 4.5
    assert r.net_cost_bps == pytest.approx(r.slippage_bps + 4.5, abs=1e-6)
    assert r.fill_price > 100.0  # buy fills above mid


def test_taker_sell_fills_below_mid():
    r = simulate_execution(side="SHORT", notional_usdc=50, mid_price=100.0, top_depth_usdc=50_000)
    assert r.fill_price < 100.0


def test_maker_earns_rebate_negative_fee():
    cfg = ExecModelConfig(maker_rebate_bps=1.0)
    r = simulate_execution(side="LONG", notional_usdc=50, mid_price=100.0,
                           top_depth_usdc=50_000, is_maker=True, queue_ahead_usdc=5000, config=cfg)
    assert r.is_maker
    assert r.fee_bps == -1.0
    assert r.slippage_bps == 0.0
    assert r.queue_ratio == pytest.approx(5000 / 50000)


def test_unknown_depth_is_conservative():
    cfg = ExecModelConfig(unknown_depth_impact_bps=25.0, half_spread_bps=1.0)
    s = estimate_slippage_bps(50, None, config=cfg)
    assert s == pytest.approx(26.0)


def test_slippage_grows_with_size():
    small = estimate_slippage_bps(50, 50_000)
    big = estimate_slippage_bps(5_000, 50_000)
    assert big > small


def test_round_trip_cost_adds_entry_and_exit():
    e = simulate_execution(side="LONG", notional_usdc=50, mid_price=100.0, top_depth_usdc=50_000)
    x = simulate_execution(side="SHORT", notional_usdc=50, mid_price=101.0, top_depth_usdc=50_000)
    assert round_trip_cost_bps(entry=e, exit_=x) == pytest.approx(e.net_cost_bps + x.net_cost_bps)


# ---------------- direction ----------------

def test_uptrend_detected():
    closes = [float(i) for i in range(1, 60)]  # strictly rising
    assert timeframe_direction(closes) == UP


def test_downtrend_detected():
    closes = [float(i) for i in range(60, 1, -1)]
    assert timeframe_direction(closes) == DOWN


def test_flat_on_short_data():
    assert timeframe_direction([1.0, 2.0]) == FLAT


def test_multi_tf_agreement():
    up = [float(i) for i in range(1, 60)]
    mtf = multi_tf_direction(up, up)
    assert mtf.agree and mtf.combined == UP


def test_multi_tf_conflict_is_flat():
    up = [float(i) for i in range(1, 60)]
    down = [float(i) for i in range(60, 1, -1)]
    mtf = multi_tf_direction(up, down)
    assert mtf.combined == FLAT and not mtf.agree


def test_aligns_with():
    assert aligns_with("LONG", UP)
    assert not aligns_with("LONG", DOWN)
    assert aligns_with("SHORT", DOWN)
    assert aligns_with("LONG", FLAT)  # neutral


# ---------------- bias_model ----------------

def test_bias_positive_when_aligned():
    up = [float(i) for i in range(1, 60)]
    r = bias_from_closes(direction_side="LONG", closes_fast_tf=up, closes_slow_tf=up)
    assert r.aligned and r.bias_bps > 0


def test_bias_negative_when_fighting_trend():
    up = [float(i) for i in range(1, 60)]
    r = bias_from_closes(direction_side="SHORT", closes_fast_tf=up, closes_slow_tf=up)
    assert not r.aligned and r.bias_bps < 0


def test_bias_zero_when_flat():
    flat = [100.0] * 60
    r = bias_from_closes(direction_side="LONG", closes_fast_tf=flat, closes_slow_tf=flat)
    assert r.bias_bps == 0.0


def test_bias_is_bounded():
    up = [float(i) * 10 for i in range(1, 60)]  # very steep
    r = bias_from_closes(direction_side="LONG", closes_fast_tf=up, closes_slow_tf=up)
    assert -8.0 <= r.bias_bps <= 8.0
