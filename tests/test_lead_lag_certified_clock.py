from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting import lead_lag_shadow
from hl_observer.backtesting.lead_lag_certified_clock import (
    CERTIFIED_TIMESTAMP_POLICY,
    backtest_with_certified_wall_clock,
    certified_event_time_ns,
    certified_protocol_signature,
    load_certified_tape,
)


def test_monotonic_only_timestamp_is_not_certifiable() -> None:
    assert certified_event_time_ns({"recu_ns": 123456789}) is None


def test_wall_clock_is_certifiable_and_converted_to_ns() -> None:
    assert certified_event_time_ns({"ts_wall_ms": 1234.5, "recu_ns": 1}) == 1_234_500_000
    assert certified_event_time_ns({"recv_wall_ts_ms": 2}) == 2_000_000


def test_protocol_signature_ne_promet_plus_le_fallback_monotone() -> None:
    signature = certified_protocol_signature()
    assert signature["timestamp_clock"] == CERTIFIED_TIMESTAMP_POLICY
    assert signature["monotonic_only_rows_eligible_for_economic_proof"] is False
    assert signature["global_clock_monkeypatch"] is False
    assert "recu_ns_fallback" not in signature["timestamp_clock"]


def test_certified_loader_classifies_and_rejects_monotonic_only_rows(tmp_path: Path) -> None:
    tape = tmp_path / "runtime/data/bbo_tape.jsonl"
    tape.parent.mkdir(parents=True)
    tape.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {
                    "event_id": "hl-wall",
                    "venue": "HL",
                    "coin": "ETH",
                    "ts_wall_ms": 1000,
                    "recu_ns": 999999999,
                    "mid": 100.0,
                    "bid": 99.9,
                    "ask": 100.1,
                    "bid_sz": 2.0,
                    "ask_sz": 2.0,
                },
                {
                    "event_id": "trade-mono",
                    "venue": "BIN_TRADE",
                    "coin": "ETH",
                    "recu_ns": 1,
                    "px": 101.0,
                    "side": "BUY",
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )

    loaded, meta = load_certified_tape(tmp_path, return_meta=True)

    assert len(loaded["ETH"]["HL"]) == 1
    assert loaded["ETH"]["TRADE"] == []
    assert meta["uncertifiable_clock_rows"] == 1
    assert meta["timestamp_clock"] == CERTIFIED_TIMESTAMP_POLICY
    assert meta["monotonic_only_rows_eligible_for_economic_proof"] is False


def test_certified_backtest_does_not_mutate_global_clock_parser(tmp_path: Path) -> None:
    original = lead_lag_shadow._event_time_ns
    tape = tmp_path / "runtime/data/bbo_tape.jsonl"
    tape.parent.mkdir(parents=True)
    tape.write_text(
        json.dumps(
            {
                "venue": "BIN_TRADE",
                "coin": "ETH",
                "recu_ns": 123,
                "px": 101.0,
                "side": "BUY",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = backtest_with_certified_wall_clock(tmp_path)

    assert lead_lag_shadow._event_time_ns is original
    assert result["statut"] == "NEED_MORE_DATA"
    assert result["timestamp_certification"]["wall_clock_required"] is True
    assert result["timestamp_certification"]["monotonic_only_rows_rejected"] == 1
