"""B1-B7 + C1-C6 : machinerie de réglage & sélectivité (pur / paper / read-only)."""

import hl_observer.strategies.fusion_runtime  # noqa: F401 - init strategies avant copy_mode (circular pre-existant)

from hl_observer.backtest.selectivity_report import selectivity_report
from hl_observer.copy_mode.reentry_cooldown import ReentryCooldown
from hl_observer.optimization.anti_overfit_guard import accept_config, is_overfit
from hl_observer.optimization.best_config_selector import select_best
from hl_observer.optimization.out_of_sample_guard import oos_consistent, oos_split
from hl_observer.optimization.pnl_sweep import best_by_profit_factor, sweep
from hl_observer.optimization.threshold_optimizer import evaluate_thresholds
from hl_observer.risk.scale_out import close_grid_fraction, trailing_close_triggered
from hl_observer.signals.gate_profile import apply_strict_profile


# B1 — profit factor dans l'optimiseur
def test_threshold_optimizer_reports_profit_factor():
    samples = [
        {"features": {"net_edge_bps": 40, "liquidity_score": 0.9, "signal_age_ms": 1000}, "net_pnl_usdc": 2.0},
        {"features": {"net_edge_bps": 40, "liquidity_score": 0.9, "signal_age_ms": 1000}, "net_pnl_usdc": -1.0},
    ]
    r = evaluate_thresholds(samples, min_edge_bps=30, min_liquidity=0.5, max_age_ms=8000)
    assert r["n_taken"] == 2 and r["profit_factor"] == 2.0


# B4 — OOS + anti-overfit
def test_oos_and_overfit_guards():
    tr, te = oos_split([{"ts_ms": i} for i in range(10)], test_frac=0.3)
    assert len(tr) == 7 and len(te) == 3
    assert oos_consistent(1.5, 1.2, 12) is True
    assert oos_consistent(1.5, 0.8, 12) is False
    assert is_overfit(2.0, 0.5) is True          # test s'effondre vs train
    assert accept_config(1.5, 1.3) is True
    assert accept_config(1.5, 0.6) is False


# B7 — sélecteur best config
def test_best_config_selector():
    results = [
        {"config": {"a": 1}, "train_pf": 1.4, "test_pf": 1.3, "test_pnl": 5},
        {"config": {"a": 2}, "train_pf": 3.0, "test_pf": 0.4, "test_pnl": 9},   # overfit -> rejeté
        {"config": {"a": 3}, "train_pf": 1.6, "test_pf": 1.5, "test_pnl": 4},
    ]
    best = select_best(results)
    assert best is not None and best["config"] == {"a": 3}


# B5 — scale-out grille + trailing close
def test_scale_out_grid_and_trailing_close():
    assert close_grid_fraction(10.0) == 0.0
    assert close_grid_fraction(20.0) == 0.34
    assert close_grid_fraction(60.0) == 0.634
    assert trailing_close_triggered(400.0, 40.0, threshold_bps=349.0) is True
    assert trailing_close_triggered(400.0, 100.0, threshold_bps=349.0) is False


# B6 — re-entry cooldown
def test_reentry_cooldown():
    cd = ReentryCooldown(cooldown_seconds=1800.0)
    cd.record_exit("ETH", 1_000_000)
    assert cd.can_reenter("ETH", 1_000_000 + 1_000_000) is False   # +1000s < 1800s
    assert cd.can_reenter("ETH", 1_000_000 + 2_000_000) is True    # +2000s >= 1800s
    assert cd.can_reenter("SOL", 1_000_000) is True                # jamais sorti


# C1-C5 — profil de gate strict
def test_gate_profile_off_is_noop():
    ctx = {"min_edge_bps": 3.0}
    assert apply_strict_profile(ctx, env={}) == ctx


def test_gate_profile_on_hardens_context():
    env = {"HYPERSMART_GATE_STRICT_PROFILE": "1"}
    c = apply_strict_profile({"min_consensus": 1, "strategy_kind": "trend"}, sigma_bps=90.0, env=env)
    assert c["require_obi"] is True
    assert c["min_consensus"] >= 2
    assert c["min_edge_bps"] >= 30.0
    assert c["conflict"] is True    # extreme -> coupe le directionnel (trend)


# C6 — rapport de sélectivité
def test_selectivity_report():
    baseline = [3.0, -3.0, 2.0, -2.0, 1.0, -1.0]     # 6 trades, PF=1.0
    variant = [4.0, -1.0, 3.0]                        # 3 trades, PF=7.0
    r = selectivity_report(baseline, variant)
    assert r["more_selective"] is True and r["better_profit_factor"] is True
    assert r["verdict"] == "SELECTIVITY_HELPS"


# B2/B3 — sweep générique branché au juge
def test_pnl_sweep_picks_best_profit_factor():
    def scorer(cfg):
        return [cfg["x"], -1.0]        # PF croit avec x
    res = sweep({"x": [1.0, 5.0, 10.0]}, scorer)
    assert best_by_profit_factor(res)["config"] == {"x": 10.0}
