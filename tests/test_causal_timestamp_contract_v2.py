from __future__ import annotations

import hashlib
import json

import pytest

from hl_observer.core.causal_time import (
    CausalTimestamp,
    causal_timestamp_from_record,
    compare_monotonic_within_connection,
    current_record_age_ms,
)
from hl_observer.experimental import signaux as signals
from hl_observer.normalization.market_events import canonicalize_tick_record


def _write_jsonl(path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows),
        encoding="utf-8",
    )


def _cross_snapshot(*, recv_hl: int, recv_bin: int, written: int) -> dict:
    return {
        "coin": "DOT",
        "hl_bid": 99.9,
        "hl_ask": 100.0,
        "bin_bid": 101.0,
        "bin_ask": 101.1,
        "taille_top_usd": 5_000.0,
        "recv_wall_hl_ms": recv_hl,
        "recv_wall_bin_ms": recv_bin,
        "write_wall_ts_ms": written,
        "ts_ms": written,
        "age_hl_ms": 1.0,
        "age_bin_ms": 1.0,
        "desync_ms": 1.0,
        "event_id": "pair-1",
    }


def _lead_lag_config(root) -> None:
    path = root / signals.CONFIG_GELE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "coins": ["SOL"],
                "coins_controle": [],
                "seuil_choc_bps": 8.0,
                "frais_slippage_bps": 6.0,
                "edge_net_par_horizon_bps": {"1000": 80.0},
                "freq_evenements_par_jour": 2.0,
            }
        ),
        encoding="utf-8",
    )


def test_current_age_recomputed_instead_of_reusing_persisted_age() -> None:
    record = {"recv_wall_ts_ms": 1_000, "age_ms": 1}
    assert current_record_age_ms(record, now_wall_ms=1_100) == 100
    assert current_record_age_ms(record, now_wall_ms=3_000) == 2_000
    assert current_record_age_ms({"age_ms": 1}, now_wall_ms=3_000) is None


def test_monotonic_clock_is_connection_local_and_not_restart_durable() -> None:
    before = CausalTimestamp(None, 1_000, 9_000, 1_001, connection_id="conn-a")
    after_restart = CausalTimestamp(
        None,
        2_000,
        10,
        2_001,
        connection_id="conn-b",
    )
    with pytest.raises(ValueError, match="across connections"):
        compare_monotonic_within_connection(before, after_restart)
    same_connection = CausalTimestamp(
        None,
        1_001,
        9_001,
        1_002,
        connection_id="conn-a",
    )
    assert compare_monotonic_within_connection(before, same_connection) == -1


def test_canonical_tick_aliases_preserve_connection_and_sequence() -> None:
    raw = '{"channel":"bbo","data":{"coin":"BTC"}}'
    record = {
        "schema_version": "hypersmart.tick.v1",
        "source_id": "hyperliquid_mainnet_readonly",
        "channel": "bbo",
        "instrument": "BTC",
        "event_kind": "SNAPSHOT",
        "exchange_ts_ms": 900,
        "recv_wall_ts_ms": 1_000,
        "write_wall_ts_ms": 1_010,
        "recv_mono_ns": 123,
        "connection_id": "hl-7",
        "sequence": 42,
        "raw_payload": raw,
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "parsed_summary": {
            "feed_quality_score": 99.0,
            "data_gate_ready": True,
        },
        "provenance": {"access": "read_only", "network": "mainnet"},
    }
    parsed = causal_timestamp_from_record(record)
    assert parsed.recv_wall_ts_ms == 1_000
    result = canonicalize_tick_record(record)
    assert result.accepted
    assert result.event is not None
    assert result.event.connection_id == "hl-7"
    assert result.event.sequence == 42
    assert result.event.recv_mono_ns == 123


def test_cross_venue_snapshot_becomes_stale_as_wall_time_advances(tmp_path) -> None:
    path = tmp_path / signals.SYNCHRO_RELPATH
    _write_jsonl(
        path,
        [_cross_snapshot(recv_hl=9_880, recv_bin=9_900, written=9_910)],
    )
    fresh, fresh_refusals = signals.signaux_cross_venue(tmp_path, now_ms=10_000)
    assert fresh
    assert not any(item["motif"] == "SNAPSHOT_PERIME_1S" for item in fresh_refusals)
    stale, stale_refusals = signals.signaux_cross_venue(tmp_path, now_ms=12_000)
    assert not stale
    assert any(item["motif"] == "SNAPSHOT_PERIME_1S" for item in stale_refusals)


def test_cross_venue_missing_wall_clock_is_refused_not_replaced_with_now(tmp_path) -> None:
    row = _cross_snapshot(recv_hl=9_880, recv_bin=9_900, written=9_910)
    row.pop("recv_wall_hl_ms")
    _write_jsonl(tmp_path / signals.SYNCHRO_RELPATH, [row])
    found, refusals = signals.signaux_cross_venue(tmp_path, now_ms=10_000)
    assert found == []
    assert any(item["motif"] == "TS_ABSENT" for item in refusals)


def test_lead_lag_uses_wall_clock_and_a_quote_observed_before_trade(tmp_path) -> None:
    _lead_lag_config(tmp_path)
    _write_jsonl(
        tmp_path / signals.TAPE_RELPATH,
        [
            {
                "coin": "SOL",
                "venue": "HL",
                "bid": 100.0,
                "ask": 100.02,
                "recu_ns": 9_999_999_999,
                "ts_wall_ms": 9_500,
                "event_id": "quote-before",
            },
            {
                "coin": "SOL",
                "venue": "BIN_TRADE",
                "px": 100.8,
                "side": "BUY",
                "recu_ns": 1,
                "ts_wall_ms": 9_600,
                "event_id": "trade",
            },
            {
                "coin": "SOL",
                "venue": "HL",
                "bid": 101.0,
                "ask": 101.02,
                "recu_ns": 2,
                "ts_wall_ms": 9_700,
                "event_id": "quote-after",
            },
        ],
    )
    found, refusals = signals.signaux_lead_lag(tmp_path, now_ms=10_000)
    assert found, refusals
    assert found[0].ts_signal_ms == 9_600
    assert found[0].meta["quote_event_id"] == "quote-before"
    assert found[0].meta["trade_event_id"] == "trade"


def test_lead_lag_monotonic_only_record_is_refused_after_restart(tmp_path) -> None:
    _lead_lag_config(tmp_path)
    _write_jsonl(
        tmp_path / signals.TAPE_RELPATH,
        [
            {
                "coin": "SOL",
                "venue": "HL",
                "bid": 100.0,
                "ask": 100.02,
                "recu_ns": 100,
            },
            {
                "coin": "SOL",
                "venue": "BIN_TRADE",
                "px": 100.8,
                "side": "BUY",
                "recu_ns": 200,
            },
        ],
    )
    found, refusals = signals.signaux_lead_lag(tmp_path, now_ms=10_000)
    assert found == []
    assert any(item["motif"] == "TS_ABSENT" for item in refusals)


@pytest.mark.parametrize("elapsed_ms", [0, 1, 10, 1_000, 60_000])
def test_current_age_is_monotone_with_wall_time(elapsed_ms: int) -> None:
    clock = CausalTimestamp(900, 1_000, 50, 1_010, connection_id="c")
    assert clock.current_age_ms(now_wall_ms=1_000 + elapsed_ms) == elapsed_ms
