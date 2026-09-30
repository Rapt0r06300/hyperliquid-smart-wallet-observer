import pytest

from hl_observer.backtest.experiment_runner import run_experiment
from hl_observer.backtest.multi_wallet_replay import replay_multi_wallet
from hl_observer.backtest.optimize import optimize, random_grid_search
from hl_observer.backtest.report_charts import build_report, max_drawdown, sharpe
from hl_observer.backtest.runner_contract import validate_runner_inputs
from hl_observer.storage.run_context import RunContext


def test_runner_contract_rejects_live_and_lookahead():
    ev_ok = [{"decision_ts_ms": 1000, "data_ts_ms": 900}]
    assert validate_runner_inputs(RunContext.BACKTEST, ev_ok) == []
    assert "RUN_CONTEXT_MUST_NOT_BE_LIVE_FOR_BACKTEST" in validate_runner_inputs(RunContext.LIVE, ev_ok)
    leak = [{"decision_ts_ms": 1000, "data_ts_ms": 1500}]
    assert any("LOOKAHEAD" in v for v in validate_runner_inputs(RunContext.BACKTEST, leak))
    assert "NO_EVENTS" in validate_runner_inputs(RunContext.REPLAY, [])


def test_experiment_runs_in_order_no_lookahead():
    events = [{"decision_ts_ms": 3, "data_ts_ms": 2, "v": 3},
              {"decision_ts_ms": 1, "data_ts_ms": 0, "v": 1}]
    seen_pasts = []
    def decide(ev, past):
        seen_pasts.append(len(past))
        return {"accepted": ev["v"] == 1}
    res = run_experiment("exp", RunContext.BACKTEST, events, decide)
    assert res.total_events == 2 and res.accepted == 1
    assert seen_pasts == [0, 1]          # first sees 0 past, second sees 1


def test_experiment_raises_on_bad_inputs():
    with pytest.raises(ValueError):
        run_experiment("x", RunContext.LIVE, [{"decision_ts_ms": 1, "data_ts_ms": 0}], lambda e, p: {})


def test_multi_wallet_merge_time_order():
    merged = replay_multi_wallet({"A": [{"ts_ms": 3}], "B": [{"ts_ms": 1}, {"ts_ms": 2}]})
    assert [m["ts_ms"] for m in merged] == [1, 2, 3]
    assert merged[0]["wallet"] == "B" and merged[-1]["wallet"] == "A"


def test_optimize_deterministic_and_picks_best():
    space = {"x": [1, 2, 3, 4, 5]}
    best = optimize(space, lambda p: -abs(p["x"] - 4), n_trials=20, seed=7)
    best2 = optimize(space, lambda p: -abs(p["x"] - 4), n_trials=20, seed=7)
    assert best.params == best2.params           # deterministic with seed
    assert best.params["x"] == 4                  # maximizes objective


def test_report_charts_math():
    rep = build_report([10.0, -4.0, 6.0], start_equity=1000.0)
    assert rep["equity"] == [1000.0, 1010.0, 1006.0, 1012.0]
    assert rep["total_pnl"] == 12.0 and rep["final_equity"] == 1012.0
    assert max_drawdown([1000, 1010, 1006, 1012]) == -4.0
    assert build_report([])["empty"] is True
