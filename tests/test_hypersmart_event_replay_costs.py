from __future__ import annotations

import pytest

from hyper_smart_observer.backtesting.event_replay import BOOK, FILL, ReplayEvent, replay_event_stream


def test_replay_facture_frais_spread_slippage_et_delai() -> None:
    report = replay_event_stream(
        "0x" + "1" * 40,
        [
            ReplayEvent(BOOK, "BTC", 1_000, best_bid=99.0, best_ask=101.0),
            ReplayEvent(FILL, "BTC", 1_100, closed_pnl=10.0, delay_ms=1_000),
        ],
        notional_per_trade=100.0,
        fee_rate_bps=5.0,
        slippage_bps=5.0,
        delay_bps_per_second=1.0,
        fee_sides=2,
    )
    assert report.simulated_trades == 1
    assert report.gross_pnl == pytest.approx(10.0)
    assert report.cost_breakdown["fees"] == pytest.approx(0.10)
    assert report.cost_breakdown["spread"] == pytest.approx(2.0)
    assert report.cost_breakdown["slippage"] == pytest.approx(0.10)
    assert report.cost_breakdown["delay"] == pytest.approx(0.01)
    assert report.total_costs == pytest.approx(2.21)
    assert report.net_pnl == pytest.approx(7.79)
    assert report.equity_curve == pytest.approx([7.79])


def test_replay_partial_fill_reduit_gain_et_couts() -> None:
    report = replay_event_stream(
        "0x" + "2" * 40,
        [
            ReplayEvent(BOOK, "ETH", 1_000, best_bid=99.9, best_ask=100.1),
            ReplayEvent(
                FILL,
                "ETH",
                1_001,
                closed_pnl=8.0,
                is_partial=True,
                fill_fraction=0.25,
            ),
        ],
        notional_per_trade=100.0,
        fee_rate_bps=0.0,
        slippage_bps=0.0,
        delay_bps_per_second=0.0,
    )
    assert report.gross_pnl == pytest.approx(2.0)
    assert report.cost_breakdown["spread"] == pytest.approx(0.05)
    assert report.net_pnl == pytest.approx(1.95)
    assert any("PARTIAL_FILL:0.2500" in warning for warning in report.warnings)


def test_replay_missed_fill_est_saute_sans_pnl_fictif() -> None:
    report = replay_event_stream(
        "0x" + "3" * 40,
        [
            ReplayEvent(BOOK, "SOL", 1_000, best_bid=99.0, best_ask=101.0),
            ReplayEvent(FILL, "SOL", 1_001, closed_pnl=1000.0, missed_fill=True),
        ],
    )
    assert report.simulated_trades == 0
    assert report.skipped_actions == 1
    assert report.net_pnl == 0.0
    assert report.gross_pnl == 0.0
    assert any("MISSED_FILL" in warning for warning in report.warnings)


def test_replay_refuse_carnet_invalide_et_fill_fraction_invalide() -> None:
    report = replay_event_stream(
        "0x" + "4" * 40,
        [
            ReplayEvent(BOOK, "BTC", 1_000, best_bid=102.0, best_ask=101.0),
            ReplayEvent(FILL, "BTC", 1_001, closed_pnl=10.0, fill_fraction=2.0),
        ],
    )
    assert report.simulated_trades == 0
    assert report.skipped_actions == 1
    assert "BTC:INVALID_BOOK" in report.warnings
    assert "BTC:INVALID_FILL_FRACTION" in report.warnings
