from __future__ import annotations

from hl_observer.backtesting.cross_venue_certified import BBO_SOURCE_MODE
from hl_observer.backtesting.cross_venue_v4_train import (
    MIN_ENTRY_EXECUTABLE_EDGE_BPS,
    explore_cross_venue_v4_train,
    replay_policy_train,
)


def _atomic(ts: int, hl_mid: float, bin_mid: float) -> tuple:
    half = 0.005
    return (
        ts,
        "ATOMIC",
        hl_mid - half,
        hl_mid + half,
        bin_mid - half,
        bin_mid + half,
    )


def _profitable_path() -> tuple[dict, dict, int]:
    start = 1_800_000_000_000
    series = {
        "BTC": [
            _atomic(start, 100.0, 100.0),
            _atomic(start + 1_000, 100.40, 100.0),
            _atomic(start + 1_400, 100.40, 100.0),
            _atomic(start + 1_500, 100.40, 100.0),
            _atomic(start + 2_500, 100.05, 100.05),
            *[
                _atomic(start + offset, 100.05, 100.05)
                for offset in range(5_000, 30_001, 2_500)
            ],
            _atomic(start + 31_500, 100.05, 100.05),
        ]
    }
    depth = {"BTC": [(row[0], 1_000.0) for row in series["BTC"]]}
    return series, depth, start


def test_cross_v4_attend_un_profit_net_executable_avant_de_clore() -> None:
    series, depth, start = _profitable_path()

    trades, diagnostics = replay_policy_train(
        series,
        depth,
        take_profit_net_bps=8.0,
        stop_loss_net_bps=30.0,
        train_end_ms=start + 40_000,
    )

    assert diagnostics["EXECUTABLE_ENTRY_PATH"] == 1
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_executable_edge_bps"] >= MIN_ENTRY_EXECUTABLE_EDGE_BPS
    assert trade["exit_reason"] == "TAKE_PROFIT_NET"
    assert trade["exit_ts_ms"] == start + 2_500
    assert trade["net_bps"] >= 8.0
    assert trade["LIQUIDATABLE_NET"] is True
    assert trade["real_execution"] is False


def test_cross_v4_ne_confond_pas_le_cout_immediat_avec_un_stop_valide() -> None:
    series, depth, start = _profitable_path()

    patient, _ = replay_policy_train(
        series,
        depth,
        take_profit_net_bps=8.0,
        stop_loss_net_bps=30.0,
        train_end_ms=start + 40_000,
    )
    premature, _ = replay_policy_train(
        series,
        depth,
        take_profit_net_bps=8.0,
        stop_loss_net_bps=12.0,
        train_end_ms=start + 40_000,
    )

    assert patient[0]["net_pnl_usd"] > 0.0
    assert premature[0]["exit_reason"] == "STOP_LOSS_NET"
    assert premature[0]["exit_ts_ms"] == start + 1_500
    assert premature[0]["net_pnl_usd"] < 0.0


def test_cross_v4_reste_train_only_et_ne_gel_pas_un_echantillon_insuffisant() -> None:
    series, depth, _ = _profitable_path()

    result = explore_cross_venue_v4_train(
        series,
        depth,
        source_mode=BBO_SOURCE_MODE,
    )

    assert result["status"] == "NO_ROBUST_TRAIN_CANDIDATE"
    assert result["selection_eligible"] is False
    assert result["physical_freeze_allowed"] is False
    assert result["heldout_evaluated"] is False
    assert result["fixed_grid"]["trial_count"] == 160
    assert result["cost_contract"]["exit_thresholds_use_liquidatable_net_bps"] is True
    assert result["real_execution"] is False
