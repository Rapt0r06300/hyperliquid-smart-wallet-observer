from __future__ import annotations

from types import SimpleNamespace

import hl_observer.ui.status_routes as status


def _marked(*, equity: float = 1001.0, pnl: float = 1.0) -> dict[str, object]:
    return {
        "estimated_net_pnl_usdc": pnl,
        "current_equity_usdt": equity,
        "realized_pnl_usdc": 0.4,
        "unrealized_pnl_usdc": 0.6,
        "open_exposure_usdt": 100.0,
        "positions": [{"coin": "BTC"}],
        "marks_used": 1,
        "marks_missing": 0,
    }


def test_fast_equity_append_recovers_non_list_history_without_persistence() -> None:
    state = SimpleNamespace(simulation_equity_history=None)

    status._append_fast_equity_point(None, state, _marked(), 1_000)

    assert isinstance(state.simulation_equity_history, list)
    assert len(state.simulation_equity_history) == 1
    assert state.simulation_equity_history[0]["timestamp_ms"] == 1_000


def test_fast_equity_same_timestamp_replaces_changed_point_and_persists(monkeypatch) -> None:
    persisted: list[tuple[object, object]] = []
    settings = SimpleNamespace()
    state = SimpleNamespace(
        simulation_equity_history=[
            {
                "timestamp_ms": 1_000,
                "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID",
                "current_pnl_usdc": 1.0,
                "current_equity_usdt": 1001.0,
                "realized_pnl_usdc": 0.4,
                "unrealized_pnl_usdc": 0.6,
                "open_exposure_usdt": 100.0,
                "open_positions": 1,
            }
        ]
    )
    monkeypatch.setattr(status, "persist_simulation_state", lambda cfg, current: persisted.append((cfg, current)))

    status._append_fast_equity_point(settings, state, _marked(equity=1002.0, pnl=2.0), 1_000)

    assert len(state.simulation_equity_history) == 1
    assert state.simulation_equity_history[0]["current_equity_usdt"] == 1002.0
    assert persisted == [(settings, state)]


def test_fast_equity_coalesces_recent_point_and_records_persist_failure(monkeypatch) -> None:
    failures: list[str] = []
    settings = SimpleNamespace()
    state = SimpleNamespace(
        simulation_equity_history=[
            {
                "timestamp_ms": 1_000,
                "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID",
                "current_pnl_usdc": 1.0,
                "current_equity_usdt": 1001.0,
                "realized_pnl_usdc": 0.4,
                "unrealized_pnl_usdc": 0.6,
                "open_exposure_usdt": 100.0,
                "open_positions": 1,
            }
        ]
    )

    def _raise_oserror(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(status, "persist_simulation_state", _raise_oserror)
    monkeypatch.setattr(status, "_noter_echec", failures.append)

    status._append_fast_equity_point(settings, state, _marked(equity=1003.0, pnl=3.0), 1_100)

    assert len(state.simulation_equity_history) == 1
    assert state.simulation_equity_history[0]["timestamp_ms"] == 1_100
    assert state.simulation_equity_history[0]["current_equity_usdt"] == 1003.0
    assert failures == ["hl_observer/ui/status_routes.py:1811"]


def test_fast_equity_session_start_is_not_coalesced_and_append_failure_is_fail_closed(monkeypatch) -> None:
    settings = SimpleNamespace()
    state = SimpleNamespace(
        simulation_equity_history=[
            {
                "timestamp_ms": 1_000,
                "source": "SESSION_START",
                "current_pnl_usdc": 0.0,
                "current_equity_usdt": 1000.0,
                "realized_pnl_usdc": 0.0,
                "unrealized_pnl_usdc": 0.0,
                "open_exposure_usdt": 0.0,
                "open_positions": 0,
            }
        ]
    )

    def _raise_oserror(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(status, "persist_simulation_state", _raise_oserror)

    status._append_fast_equity_point(settings, state, _marked(), 1_000)

    assert len(state.simulation_equity_history) == 2
    assert state.simulation_equity_history[-1]["source"] == "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID"


def test_dedupe_equity_history_keeps_clean_monotonic_history_unchanged() -> None:
    first = {"timestamp_ms": 1, "source": "A"}
    second = {"timestamp_ms": 2, "source": "B"}
    history = [first, second]

    status._dedupe_equity_history_timestamps(history)

    assert history == [first, second]
    assert history[0] is first
    assert history[1] is second
