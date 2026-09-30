from __future__ import annotations

import pytest

from hl_observer.backtesting.cross_venue_certified import BBO_SOURCE_MODE
from hl_observer.backtesting.cross_venue_v5_persistence_train import (
    explore_cross_venue_v5_train,
    replay_persistence_policy_train,
)


def _atomic(ts: int, hl_mid: float, bin_mid: float) -> tuple:
    half = 0.005
    return (
        ts,
        "ATOMIC_BBO",
        hl_mid - half,
        hl_mid + half,
        bin_mid - half,
        bin_mid + half,
    )


def _persistent_path() -> tuple[dict, dict, int]:
    start = 1_800_000_000_000
    rows = [
        _atomic(start, 100.0, 100.0),
        _atomic(start + 1_000, 100.40, 100.0),
        _atomic(start + 1_400, 100.40, 100.0),
        _atomic(start + 1_500, 100.40, 100.0),
        _atomic(start + 1_600, 100.40, 100.0),
        _atomic(start + 2_500, 100.05, 100.05),
        *[
            _atomic(start + offset, 100.05, 100.05)
            for offset in range(5_000, 30_001, 2_500)
        ],
        _atomic(start + 31_500, 100.05, 100.05),
        _atomic(start + 32_000, 100.05, 100.05),
    ]
    return {"BTC": rows}, {"BTC": [(row[0], 1_000.0) for row in rows]}, start


@pytest.mark.parametrize(
    ("confirmation_count", "max_window_ms", "expected_entry_ms"),
    ((2, 1_000, 1_500), (3, 2_000, 1_600)),
)
def test_cross_v5_entre_sur_la_derniere_confirmation_et_reconcilie_les_couts(
    confirmation_count: int,
    max_window_ms: int,
    expected_entry_ms: int,
) -> None:
    series, depth, start = _persistent_path()

    trades, diagnostics = replay_persistence_policy_train(
        series,
        depth,
        confirmation_count=confirmation_count,
        max_confirmation_window_ms=max_window_ms,
        take_profit_net_bps=8.0,
        stop_loss_net_bps=30.0,
        train_end_ms=start + 40_000,
    )

    assert diagnostics["PERSISTENT_EXECUTABLE_ENTRY_PATH"] == 1
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_ts_ms"] == start + expected_entry_ms
    assert trade["confirmation_count"] == confirmation_count
    assert trade["confirmation_duration_ms"] == expected_entry_ms - 1_400
    assert trade["exit_reason"] == "TAKE_PROFIT_NET"
    assert trade["net_pnl_usd"] == pytest.approx(
        trade["gross_pnl_usd"] - trade["fees_usd"]
    )
    assert trade["LIQUIDATABLE_NET"] is True
    assert trade["paper_read_only"] is True
    assert trade["real_execution"] is False


def test_cross_v5_rejette_un_ecart_present_sur_une_seule_observation() -> None:
    series, depth, start = _persistent_path()
    series["BTC"][3] = _atomic(start + 1_500, 100.05, 100.05)

    trades, diagnostics = replay_persistence_policy_train(
        series,
        depth,
        confirmation_count=2,
        max_confirmation_window_ms=1_000,
        take_profit_net_bps=8.0,
        stop_loss_net_bps=30.0,
        train_end_ms=start + 40_000,
    )

    assert trades == []
    assert diagnostics["CONFIRMATION_BASIS_REVERSED"] == 1
    assert diagnostics.get("PERSISTENT_EXECUTABLE_ENTRY_PATH", 0) == 0


def test_cross_v5_rejette_confirmation_trop_tardive_sans_attendre_un_rebond() -> None:
    series, depth, start = _persistent_path()
    series["BTC"] = [
        series["BTC"][0],
        series["BTC"][1],
        series["BTC"][2],
        _atomic(start + 2_500, 100.40, 100.0),
        *series["BTC"][6:],
    ]
    depth["BTC"] = [(row[0], 1_000.0) for row in series["BTC"]]

    trades, diagnostics = replay_persistence_policy_train(
        series,
        depth,
        confirmation_count=2,
        max_confirmation_window_ms=1_000,
        take_profit_net_bps=8.0,
        stop_loss_net_bps=30.0,
        train_end_ms=start + 40_000,
    )

    assert trades == []
    assert diagnostics["CONFIRMATION_WINDOW_EXPIRED"] == 1


def test_cross_v5_reste_train_only_et_compte_toute_la_famille_de_tests() -> None:
    series, depth, _ = _persistent_path()

    result = explore_cross_venue_v5_train(
        series,
        depth,
        source_mode=BBO_SOURCE_MODE,
    )

    assert result["status"] == "NO_ROBUST_TRAIN_CANDIDATE"
    assert result["selection_eligible"] is False
    assert result["physical_freeze_allowed"] is False
    assert result["heldout_evaluated"] is False
    assert result["fixed_grid"]["trial_count"] == 320
    assert result["cost_contract"]["confirmation_enters_on_last_observation"] is True
    assert result["real_execution"] is False


def test_cross_v5_echoue_ferme_sans_source_certifiee() -> None:
    result = explore_cross_venue_v5_train({}, {}, source_mode="LEGACY")

    assert result["status"] == "MORE_DATA_CERTIFIED_ATOMIC_BOOK_REQUIRED"
    assert result["selection_eligible"] is False
    assert result["heldout_evaluated"] is False
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
