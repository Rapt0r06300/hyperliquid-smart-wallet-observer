"""V9 quant-core test suite (S4–S7 + S5) — additive modules.

Covers: market features (microstructure / volatility / OBI / quality mode),
net edge + fair value, freshness, execution gates, loss halts, adaptive
sizing, trade floor, trading circuit breaker, VaR/CVaR, calibration (Brier /
buckets / model-market / shadow), smart-money filter, wallet labels and
copy-fidelity. Plus safety (no real order possible) and no-fabrication.

All tests are pure/offline — no network, no real orders.
"""

from __future__ import annotations

import pathlib

import pytest

# ---- S4 features -----------------------------------------------------------
from hl_observer.features.microstructure import (
    compute_anchored_vwap,
    compute_basis_bps,
    compute_cvd,
    compute_impulse_bps,
    compute_microstructure,
    compute_rvol,
)
from hl_observer.features.volatility import compute_volatility_blend
from hl_observer.features.orderbook_imbalance import compute_obi, compute_obi_from_l2
from hl_observer.features.quality_mode import (
    QualityLevel,
    aggregate_quality,
    assess_stream,
    is_tradeable,
)

# ---- S6 edge / freshness / gates ------------------------------------------
from hl_observer.edge.edge_calculator import EdgeNetInputs, apply_time_decay, compute_net_edge
from hl_observer.edge.fair_value import compute_fair_value
from hl_observer.freshness.freshness_policy import (
    FreshnessAction,
    evaluate_freshness,
    should_apply_patch,
)
from hl_observer.risk.exec_gates import ExecGateConfig, ExecGateContext, evaluate_exec_gates

# ---- S7 risk ---------------------------------------------------------------
from hl_observer.risk.loss_halts import LossHaltConfig, LossHaltState, evaluate_loss_halts
from hl_observer.risk.adaptive_sizing import compute_size_pct, size_to_notional
from hl_observer.risk.trade_floor import TradeFloorConfig, evaluate_trade_floor, required_edge_bps
from hl_observer.risk.trade_circuit_breaker import (
    CircuitBreakerConfig,
    TradeCircuitBreaker,
    depth_guard,
)
from hl_observer.risk.var_cvar import (
    classify_regime,
    historical_cvar,
    historical_var,
    kelly_fraction,
)

# ---- S7 calibration --------------------------------------------------------
from hl_observer.calibration.brier import brier_score, cumulative_brier_advantage
from hl_observer.calibration.confidence_buckets import bucketize, calibration_error
from hl_observer.calibration.model_market import model_market_diff
from hl_observer.calibration.shadow_promote import ModelScore, ready_for_promotion, shadow_never_acts

# ---- S5 scoring / copy fidelity -------------------------------------------
from hl_observer.scoring.smart_money_filter import WalletStats, is_smart_money
from hl_observer.scoring.wallet_labels import assign_labels
from hl_observer.copy_fidelity.tracking_error import CopyTrade, tracking_error
from hl_observer.copy_fidelity.exec_quality import evaluate_exec_quality


# ===========================================================================
# S4 — FEATURES
# ===========================================================================
def test_microstructure_cvd_buy_sell():
    trades = [
        {"px": 1.0, "sz": 100, "side": "B"},
        {"px": 1.0, "sz": 50, "side": "A"},
    ]
    cvd, buy, sell = compute_cvd(trades)
    assert buy == pytest.approx(100.0)
    assert sell == pytest.approx(50.0)
    assert cvd == pytest.approx(50.0)


def test_cvd_none_without_sides_no_fabrication():
    trades = [{"px": 1.0, "sz": 100}, {"px": 1.0, "sz": 50}]
    cvd, buy, sell = compute_cvd(trades)
    assert cvd is None  # never guess an aggressor side


def test_rvol_anchored_vwap_impulse_basis():
    assert compute_rvol(150.0, [100, 100, 100]) == pytest.approx(1.5)
    assert compute_anchored_vwap([{"px": 10, "sz": 1}, {"px": 20, "sz": 1}]) == pytest.approx(15.0)
    assert compute_impulse_bps([100, 101], window=5) == pytest.approx(100.0)
    assert compute_basis_bps(101.0, 100.0) == pytest.approx(100.0)


def test_microstructure_empty_no_fabrication():
    feats = compute_microstructure(trades=None)
    assert feats.cvd is None
    assert feats.data_quality == "MISSING"
    assert feats.trade_count == 0


def test_volatility_blend_present_and_bucketed():
    prices = [100, 101, 100, 102, 99, 103, 98, 104, 97, 105]
    vol = compute_volatility_blend(prices, fast_window=4, slow_window=9)
    assert vol.fast_bps is not None and vol.fast_bps > 0
    assert vol.slow_bps is not None and vol.slow_bps > 0
    assert vol.blend_bps is not None
    assert vol.bucket in {"LOW", "NORMAL", "HIGH", "EXTREME"}
    assert vol.data_quality == "OK"


def test_volatility_empty_no_fabrication():
    vol = compute_volatility_blend(None)
    assert vol.blend_bps is None
    assert vol.bucket == "UNKNOWN"
    assert vol.data_quality == "MISSING"


def test_obi_long_short_neutral():
    long_bias = compute_obi([(100.0, 10.0)], [(101.0, 1.0)])
    assert long_bias.signal == "LONG_BIAS"
    assert long_bias.imbalance is not None and long_bias.imbalance > 0

    short_bias = compute_obi([(100.0, 1.0)], [(101.0, 10.0)])
    assert short_bias.signal == "SHORT_BIAS"

    neutral = compute_obi([(100.0, 5.0)], [(101.0, 5.0)])
    assert neutral.signal == "NEUTRAL"


def test_obi_missing_side_no_fabrication():
    res = compute_obi_from_l2({"levels": [[], [{"px": 101, "sz": 1}]]})
    assert res.signal == "NEUTRAL"
    assert res.imbalance is None
    assert res.data_quality == "MISSING_BOOK_SIDE"


def test_quality_mode_three_levels():
    ok = assess_stream("book", age_ms=100, degraded_after_ms=1000, bad_after_ms=5000)
    deg = assess_stream("book", age_ms=2000, degraded_after_ms=1000, bad_after_ms=5000)
    bad = assess_stream("book", age_ms=9000, degraded_after_ms=1000, bad_after_ms=5000)
    assert ok.level == QualityLevel.OK
    assert deg.level == QualityLevel.DEGRADED
    assert bad.level == QualityLevel.BAD
    assert is_tradeable(deg.level) and not is_tradeable(bad.level)


def test_quality_mode_missing_fields_and_aggregate():
    bad = assess_stream(
        "trades", age_ms=0, degraded_after_ms=1000, bad_after_ms=5000,
        missing_fields=("px", "sz", "side"),
    )
    assert bad.level == QualityLevel.BAD
    ok = assess_stream("mids", age_ms=0, degraded_after_ms=1000, bad_after_ms=5000)
    assert aggregate_quality([ok, bad]) == QualityLevel.BAD
    assert aggregate_quality([]) == QualityLevel.BAD  # deny-by-default


# ===========================================================================
# S6 — EDGE / FRESHNESS / GATES
# ===========================================================================
def test_net_edge_accept():
    inp = EdgeNetInputs(
        gross_edge_bps=100, taker_fee_bps=5, spread_cost_bps=10,
        slippage_bps=5, latency_decay_bps=5, copy_degradation_bps=5,
    )
    res = compute_net_edge(inp, min_edge_bps=30)
    assert res.decision == "ACCEPT"
    assert res.net_edge_bps == pytest.approx(70.0)
    assert res.accepted


def test_low_edge_refused():
    res = compute_net_edge(EdgeNetInputs(gross_edge_bps=35, spread_cost_bps=30), min_edge_bps=30)
    assert res.decision == "REJECT_EDGE_TOO_SMALL"
    assert not res.accepted


def test_negative_edge_refused():
    res = compute_net_edge(EdgeNetInputs(gross_edge_bps=10, spread_cost_bps=30), min_edge_bps=30)
    assert res.decision == "REJECT_EDGE_NEGATIVE"


def test_fees_not_double_counted_and_rebate_offsets():
    res = compute_net_edge(
        EdgeNetInputs(gross_edge_bps=40, taker_fee_bps=10, maker_rebate_bps=10), min_edge_bps=30
    )
    assert res.total_cost_bps == pytest.approx(0.0)
    assert res.net_edge_bps == pytest.approx(40.0)


def test_time_decay_reduces_edge():
    decayed = apply_time_decay(100.0, signal_age_ms=1000, half_life_ms=1000)
    assert decayed < 100.0
    assert decayed == pytest.approx(100.0 * 0.36787944, abs=1e-3)


def test_fair_value_spike_and_dip():
    spike = compute_fair_value([100, 100, 100, 100, 100, 100, 100, 140])
    assert spike.signal == "SPIKE_UP"
    dip = compute_fair_value([100, 100, 100, 100, 100, 100, 100, 70])
    assert dip.signal == "DIP_DOWN"


def test_fair_value_empty_no_fabrication():
    fv = compute_fair_value(None)
    assert fv.fair_value is None and fv.data_quality == "MISSING"


def test_freshness_stale_signal_refused():
    d = evaluate_freshness(1000, now_ms=10_000, max_age_ms=5000)
    assert d.action == FreshnessAction.REFUSE_STALE and not d.fresh


def test_freshness_no_timestamp_refused():
    d = evaluate_freshness(None, now_ms=10_000, max_age_ms=5000)
    assert d.action == FreshnessAction.REFUSE_NO_TIMESTAMP


def test_freshness_fresh_accepted():
    d = evaluate_freshness(8000, now_ms=10_000, max_age_ms=5000)
    assert d.action == FreshnessAction.ACCEPT and d.fresh


def test_anti_jump_patch_merge():
    assert should_apply_patch(current_revision=5, incoming_revision=6) is True
    assert should_apply_patch(current_revision=5, incoming_revision=5) is False
    assert should_apply_patch(
        current_revision=5, incoming_revision=7, incoming_age_ms=9000, max_age_ms=5000
    ) is False


def test_exec_gates_vetoes():
    cfg = ExecGateConfig()
    assert "STALE_SIGNAL" in evaluate_exec_gates(
        ExecGateContext(signal_age_ms=10_000, spread_bps=10, depth_usdc=5000), cfg
    ).vetoes
    assert "SPREAD_TOO_WIDE" in evaluate_exec_gates(
        ExecGateContext(signal_age_ms=100, spread_bps=600, depth_usdc=5000), cfg
    ).vetoes
    assert "DEPTH_TOO_LOW" in evaluate_exec_gates(
        ExecGateContext(signal_age_ms=100, spread_bps=10, depth_usdc=100), cfg
    ).vetoes
    assert "COOLDOWN_ACTIVE" in evaluate_exec_gates(
        ExecGateContext(signal_age_ms=100, spread_bps=10, depth_usdc=5000,
                        seconds_since_last_entry=10), cfg
    ).vetoes


def test_exec_gates_pass():
    res = evaluate_exec_gates(
        ExecGateContext(signal_age_ms=1000, spread_bps=50, depth_usdc=5000,
                        estimated_slippage_bps=10, seconds_since_last_entry=60)
    )
    assert res.passed and not res.vetoes


# ===========================================================================
# S7 — RISK
# ===========================================================================
def test_loss_halts_levels():
    assert evaluate_loss_halts(LossHaltState(daily_pnl_pct=-6)).triggers == ("DAILY_LOSS_HALT",)
    assert "MONTHLY_LOSS_HALT" in evaluate_loss_halts(LossHaltState(monthly_pnl_pct=-16)).triggers
    dd = evaluate_loss_halts(LossHaltState(peak_equity=100, current_equity=70))
    assert "DRAWDOWN_HALT" in dd.triggers and dd.halted
    ok = evaluate_loss_halts(LossHaltState(daily_pnl_pct=-1, monthly_pnl_pct=-2))
    assert ok.ok and not ok.halted


def test_loss_halts_trailing():
    cfg = LossHaltConfig(trailing_giveback_pct=10.0)
    d = evaluate_loss_halts(
        LossHaltState(session_peak_equity=100, current_equity=85), cfg
    )
    assert "TRAILING_GIVEBACK_HALT" in d.triggers


def test_adaptive_sizing_streak():
    loss = compute_size_pct(consecutive_losses=3)
    assert loss.size_pct == pytest.approx(2.0 * 0.8 ** 3)
    win = compute_size_pct(consecutive_wins=5)
    assert win.size_pct == pytest.approx(2.0 * 1.1 ** 5)
    capped = compute_size_pct(consecutive_wins=20)
    assert capped.size_pct == 5.0 and capped.capped
    assert compute_size_pct(confidence=0.0).size_pct == 0.0
    assert size_to_notional(2.0, 1000.0) == pytest.approx(20.0)


def test_trade_floor():
    assert evaluate_trade_floor(1.0).passes_floor is False
    assert evaluate_trade_floor(100.0).passes_floor is True
    assert required_edge_bps(100.0, TradeFloorConfig(fixed_cost_usdc=1.0)) == pytest.approx(9.0 + 100.0)


def test_trade_circuit_breaker_and_depth_guard():
    cb = TradeCircuitBreaker(CircuitBreakerConfig(max_trades=3, window_ms=60_000, big_trade_usdc=1000))
    for t in (0, 1000, 2000):
        cb.record_trade(notional_usdc=5000, now_ms=t)
    assert cb.is_tripped(2000) is True
    assert cb.is_tripped(100_000) is False  # window elapsed -> pruned
    assert depth_guard(None) is False
    assert depth_guard(100, min_depth_usdc=200) is False
    assert depth_guard(300, min_depth_usdc=200) is True


def test_var_cvar_kelly_regime():
    returns = [-0.10, -0.05, -0.02, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    assert historical_var(returns, confidence=0.9) == pytest.approx(0.05)
    assert historical_cvar(returns, confidence=0.9) == pytest.approx(0.10)
    assert historical_var([0.01]) is None  # <2 samples -> no fabrication
    assert kelly_fraction(0.6, 2.0, cap=1.0) == pytest.approx(0.4)
    assert kelly_fraction(0.4, 1.0) == 0.0
    assert classify_regime(5) == "LOW"
    assert classify_regime(100) == "EXTREME"
    assert classify_regime(None) == "UNKNOWN"


# ===========================================================================
# S7 — CALIBRATION
# ===========================================================================
def test_brier_score_and_advantage():
    assert brier_score([(1.0, 1), (0.0, 0)]) == pytest.approx(0.0)
    assert brier_score([(1.0, 0), (0.0, 1)]) == pytest.approx(1.0)
    res = cumulative_brier_advantage([0.9, 0.1], [1, 0], baseline_constant=0.5)
    assert res.brier == pytest.approx(0.01)
    assert res.advantage == pytest.approx(0.24)


def test_confidence_buckets_winrate():
    samples = [(0.95, i < 8) for i in range(10)]
    buckets = bucketize(samples, n_buckets=10)
    top = buckets[9]
    assert top.count == 10
    assert top.win_rate == pytest.approx(0.8)
    assert calibration_error(buckets) == pytest.approx(0.15)


def test_model_market_diff():
    hi = model_market_diff(0.7, 0.5, threshold=0.05)
    assert hi.edge_side == "MODEL_HIGHER" and hi.actionable
    aligned = model_market_diff(0.51, 0.5, threshold=0.05)
    assert aligned.edge_side == "ALIGNED" and not aligned.actionable


def test_shadow_promotion_and_never_acts():
    shadow = ModelScore("shadow", brier=0.10, samples=300, acting=False)
    primary = ModelScore("primary", brier=0.15, samples=1000, acting=True)
    assert ready_for_promotion(shadow, primary).ready_for_promotion is True
    assert ready_for_promotion(
        ModelScore("shadow", 0.10, 50), primary
    ).ready_for_promotion is False
    acting_shadow = ModelScore("shadow", brier=0.10, samples=300, acting=True)
    decision = ready_for_promotion(acting_shadow, primary)
    assert decision.ready_for_promotion is False
    assert decision.shadow_acts is False
    assert shadow_never_acts(shadow) is True


# ===========================================================================
# S5 — SCORING / COPY FIDELITY
# ===========================================================================
def _good_stats() -> WalletStats:
    return WalletStats(
        win_rate=0.65, total_pnl_usdc=1500, profit_factor=1.8,
        consistency=0.75, one_big_win_share=0.20,
    )


def test_smart_money_thresholds_pass_and_fail():
    assert is_smart_money(_good_stats()).is_smart_money is True
    bad = WalletStats(win_rate=0.50, total_pnl_usdc=1500, profit_factor=1.8,
                      consistency=0.75, one_big_win_share=0.20)
    res = is_smart_money(bad)
    assert res.is_smart_money is False and "WIN_RATE" in res.failures


def test_smart_money_missing_data_excluded():
    missing = WalletStats(None, None, None, None, None)
    assert is_smart_money(missing).is_smart_money is False  # deny-by-default


def test_wallet_label_requires_evidence():
    res = assign_labels(_good_stats(), evidence_count=5)
    assert res.labels == ("UNVERIFIED",) and res.verified is False


def test_wallet_labels_assigned_with_evidence():
    res = assign_labels(
        _good_stats(), evidence_count=50, largest_notional_usdc=300_000, fill_count=5
    )
    assert "SMART" in res.labels and "WHALE" in res.labels and "FRESH" in res.labels
    assert res.verified is True


def test_copy_tracking_error_long_and_short_sign():
    long_te = tracking_error([CopyTrade("long", leader_price=100, copy_price=101)])
    assert long_te.mean_gap_bps == pytest.approx(100.0)  # paid worse
    short_te = tracking_error([CopyTrade("short", leader_price=100, copy_price=99)])
    assert short_te.mean_gap_bps == pytest.approx(100.0)  # also worse for a short
    assert tracking_error([]).samples == 0


def test_exec_quality_grades():
    good = evaluate_exec_quality(realized_slippage_bps=5, expected_slippage_bps=5,
                                 filled_qty=10, intended_qty=10)
    assert good.grade == "GOOD" and good.fill_ratio == pytest.approx(1.0)
    poor = evaluate_exec_quality(realized_slippage_bps=40, expected_slippage_bps=5,
                                 filled_qty=10, intended_qty=10)
    assert poor.grade == "POOR"
    partial = evaluate_exec_quality(realized_slippage_bps=5, expected_slippage_bps=5,
                                    filled_qty=5, intended_qty=10)
    assert partial.grade == "POOR" and partial.fill_ratio == pytest.approx(0.5)


# ===========================================================================
# SAFETY — no real order possible in the new quant-core modules
# ===========================================================================
def test_safety_no_real_execution_tokens_in_new_modules():
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "hl_observer"
    targets = [
        root / "features" / "microstructure.py",
        root / "features" / "volatility.py",
        root / "features" / "orderbook_imbalance.py",
        root / "features" / "quality_mode.py",
        root / "edge" / "fair_value.py",
        root / "edge" / "edge_calculator.py",
        root / "freshness" / "freshness_policy.py",
        root / "risk" / "exec_gates.py",
        root / "risk" / "loss_halts.py",
        root / "risk" / "adaptive_sizing.py",
        root / "risk" / "trade_floor.py",
        root / "risk" / "trade_circuit_breaker.py",
        root / "risk" / "var_cvar.py",
        root / "calibration" / "brier.py",
        root / "calibration" / "confidence_buckets.py",
        root / "calibration" / "model_market.py",
        root / "calibration" / "shadow_promote.py",
        root / "scoring" / "smart_money_filter.py",
        root / "scoring" / "wallet_labels.py",
        root / "copy_fidelity" / "tracking_error.py",
        root / "copy_fidelity" / "exec_quality.py",
    ]
    forbidden = (
        "place_order", "send_order", "create_order", "submit_order",
        "signtypeddata", "eth_sendtransaction", "private_key",
        "mnemonic", "wallet.connect", "exchange.order",
    )
    for path in targets:
        assert path.exists(), f"missing module: {path}"
        text = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in text, f"forbidden execution token {token!r} in {path.name}"
