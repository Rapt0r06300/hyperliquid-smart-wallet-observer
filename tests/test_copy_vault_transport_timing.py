from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from hl_observer.collection import userfills_live as UL

ROOT = Path(__file__).resolve().parents[1]


def _collector():
    spec = importlib.util.spec_from_file_location(
        "collector_copy_vault_transport",
        ROOT / "tools" / "collecter_userfills_vaults.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_userfill_keeps_exact_receive_wall_mono_and_connection() -> None:
    msg = {
        "channel": "userFills",
        "sequence": 42,
        "data": {
            "user": "0xabc",
            "fills": [
                {
                    "coin": "SOL",
                    "px": "150",
                    "sz": "1",
                    "side": "B",
                    "dir": "Open Long",
                    "time": 1_000,
                    "tid": 7,
                    "oid": 11,
                    "hash": "0xfill",
                }
            ],
        },
    }
    [fill] = UL.parser_message_userfills(
        msg,
        vault="0xabc",
        received_at_ms=1_050,
        receive_mono_ns=123_456_789,
        connection_id="userfills-A-1",
    )
    assert fill["ts_ms"] == 1_000
    assert fill["received_at_ms"] == 1_050
    assert fill["recv_mono_ns"] == 123_456_789
    assert fill["connection_id"] == "userfills-A-1"
    assert fill["frame_sequence"] == 42


def test_worker_never_overwrites_true_ws_receive_time(tmp_path, monkeypatch) -> None:
    collector = _collector()
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    monkeypatch.setattr(collector, "_TAPE_FILLS", None)
    monkeypatch.setattr(collector.CO, "COHORTES", {})
    monkeypatch.setattr(collector.time, "time", lambda: 5.0)

    fill = {
        "vault": "0xabc",
        "coin": "SOL",
        "ts_ms": 1_000,
        "received_at_ms": 1_050,
        "recv_mono_ns": 123_456_789,
        "connection_id": "userfills-A-1",
        "source": "LIVE_WS",
        "isSnapshot": False,
        "hash": "0xfill",
    }
    collector._traiter_un(tmp_path, fill, set(), 0.123456789)

    saved = json.loads((tmp_path / collector.FILLS_LIVE).read_text(encoding="utf-8"))
    assert saved["received_at_ms"] == 1_050
    assert saved["processed_at_ms"] == 5_000
    assert saved["recv_mono_ns"] == 123_456_789
    assert saved["connection_id"] == "userfills-A-1"


def test_copy_vault_journal_separates_transport_and_processing_latency(tmp_path) -> None:
    collector = _collector()
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    fill = {
        "vault": "0xabc",
        "coin": "SOL",
        "ts_ms": 1_000,
        "received_at_ms": 1_050,
        "recv_mono_ns": 123_456_789,
        "connection_id": "userfills-A-1",
        "source": "LIVE_WS",
        "isSnapshot": False,
    }
    collector._journal(tmp_path, fill, "PROBE", {"refus": "TEST"}, 1_080)
    row = json.loads((tmp_path / collector.JOURNAL).read_text(encoding="utf-8"))
    assert row["latence_fill_receive_ms"] == 50
    assert row["latence_receive_process_ms"] == 30
    assert row["latence_fill_decision_ms"] == 80
    assert row["received_at_ms"] == 1_050
    assert row["processed_at_ms"] == 1_080


@pytest.mark.parametrize("received_at_ms", [None, 0, -1])
def test_worker_quarantines_invalid_receive_clock_without_reconstruction(
    tmp_path, monkeypatch, received_at_ms,
) -> None:
    collector = _collector()
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    monkeypatch.setattr(collector, "_TAPE_FILLS", None)
    monkeypatch.setattr(collector.time, "time", lambda: 5.0)
    monkeypatch.setattr(collector.CO, "COHORTES", {"probe": object()})
    monkeypatch.setattr(collector, "ETATS", {"probe": {}})
    calls = []
    monkeypatch.setattr(collector.CO, "traiter_fill", lambda *args, **kwargs: calls.append(args))

    fill = {
        "vault": "0xabc", "coin": "SOL", "ts_ms": 1_000,
        "received_at_ms": received_at_ms, "source": "LIVE_WS",
        "isSnapshot": False, "hash": "0xfill",
    }
    collector._traiter_un(tmp_path, fill, set(), 0.123456789)

    rows = [
        json.loads(line)
        for line in (tmp_path / collector.FILLS_UNCLASSIFIED).read_text(encoding="utf-8").splitlines()
    ]
    [row] = rows
    assert row["received_at_ms"] is None
    assert row["received_at_ms_raw"] == received_at_ms
    assert row["processed_at_ms"] == 5_000
    assert row["reason"] == "FILL_RECEIVE_TIMESTAMP_INVALID"
    assert row["raw_payload"]["hash"] == "0xfill"
    assert calls == []
    assert not (tmp_path / collector.FILLS_LIVE).exists()


def test_journal_keeps_unknown_receive_time_and_does_not_compute_fake_latency(tmp_path) -> None:
    collector = _collector()
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    fill = {"vault": "0xabc", "coin": "SOL", "ts_ms": 1_000, "source": "LIVE_WS"}

    collector._journal(tmp_path, fill, "PROBE", {"refus": "TEST"}, 1_080)

    row = json.loads((tmp_path / collector.JOURNAL).read_text(encoding="utf-8"))
    assert row["received_at_ms"] is None
    assert row["received_at_ms_raw"] is None
    assert row["latence_fill_receive_ms"] is None
    assert row["latence_receive_process_ms"] is None
    assert row["latence_fill_decision_ms"] is None
