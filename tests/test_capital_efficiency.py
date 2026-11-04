from __future__ import annotations

from hl_observer.research.capital_efficiency import compare_selectivity_vs_volume


def _row(ts: int, episode: str, selected: bool, gross: float, costs: float, margin: float, duration: float) -> dict:
    return {
        "signal_ts_ms": ts,
        "episode_id": episode,
        "selected": selected,
        "gross_pnl_usd": gross,
        "costs_usd": costs,
        "margin_usd": margin,
        "duration_h": duration,
    }


def test_selectivity_is_compared_after_costs_and_capital_hours() -> None:
    train = [
        _row(100, "tr-1", True, 4.0, 1.0, 100.0, 1.0),
        _row(110, "tr-2", False, 1.0, 1.0, 100.0, 1.0),
    ]
    oos = [
        _row(2_000, "oos-1", True, 8.0, 2.0, 100.0, 1.0),
        _row(2_010, "oos-2", False, 1.0, 1.0, 100.0, 1.0),
    ]

    result = compare_selectivity_vs_volume(train, oos, cutoff_ms=1_000)

    assert result["status"] == "COMPARABLE"
    assert result["baseline_oos"]["net_pnl_usd"] == 6.0
    assert result["selective_oos"]["net_pnl_usd"] == 6.0
    assert result["selective_oos"]["net_per_capital_hour"] == 0.06
    assert result["trade_count_is_not_objective"] is True
    assert result["promotion"] == "DISABLED_UNTIL_REVIEW"


def test_selectivity_fails_closed_on_future_or_missing_selection() -> None:
    future_train = _row(2_000, "future", True, 1.0, 1.0, 100.0, 1.0)
    assert compare_selectivity_vs_volume(
        [future_train],
        [_row(3_000, "oos", True, 1.0, 1.0, 100.0, 1.0)],
        cutoff_ms=1_000,
    )["status"] == "UNMEASURABLE"

    missing = _row(100, "tr", True, 1.0, 1.0, 100.0, 1.0)
    missing.pop("selected")
    assert compare_selectivity_vs_volume(
        [missing],
        [_row(2_000, "oos", True, 1.0, 1.0, 100.0, 1.0)],
        cutoff_ms=1_000,
    )["status"] == "UNMEASURABLE"
