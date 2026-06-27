from hl_observer.copy_fidelity.exec_cost_model import (
    model_exec_costs, net_edge_after_costs, queue_fill_probability,
)
from hl_observer.scoring.smart_money_gate import smart_money_gate, min_depth_ok, window_caps_ok
from hl_observer.signals.depth_guard import depth_guard
from hl_observer.signals.obi_signal import obi_signal, order_book_imbalance
from hl_observer.features.eat_flow import eat_flow_ratio, levels_eaten
from hl_observer.features.basis import basis_bps, oracle_lag_ms
from hl_observer.features.accumulate import AccumulateState, apply_slice, can_add_slice
from hl_observer.features.vol_sigma import sigma_fast_slow_blend
from hl_observer.optimization.threshold_optimizer import evaluate_thresholds, optimize_thresholds


# ---- #150 exec costs ----
def test_maker_rebate_reduces_cost_and_net_edge():
    taker = model_exec_costs(fee_bps=4.5, half_spread_bps=2.0, slippage_bps=1.0)
    maker = model_exec_costs(fee_bps=1.0, half_spread_bps=2.0, is_maker=True, maker_rebate_bps=0.5)
    assert maker.total_cost_bps < taker.total_cost_bps
    assert net_edge_after_costs(gross_edge_bps=20, costs=taker) == round(20 - taker.total_cost_bps, 4)


def test_queue_fill_probability_bounds():
    assert queue_fill_probability(0, 100) == 1.0
    assert queue_fill_probability(100, 100) == 0.0
    assert 0.0 < queue_fill_probability(40, 100) < 1.0


# ---- #152 smart money ----
def test_smart_money_gate_thresholds():
    ok = smart_money_gate(win_rate=0.65, total_pnl_usdc=800, profit_factor=1.8,
                          consistency=0.75, one_big_win_share=0.2)
    assert ok.accepted and ok.reasons == ()
    bad = smart_money_gate(win_rate=0.5, total_pnl_usdc=100, profit_factor=1.1,
                           consistency=0.5, one_big_win_share=0.6)
    assert not bad.accepted and "WIN_RATE_TOO_LOW" in bad.reasons and "ONE_BIG_WIN_RISK" in bad.reasons


def test_depth_and_window_caps():
    assert min_depth_ok(250) and not min_depth_ok(150)
    ok, _ = window_caps_ok(trades_in_window=5, usd_in_window=50)
    assert ok
    blocked, code = window_caps_ok(trades_in_window=30, usd_in_window=50)
    assert not blocked and code == "MAX_SLICES_PER_WINDOW"


# ---- #155 depth guard + OBI ----
def test_depth_guard_blocks_thin_book():
    ok, _ = depth_guard(bid_depth_usd=1000, ask_depth_usd=1000, side="LONG", needed_usd=100)
    assert ok
    thin, code = depth_guard(bid_depth_usd=100, ask_depth_usd=100, side="LONG", needed_usd=100)
    assert not thin and code in {"DEPTH_TOO_LOW", "SIZE_EXCEEDS_DEPTH"}


def test_obi_signal_direction():
    assert obi_signal(order_book_imbalance([10, 5], [1, 1])) == "LONG"
    assert obi_signal(order_book_imbalance([1, 1], [10, 5])) == "SHORT"
    assert obi_signal(order_book_imbalance([5], [5])) == "FLAT"


# ---- #154 features ----
def test_eat_flow_and_levels():
    assert eat_flow_ratio(300, 100) == 3.0
    assert levels_eaten(250, [100, 100, 100]) == 2


def test_basis_and_lag():
    assert basis_bps(101.0, 100.0) == 100.0
    assert oracle_lag_ms(5000, 4000) == 1000 and oracle_lag_ms(4000, 5000) == 0


def test_accumulate_caps():
    st = AccumulateState()
    ok, _ = can_add_slice(st, now_ms=10000, slice_usd=20)
    assert ok
    st = apply_slice(st, now_ms=10000, slice_usd=20)
    blocked, code = can_add_slice(st, now_ms=10500, slice_usd=20)   # within cooldown
    assert not blocked and code == "COOLDOWN"


def test_sigma_blend():
    r = [0.01, -0.02, 0.015, -0.01, 0.02] * 5
    s = sigma_fast_slow_blend(r, fast_n=5, slow_n=20)
    assert s["sigma_fast"] >= 0 and s["sigma_slow"] >= 0 and s["sigma_blend"] >= 0


# ---- #151 threshold optimizer ----
def _mk_samples():
    out = []
    for i in range(120):
        edge = 5 + (i % 40)
        # higher edge => more likely profitable
        pnl = 3.0 if edge >= 20 else -2.0
        out.append({"ts_ms": 1000 + i, "features": {"net_edge_bps": edge, "liquidity_score": 0.5,
                    "signal_age_ms": 5000}, "label": 1 if pnl > 0 else 0, "net_pnl_usdc": pnl})
    return out


def test_optimizer_prefers_higher_edge_and_reports_oos():
    res = optimize_thresholds(_mk_samples(), min_taken=5)
    assert res["ok"] is True
    assert res["best_config"]["min_edge_bps"] >= 20      # learns that high edge is profitable
    assert "oos_consistent" in res and "test" in res


def test_optimizer_refuses_tiny_dataset():
    assert optimize_thresholds([{"ts_ms": 1, "features": {}, "net_pnl_usdc": 1}])["ok"] is False
