from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.config.loader import load_settings
from hl_observer.simulation.accounting_truth import (
    allocated_entry_cost_usdc,
    first_not_none,
    named_roi_metrics,
    round_trip_net_pnl_usdc,
)
from hl_observer.simulation.ledger_integrity import (
    LEDGER_CORRUPTED,
    LEDGER_OK,
    read_chain,
    seal_chain,
    verify_chain,
    write_chain_atomic,
)
from hl_observer.simulation.paper_ledger import PaperLedger
from hl_observer.ui import persistent_state
from hl_observer.ui.fusion_persistent_adapter import _trim_ledger
from hl_observer.ui.persistent_state import (
    load_or_create_ui_state,
    persist_simulation_state,
    simulation_ledger_path,
    simulation_state_path,
)
from hl_observer.ui.state import UiState
from hl_observer.ui.status_routes import _mark_to_market_positions


def test_ledger_event_sequence_monotonic() -> None:
    ledger = PaperLedger(starting_balance_usdc=1_000.0, session_id="paper:test-sequence")
    ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=100.0,
        fill_price=20.0,
        timestamp_ms=1_000,
    )
    ledger.mark_to_market({"HYPE": 21.0}, timestamp_ms=2_000)

    assert [event.event_seq for event in ledger.events] == list(range(1, len(ledger.events) + 1))
    assert ledger.verify_event_chain() is True


def test_ledger_event_hash_chain_valid() -> None:
    rows = seal_chain(
        [
            {"record_type": "SESSION_START", "timestamp_ms": 1, "equity_usdc": 1_000.0},
            {"record_type": "MARK", "timestamp_ms": 2, "equity_usdc": 1_001.0},
        ],
        session_id="paper:test-chain",
    )

    assert verify_chain(rows) == rows
    assert rows[0]["prev_hash"] == "0" * 64
    assert rows[1]["prev_hash"] == rows[0]["event_hash"]


def test_corrupt_ledger_line_blocks_strict_pnl(tmp_path: Path) -> None:
    ledger_path = tmp_path / "paper_ledger.jsonl"
    write_chain_atomic(
        ledger_path,
        [{"record_type": "SESSION_START", "timestamp_ms": 1, "equity_usdc": 1_000.0}],
        session_id="paper:test-corruption",
    )
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write("{not-json}\n")

    result = read_chain(ledger_path)

    assert result.status == LEDGER_CORRUPTED
    assert result.strict_pnl_allowed is False
    assert result.errors
    assert result.errors[0]["line"] == 2


def test_atomic_chain_round_trip_preserves_zero_values(tmp_path: Path) -> None:
    ledger_path = tmp_path / "paper_ledger.jsonl"
    rows = write_chain_atomic(
        ledger_path,
        [
            {
                "record_type": "STATE_CHECKPOINT",
                "timestamp_ms": 1,
                "state": {"realized_pnl_usdc": 0.0, "open_positions": {}},
            }
        ],
        session_id="paper:test-zero",
    )

    result = read_chain(ledger_path)

    assert result.status == LEDGER_OK
    assert result.events == rows
    assert result.events[0]["state"]["realized_pnl_usdc"] == 0.0


def test_first_not_none_replaces_numeric_or_fallbacks() -> None:
    assert first_not_none(None, 0.0, 7.0) == 0.0
    assert first_not_none(None, 0, 7) == 0
    assert first_not_none(None, None) is None


def test_roi_denominators_are_named_and_non_artificial() -> None:
    metrics = named_roi_metrics(
        pnl_usdc=25.0,
        initial_capital_usdc=1_000.0,
        peak_margin_usdc=250.0,
        average_capital_at_risk_usdc=None,
    ).to_dict()

    assert metrics["roi_on_initial_capital_pct"] == 2.5
    assert metrics["roi_on_peak_margin_pct"] == 10.0
    assert metrics["roi_on_average_capital_at_risk_pct"] is None
    assert "roi_pct" not in metrics


def test_unrealized_pnl_is_in_equity() -> None:
    ledger = PaperLedger(starting_balance_usdc=1_000.0, session_id="paper:test-equity")
    ledger.open_position(
        coin="BTC",
        side="LONG",
        notional_usdc=100.0,
        fill_price=100.0,
        timestamp_ms=1_000,
        fee_bps=0.0,
    )
    ledger.mark_to_market({"BTC": 110.0}, timestamp_ms=2_000)

    assert ledger.unrealized_pnl_usdc == 10.0
    assert ledger.equity_usdc == 1_010.0
    assert ledger.snapshot()["roi"]["roi_on_initial_capital_pct"] == 1.0


def test_drawdown_updates_on_marks_not_only_trade_events() -> None:
    ledger = PaperLedger(starting_balance_usdc=1_000.0, session_id="paper:test-drawdown")
    ledger.open_position(
        coin="ETH",
        side="LONG",
        notional_usdc=100.0,
        fill_price=100.0,
        timestamp_ms=1_000,
        fee_bps=0.0,
    )
    ledger.mark_to_market({"ETH": 110.0}, timestamp_ms=2_000)
    assert ledger.high_water_equity_usdc == 1_010.0

    ledger.mark_to_market({"ETH": 95.0}, timestamp_ms=3_000)

    assert ledger.equity_usdc == 995.0
    assert ledger.drawdown_usdc == 15.0
    assert ledger.events[-1].drawdown_usdc == 15.0


def test_non_finite_roi_is_rejected() -> None:
    with pytest.raises(ValueError):
        named_roi_metrics(pnl_usdc=float("nan"), initial_capital_usdc=1_000.0)


def test_open_mark_and_close_share_exact_round_trip_cost_truth() -> None:
    """An unchanged price cannot create a close-time PnL jump."""

    marked = _mark_to_market_positions(
        [
            {
                "position_id": "paper:hype:long:1",
                "coin": "HYPE",
                "direction": "LONG",
                "size": 1.0,
                "entry_price": 100.0,
                "entry_costs": 0.12,
                "fee_already_embedded_in_entry_price": False,
            }
        ],
        starting_equity_usdt=1_000.0,
        realized_pnl_usdc=0.0,
        market_marks={
            "prices": {"HYPE": 100.0},
            "sources": {"HYPE": "test_real_mark"},
            "latest_exchange_ts": 2_000,
            "read_status": "OK",
        },
        current_ms=2_000,
    )
    close_net = round_trip_net_pnl_usdc(
        gross_pnl_usdc=0.0,
        entry_cost_usdc=0.12,
        exit_cost_usdc=0.12,
    )

    assert close_net == pytest.approx(-0.24)
    assert marked["unrealized_pnl_usdc"] == pytest.approx(close_net)
    assert marked["current_equity_usdt"] == pytest.approx(999.76)
    assert marked["positions"][0]["entry_cost_carried_usdc"] == 0.12
    assert marked["positions"][0]["pnl_accounting_status"] == "STRICT_ROUND_TRIP_COSTS_KNOWN"


def test_sltp_close_includes_entry_and_exit_costs_once() -> None:
    from hl_observer.paper_trading.sl_tp import SLTPConfig
    from hl_observer.paper_trading.sltp_runtime import apply_sltp_exits

    positions = {
        "wallet|HYPE|LONG": {
            "coin": "HYPE",
            "direction": "LONG",
            "side": "LONG",
            "size": 1.0,
            "avg_price": 100.0,
            "entry_costs": 0.1,
            "fee_already_embedded_in_entry_price": False,
        }
    }
    ledger: list[dict] = []

    apply_sltp_exits(
        positions,
        ledger,
        {"HYPE": 101.0},
        cost_bps=10.0,
        config=SLTPConfig(take_profit_bps=50.0, stop_loss_bps=50.0),
    )

    assert ledger[0]["gross_pnl_usdc"] == 1.0
    assert ledger[0]["entry_cost_carried_usdc"] == 0.1
    assert ledger[0]["fee_cost_usdc"] == 0.101
    assert ledger[0]["estimated_net_pnl_usdc"] == pytest.approx(0.799)
    assert ledger[0]["total_round_trip_cost_usdc"] == pytest.approx(0.201)


def test_partial_reduce_allocates_entry_cost_proportionally() -> None:
    position = {
        "entry_costs": 2.0,
        "fee_already_embedded_in_entry_price": False,
    }

    allocated = allocated_entry_cost_usdc(
        position,
        close_quantity=2.5,
        open_quantity=10.0,
    )

    assert allocated == pytest.approx(0.5)


def test_tampered_hash_chain_is_rejected() -> None:
    rows = list(
        seal_chain(
            [{"record_type": "SESSION_START", "timestamp_ms": 1, "equity_usdc": 1_000.0}],
            session_id="paper:test-tamper",
        )
    )
    rows[0]["equity_usdc"] = 9_999.0

    with pytest.raises(ValueError, match="event_hash mismatch"):
        verify_chain(rows)


def test_corrupt_chain_is_not_partially_trusted(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    good = seal_chain(
        [{"record_type": "SESSION_START", "timestamp_ms": 1, "equity_usdc": 1_000.0}],
        session_id="paper:test-partial",
    )[0]
    path.write_text(
        json.dumps(good, sort_keys=True) + "\n" + json.dumps({**good, "event_seq": 2}) + "\n",
        encoding="utf-8",
    )

    result = read_chain(path)

    assert result.status == LEDGER_CORRUPTED
    assert result.strict_pnl_allowed is False


def _settings_for(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'runtime' / 'data' / 'state.sqlite3'}"
    return settings


def _profitable_state() -> UiState:
    state = UiState()
    state.simulation_started_at_ms = 123_456
    state.simulation_session_id = "ui:test-recovery"
    state.simulation_starting_equity_usdt = 1_000.0
    state.simulation_realized_pnl_usdc = 12.5
    state.simulation_reproduced_entries_total = 1
    state.simulation_reproduced_exits_total = 1
    state.simulation_ledger_events = [
        {
            "event_id": "entry:1",
            "bot_replay_action": "PAPER_ENTRY_REPLAYED",
            "coin": "HYPE",
            "estimated_net_pnl_usdc": -0.05,
        },
        {
            "event_id": "exit:1",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "coin": "HYPE",
            "estimated_net_pnl_usdc": 12.55,
        },
    ]
    state.simulation_equity_history = [
        {
            "timestamp_ms": 123_456,
            "current_equity_usdt": 1_000.0,
            "current_pnl_usdc": 0.0,
        },
        {
            "timestamp_ms": 124_456,
            "current_equity_usdt": 1_012.5,
            "current_pnl_usdc": 12.5,
        },
    ]
    return state


def test_corrupt_state_recovers_from_ledger_or_blocks(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    state = _profitable_state()
    persist_simulation_state(settings, state)
    simulation_state_path(settings).write_text("{broken-json", encoding="utf-8")

    recovered = load_or_create_ui_state(settings)

    assert recovered.simulation_recovery_source == "LEDGER_CHECKPOINT"
    assert recovered.simulation_pnl_trusted is True
    assert recovered.simulation_realized_pnl_usdc == 12.5
    assert recovered.simulation_starting_equity_usdt == 1_000.0


def test_existing_ledger_with_missing_state_does_not_reset_capital(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    state = _profitable_state()
    persist_simulation_state(settings, state)
    simulation_state_path(settings).unlink()

    recovered = load_or_create_ui_state(settings)

    assert recovered.simulation_recovery_source == "LEDGER_CHECKPOINT"
    assert recovered.simulation_realized_pnl_usdc == 12.5
    assert recovered.simulation_starting_equity_usdt == 1_000.0
    assert recovered.simulation_realized_pnl_usdc != 0.0


def test_crash_after_ledger_append_before_snapshot_recovers_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings_for(tmp_path)
    state = _profitable_state()
    original_writer = persistent_state._atomic_write_json

    def crash_before_snapshot(path: Path, payload: dict, *, retries: int = 5) -> None:
        raise OSError("simulated crash after durable ledger commit")

    monkeypatch.setattr(persistent_state, "_atomic_write_json", crash_before_snapshot)
    with pytest.raises(OSError, match="simulated crash"):
        persist_simulation_state(settings, state)
    assert simulation_ledger_path(settings).exists()
    assert not simulation_state_path(settings).exists()

    monkeypatch.setattr(persistent_state, "_atomic_write_json", original_writer)
    recovered = load_or_create_ui_state(settings)

    assert recovered.simulation_recovery_source == "LEDGER_CHECKPOINT"
    assert recovered.simulation_realized_pnl_usdc == 12.5
    assert recovered.simulation_reproduced_entries_total == 1
    assert recovered.simulation_reproduced_exits_total == 1


def test_recovery_is_idempotent(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    state = _profitable_state()
    persist_simulation_state(settings, state)
    simulation_state_path(settings).unlink()

    first = load_or_create_ui_state(settings)
    second = load_or_create_ui_state(settings)

    assert first.simulation_realized_pnl_usdc == second.simulation_realized_pnl_usdc == 12.5
    assert first.simulation_ledger_events == second.simulation_ledger_events
    assert first.simulation_ledger_last_hash == second.simulation_ledger_last_hash
    assert first.simulation_session_id == second.simulation_session_id


def test_corrupt_runtime_ledger_blocks_snapshot_pnl(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    state = _profitable_state()
    persist_simulation_state(settings, state)
    with simulation_ledger_path(settings).open("a", encoding="utf-8") as handle:
        handle.write("{corrupt}\n")

    blocked = load_or_create_ui_state(settings)

    assert blocked.simulation_accounting_status == LEDGER_CORRUPTED
    assert blocked.simulation_pnl_trusted is False
    assert blocked.simulation_realized_pnl_usdc == 12.5


def test_canonical_ledger_truth_is_not_truncated_at_twenty_thousand_events() -> None:
    state = UiState()
    state.simulation_ledger_events = [
        {
            "event_id": f"event:{index}",
            "event": "PAPER_OPEN" if index == 0 else "MARK",
            "timestamp_ms": index + 1,
        }
        for index in range(20_001)
    ]

    _trim_ledger(state)
    safe = persistent_state._safe_ledger_payload(state.simulation_ledger_events)
    restored = persistent_state._state_from_payload(
        {
            "simulation_started_at_ms": 1,
            "simulation_starting_equity_usdt": 1_000.0,
            "simulation_ledger_events": safe,
        }
    )

    assert len(state.simulation_ledger_events) == 20_001
    assert len(safe) == 20_001
    assert restored is not None
    assert len(restored.simulation_ledger_events) == 20_001
    assert restored.simulation_ledger_events[0]["event_id"] == "event:0"
