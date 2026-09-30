from __future__ import annotations

import json
from types import SimpleNamespace

import hl_observer.ui.status_routes as status


def _prepare_runtime_tape(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime" / "data" / "simulation_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(status, "simulation_state_path", lambda _settings: state_path)
    return state_path.parent / "bbo_tape.jsonl"


def test_local_bbo_marks_fail_closed_without_positions_or_tape(tmp_path, monkeypatch) -> None:
    tape = _prepare_runtime_tape(tmp_path, monkeypatch)
    settings = SimpleNamespace()

    assert status._local_bbo_marks(None, raw_positions=[{"coin": "BTC"}], current_ms=1_000)["read_status"] == "NO_OPEN_POSITION"
    assert status._local_bbo_marks(settings, raw_positions=[], current_ms=1_000)["read_status"] == "NO_OPEN_POSITION"
    assert status._local_bbo_marks(settings, raw_positions=[{"position_id": "LONG"}], current_ms=1_000)["read_status"] == "NO_OPEN_POSITION_COIN"
    assert not tape.exists()
    assert status._local_bbo_marks(settings, raw_positions=[{"coin": "BTC"}], current_ms=1_000)["read_status"] == "LOCAL_BBO_MISSING"


def test_local_bbo_marks_ignore_invalid_stale_and_non_hyperliquid_rows(tmp_path, monkeypatch) -> None:
    tape = _prepare_runtime_tape(tmp_path, monkeypatch)
    current_ms = 2_000_000_000_000
    rows = [
        "not-json",
        json.dumps({"coin": "BTC", "venue": "BINANCE", "bid": 100, "ask": 101, "ts_wall_ms": current_ms - 10}),
        json.dumps({"coin": "BTC", "venue": "HL", "bid": 102, "ask": 101, "ts_wall_ms": current_ms - 10}),
        json.dumps({"coin": "BTC", "venue": "HL", "bid": 100, "ask": 101, "ts_wall_ms": current_ms - status.LIVE_MARKS_MAX_STALE_MS - 1}),
        json.dumps({"coin": "ETH", "venue": "HL", "bid": 50, "ask": 51, "ts_wall_ms": current_ms - 10}),
    ]
    tape.write_text("\n".join(rows) + "\n", encoding="utf-8")

    result = status._local_bbo_marks(SimpleNamespace(), raw_positions=[{"coin": "BTC"}], current_ms=current_ms)

    assert result["read_status"] == "LOCAL_BBO_NO_FRESH_MARK"
    assert result["prices"] == {}


def test_local_bbo_marks_use_freshest_hyperliquid_executable_quote(tmp_path, monkeypatch) -> None:
    tape = _prepare_runtime_tape(tmp_path, monkeypatch)
    current_ms = 2_000_000_000_000
    rows = [
        {"coin": "BTC", "venue": "HL", "bid": 99.0, "ask": 101.0, "ts_wall_ms": current_ms - 500},
        {"coin": "BTC", "venue": "HYPERLIQUID", "bid": 100.0, "ask": 102.0, "ts_wall_ms": current_ms - 100},
    ]
    tape.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = status._local_bbo_marks(
        SimpleNamespace(),
        raw_positions=[{"coin": "BTC", "direction": "LONG"}],
        current_ms=current_ms,
    )

    assert result["read_only"] is True
    assert result["read_status"] == "OK_LOCAL_BBO"
    assert result["prices"] == {"BTC": 101.0, "BTC|LONG": 100.0, "BTC|SHORT": 102.0}
    assert result["sources"] == {
        "BTC": "LOCAL_BBO_MID",
        "BTC|LONG": "LOCAL_BBO_BID",
        "BTC|SHORT": "LOCAL_BBO_ASK",
    }
    assert result["timestamps"]["BTC|LONG"] == current_ms - 100
    assert result["latest_exchange_ts"] == current_ms - 100
