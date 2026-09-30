"""Coverage contracts for the live PAPER-only graded halt guard."""

from __future__ import annotations

from hl_observer.risk.graded_halt import AMBER_LOSS_ENV, _f, realized_window_pnl_usd


def test_realized_window_pnl_ignores_malformed_non_close_and_stale_events() -> None:
    now_ms = 1_000_000
    events = [
        None,
        {
            "paper_action_type": "OPEN",
            "observed_at_ms": now_ms,
            "estimated_net_pnl_usdc": -99.0,
        },
        {
            "paper_action_type": "CLOSE",
            "observed_at_ms": now_ms - 61_000,
            "estimated_net_pnl_usdc": -99.0,
        },
        {
            "paper_action_type": "CLOSE",
            "observed_at_ms": now_ms,
            "estimated_net_pnl_usdc": -3.5,
        },
    ]

    assert realized_window_pnl_usd(events, now_ms, 1.0) == -3.5


def test_invalid_graded_halt_threshold_falls_back_to_safe_default() -> None:
    assert _f(AMBER_LOSS_ENV, {AMBER_LOSS_ENV: "not-a-number"}) == 12.0
