from __future__ import annotations

from hl_observer.backtesting.anti_overfit_gate import (
    MOTIF_TROP_PEU_DE_TRADES,
    evaluer,
)
from hl_observer.backtesting.copy_vault_causal_selection import cluster_metaorders
from hl_observer.backtesting.copy_vault_experiment_controls import (
    delayed_data_falsification_receipt,
    neutral_benchmark_receipt,
)
from hl_observer.backtesting.copy_vault_generalization import (
    derive_heldout_vault_generalization,
)
from hl_observer.backtesting.copy_vault_scientific_controls import (
    extreme_trade_robustness_receipt,
)
from hl_observer.backtesting.train_statistics import (
    UTC_DAY_MS,
    summarize_complete_utc_days,
)
from hl_observer.simulation.scoreboard_metrics import assembler_ligne
from hl_observer.backtesting.copy_vault_scientific_controls import independent_episode_receipt


def _trade(vault: str, ts_ms: int, suffix: str, net: float) -> dict[str, object]:
    return {
        "vault": vault,
        "signal_ts_ms": ts_ms,
        "net_pnl_usd": net,
        "notional_usd": 100.0,
        "trade_id": suffix * 64,
        "liquidatable_net": True,
        "coin": "BTC",
        "direction": 1,
    }


def test_pnl041_losing_wallets_remain_in_heldout_sample() -> None:
    proof = derive_heldout_vault_generalization([
        _trade("winner", 300, "a", 2.0),
        _trade("loser", 301, "b", -3.0),
    ], oos_start_ms=200)

    assert proof is not None
    assert proof["sample_count"] == 2
    assert proof["vaults_held_out"] == ["loser", "winner"]
    assert proof["heldout_profit_vault_count"] == 1
    assert proof["net_pnl_usd"] == -1.0


def test_pnl042_multiple_wallet_parameter_horizon_trials_keep_trial_count_explicit() -> None:
    values = [1.0, -0.5] * 13
    verdict = evaluer(values, n_essais=12, trial_sharpes=[0.1, 0.2, 0.3])

    assert verdict.n_essais == 12
    assert verdict.n_trades == 26
    assert verdict.n_sharpes_distribution == 3
    assert verdict.as_dict()["real_execution"] is False


def test_pnl043_burst_fragments_count_as_independent_episodes_not_trades() -> None:
    rows = [
        {"episode_id": "burst-a", "fragment_id": f"a-{index}"}
        for index in range(10)
    ] + [{"episode_id": "burst-b", "fragment_id": "b-1"}]
    receipt = independent_episode_receipt(rows)

    assert receipt["status"] == "PROVEN"
    assert receipt["independent_episode_count"] == 2
    assert receipt["fragment_count"] == 11


def test_pnl044_delayed_signal_placebo_is_falsified_in_both_shift_directions() -> None:
    receipt = delayed_data_falsification_receipt([
        {"delay_ms": 101, "max_delay_ms": 100, "advantage_valid": False, "shift": "lead"},
        {"delay_ms": 125, "max_delay_ms": 100, "advantage_valid": False, "shift": "lag"},
    ])

    assert receipt["status"] == "PROVEN"
    assert receipt["falsified_count"] == 2


def test_pnl045_matched_neutral_benchmark_uses_same_window_corpus_and_costs() -> None:
    receipt = neutral_benchmark_receipt([
        {
            "strategy_net": 2.0,
            "neutral_net": 1.0,
            "same_corpus": True,
            "same_costs": True,
        }
    ])

    assert receipt["status"] == "PROVEN"
    assert receipt["verdict"] == "STRATEGY_BEATS_MATCHED_NEUTRAL"


def test_pnl046_missing_buy_and_hold_data_is_not_zero_return() -> None:
    row = assembler_ligne(
        "COPY_VAULT",
        closed_pnls=None,
        n_independent=25,
        gross_edge_bps=10.0,
        fees_bps=1.0,
        spread_bps=1.0,
        slippage_bps=1.0,
        latency_bps=1.0,
        capacity_usd=200.0,
        fill_ratios=[1.0],
        latency_p95_ms=10.0,
        oos_net_bps=1.0,
        forward_net_bps=1.0,
    )

    assert row.pnl_usd is None
    assert row.roi is None
    assert row.verdict == "MORE_DATA"


def test_pnl047_short_or_constant_series_never_certifies_sharpe() -> None:
    short = evaluer([1.0], n_essais=1)
    constant = evaluer([1.0] * 25, n_essais=1)

    assert short.motif == MOTIF_TROP_PEU_DE_TRADES
    assert short.survit is False
    assert constant.survit is False
    assert constant.proba_deflatee < 0.95


def test_pnl048_expectancy_without_minimum_independent_sample_stays_unpromoted() -> None:
    row = assembler_ligne(
        "COPY_VAULT",
        closed_pnls=[1.0, -0.2],
        n_independent=2,
        gross_edge_bps=10.0,
        fees_bps=1.0,
        spread_bps=1.0,
        slippage_bps=1.0,
        latency_bps=1.0,
        capacity_usd=200.0,
        fill_ratios=[1.0],
        latency_p95_ms=10.0,
        oos_net_bps=1.0,
        forward_net_bps=1.0,
    )

    assert row.verdict == "MORE_DATA"
    assert row.n_independent == 2


def test_pnl049_zero_trade_days_are_included_in_calendar_net() -> None:
    receipt = summarize_complete_utc_days(
        [
            {"net_pnl_usd": 1.0, "timestamp_ms": 1},
            {"net_pnl_usd": 2.0, "timestamp_ms": (2 * UTC_DAY_MS) + 1},
        ],
        value_key="net_pnl_usd",
        timestamp_key="timestamp_ms",
        complete_day_starts_ms=[0, UTC_DAY_MS, 2 * UTC_DAY_MS],
    )

    assert receipt["status"] == "MEASURABLE"
    assert receipt["calendar_day_count"] == 3
    assert receipt["active_day_count"] == 2
    assert receipt["zero_trade_days"] == 1
    assert receipt["calendar_day_net_pnl_usd"] == [1.0, 0.0, 2.0]


def test_pnl050_ex_post_trimming_keeps_losing_trades_in_audited_count() -> None:
    receipt = extreme_trade_robustness_receipt(
        [{"net_pnl_bps": 10.0}, {"net_pnl_bps": -5.0}, {"net_pnl_bps": 1.0}, {"net_pnl_bps": 2.0}],
        top_n=1,
    )

    assert receipt["status"] == "PROVEN"
    assert receipt["total_trades"] == 4
    assert receipt["removed_top_n"] == 1
    assert receipt["trimmed_mean"] == (-5.0 + 1.0 + 2.0) / 3.0

