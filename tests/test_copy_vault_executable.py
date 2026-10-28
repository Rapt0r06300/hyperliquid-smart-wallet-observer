from __future__ import annotations

import json
import math
from decimal import Decimal

import pytest

import hl_observer.backtesting.copy_vault_executable as copy_vault_executable
from hl_observer.backtesting.copy_vault_executable import (
    CHECKPOINT_COLLECTOR_PROTOCOL,
    COPY_DELAY_MS,
    HORIZONS_MS,
    MAX_TARGET_LAG_MS,
    calibrate_train_only,
    cluster_metaorders,
    evaluate_frozen,
    execute_metaorder,
    load_observed_books,
    protocol_signature,
    replay_metaorders,
    select_causal_protocol_inputs,
    select_observed_continuations,
    summarize,
    temporal_bounds,
    temporal_evidence,
)
from hl_observer.backtesting.copy_vault_protocol import INSTRUMENT_IDENTITY_SCHEMA
from hl_observer.economics.assumptions import EconomicConfigError, EconomicRunMode


def _entry(
    event_id: str,
    ts_ms: int,
    *,
    coin: str = "BTC",
    direction: int = 1,
    vault: str = "0xA",
    action: str = "ADD",
) -> dict:
    return {
        "event_id": event_id,
        "ts_ms": ts_ms,
        "coin": coin,
        "direction": direction,
        "action": action,
        "dir": "Open Long" if direction > 0 else "Open Short",
        "vault": vault,
        "taille_usd": 100.0,
        "move_frac": 0.01,
    }


def test_metaorders_refusent_les_sorties_et_les_contradictions_de_sens() -> None:
    open_one = _entry("open-one", 1_000, action="OPEN")
    add_one = _entry("add-one", 2_000)
    close = {
        **_entry("close", 3_000),
        "action": "CLOSE",
        "dir": "Close Long",
        "direction": 1,
    }
    reopen = _entry("reopen", 4_000, action="OPEN")
    contradiction = {
        **_entry("contradiction", 5_000, direction=-1),
        "dir": "Open Long",
    }

    metaorders, audit = cluster_metaorders(
        [open_one, add_one, close, reopen, contradiction], gap_ms=60_000
    )

    assert [row["fill_count"] for row in metaorders] == [2, 1]
    assert [row["member_event_ids"] for row in metaorders] == [
        ["open-one", "add-one"],
        ["reopen"],
    ]
    assert audit["non_entry_events_rejected"] == 1
    assert audit["action_direction_contradictions_rejected"] == 1


def test_metaorder_conserve_la_provenance_complete_des_fills_sources() -> None:
    event = {
        **_entry("safe-event", 1_000, action="OPEN"),
        "source": "LIVE_WS",
        "is_snapshot": False,
        "observed_at_ms": 1_010,
        "received_at_ms": 1_010,
        "source_dataset_id": "dataset-live-1",
        "source_shard_sha256": "a" * 64,
        "source_raw_sha256": "b" * 64,
        "source_catalog_sha256": "c" * 64,
        "source_quality_status": "SAFE",
        "source_manifest_verified": True,
        "source_replay_compatible": True,
    }

    metaorders, audit = cluster_metaorders([event])

    assert metaorders[0]["source_evidence_status"] == "COMPLETE"
    assert metaorders[0]["source_evidence_refs"] == [
        {
            "dataset_id": "dataset-live-1",
            "shard_sha256": "a" * 64,
            "raw_frame_sha256": "b" * 64,
            "source_catalog_sha256": "c" * 64,
            "quality": "SAFE",
            "manifest_verified": True,
            "replay_compatible": True,
            "event_id": "safe-event",
            "event_ts_ms": 1_000,
            "received_at_ms": 1_010,
            "source": "LIVE_WS",
            "forward_evidence_allowed": True,
        }
    ]
    assert metaorders[0]["member_events"][0]["source_dataset_id"] == "dataset-live-1"
    assert audit["source_evidence_missing_events"] == 0


def test_metaorder_without_shard_lineage_is_marked_incomplete() -> None:
    metaorders, audit = cluster_metaorders([_entry("legacy-event", 1_000, action="OPEN")])

    assert metaorders[0]["source_evidence_status"] == "INCOMPLETE"
    assert metaorders[0]["source_evidence_refs"] == []
    assert audit["source_evidence_missing_events"] == 1


def _book(
    ts_ms: int,
    bid: float,
    ask: float,
    *,
    capacity: float = 1_000.0,
    line: int = 1,
    causal: bool = False,
) -> dict:
    row = {
        "coin": "BTC",
        "ts_ms": ts_ms,
        "bid": bid,
        "ask": ask,
        "capacity_usd": capacity,
        "bids5": [[bid, capacity / bid]],
        "asks5": [[ask, capacity / ask]],
        "source_line": line,
        "causal_observation": causal,
    }
    if causal:
        row["connection_id"] = "fixture-causal-connection"
        row["l2_gap_epoch"] = 0
    return row


def test_metaorders_collapse_slices_even_when_other_coin_is_interleaved() -> None:
    entries = [
        _entry("a", 1_000),
        _entry("other", 20_000, coin="ETH"),
        _entry("b", 40_000),
        _entry("b", 40_000),
        _entry("c", 120_001),
    ]

    metaorders, audit = cluster_metaorders(entries, gap_ms=60_000)

    btc = [row for row in metaorders if row["coin"] == "BTC"]
    assert [row["fill_count"] for row in btc] == [2, 1]
    assert audit["duplicate_events_rejected"] == 1
    assert audit["sliced_fills_collapsed"] == 1


def test_metaorder_and_book_selection_preserve_native_coin_case() -> None:
    signal = {
        **_entry("native-kpepe", 2_000, coin="kPEPE", action="OPEN"),
        "source": "LIVE_WS",
        "is_snapshot": False,
        "observed_at_ms": 2_025,
    }
    metaorder = cluster_metaorders([signal])[0][0]
    book = {**_book(2_025, 0.0001, 0.0002, causal=True), "coin": "kPEPE"}

    selected, books, _audit = select_causal_protocol_inputs(
        [metaorder], {"kPEPE": [book], "KPEPE": [_book(2_025, 1.0, 2.0, causal=True)]}
    )

    assert metaorder["coin"] == "kPEPE"
    assert metaorder["metaorder_id"] == cluster_metaorders([signal])[0][0]["metaorder_id"]
    assert [row["coin"] for row in selected] == ["kPEPE"]
    assert list(books) == ["kPEPE"]


def test_observed_book_loader_does_not_case_fold_native_coin(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    row = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "kPEPE", "received_at_ms": 2_010, "exchange_ts_ms": 2_000,
        "bid": 0.0001, "ask": 0.0002, "capacity_usd": 10.0,
        "source": "HYPERLIQUID_L2_WS", "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
        "source_dataset_id": "safe-kpepe-l2",
        "source_shard_sha256": "a" * 64,
        "source_raw_sha256": "b" * 64,
        "source_catalog_sha256": "c" * 64,
        "source_quality_status": "SAFE",
        "source_manifest_verified": True,
        "source_replay_compatible": True,
    }
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    books, _audit = load_observed_books(tmp_path, coins={"kPEPE"})

    assert list(books) == ["kPEPE"]
    assert books["kPEPE"][0]["source_dataset_id"] == "safe-kpepe-l2"
    assert books["kPEPE"][0]["source_shard_sha256"] == "a" * 64
    assert books["kPEPE"][0]["source_raw_sha256"] == "b" * 64
    assert books["kPEPE"][0]["source_evidence_status"] == "STRUCTURALLY_COMPLETE"
    assert books["kPEPE"][0]["source_catalog_sha256"] == "c" * 64
    assert books["kPEPE"][0]["source_quality_status"] == "SAFE"
    assert books["kPEPE"][0]["source_manifest_verified"] is True
    assert books["kPEPE"][0]["source_replay_compatible"] is True
    assert load_observed_books(tmp_path, coins={"KPEPE"})[0] == {}


def test_metaorder_id_ne_change_pas_quand_une_slice_future_arrive() -> None:
    first = _entry("first", 1_000, action="OPEN")
    future_add = _entry("future-add", 2_000, action="ADD")

    initial = cluster_metaorders([first])[0][0]
    enriched = cluster_metaorders([first, future_add])[0][0]

    assert initial["metaorder_id"] == enriched["metaorder_id"]
    assert initial["first_event_id"] == enriched["first_event_id"] == "first"


def test_portfolio_exposure_uses_decimal_before_comparing_the_paper_cap(monkeypatch) -> None:
    trades = {
        "first": {
            "trade_id": "trade-first", "entry_ts_ms": 10, "exit_ts_ms": 100,
            "notional_usd": 100.00000000000001,
        },
        "second": {
            "trade_id": "trade-second", "entry_ts_ms": 20, "exit_ts_ms": 200,
            "notional_usd": 100.0,
        },
    }

    def fake_execute(metaorder, _books, **_kwargs):
        return trades[metaorder["id"]].copy(), "LIQUIDATABLE_NET"

    monkeypatch.setattr(copy_vault_executable, "execute_metaorder", fake_execute)
    metaorders = [
        {"id": "first", "signal_ts_ms": 1, "entry_ts_ms": 10, "coin": "BTC"},
        {"id": "second", "signal_ts_ms": 2, "entry_ts_ms": 20, "coin": "ETH"},
    ]

    accepted, counters = replay_metaorders(
        metaorders, {}, horizon_ms=1_000
    )

    assert [trade["trade_id"] for trade in accepted] == ["trade-first"]
    assert counters["capital_margin_rejected"] == 1

    trades["first"]["notional_usd"] = 100.0
    accepted_at_limit, exact_limit_counters = replay_metaorders(
        metaorders, {}, horizon_ms=1_000
    )
    assert [trade["trade_id"] for trade in accepted_at_limit] == [
        "trade-first", "trade-second",
    ]
    assert exact_limit_counters["capital_margin_rejected"] == 0


def test_continuation_attend_trois_fills_observes_sans_regarder_le_futur() -> None:
    def live(event_id: str, ts_ms: int, action: str) -> dict:
        return {
            **_entry(event_id, ts_ms, action=action),
            "source": "LIVE_WS",
            "is_snapshot": False,
            "observed_at_ms": ts_ms + 25,
            "received_at_ms": ts_ms + 25,
            "source_dataset_id": f"dataset-{event_id}",
            "source_shard_sha256": "a" * 64,
            "source_raw_sha256": "b" * 64,
            "source_catalog_sha256": "c" * 64,
            "source_quality_status": "SAFE",
            "source_manifest_verified": True,
            "source_replay_compatible": True,
        }

    prefix = [
        live("first", 1_000, "OPEN"),
        live("second", 2_000, "ADD"),
        live("third", 3_000, "ADD"),
    ]
    initial = cluster_metaorders(prefix)[0]
    enriched = cluster_metaorders(prefix + [live("future", 4_000, "ADD")])[0]
    selected_initial, audit = select_observed_continuations(initial)
    selected_enriched, _ = select_observed_continuations(enriched)

    assert audit["selected_continuations"] == 1
    assert selected_initial[0]["signal_ts_ms"] == 3_025
    assert selected_initial[0]["confirmation_event_id"] == "third"
    assert selected_initial[0]["member_event_ids_at_signal"] == ["first", "second", "third"]
    assert selected_initial[0]["leader_notional_usd_at_signal"] == 300.0
    assert selected_initial[0]["confirmation_burst_ms"] == 2_000
    assert selected_enriched[0]["metaorder_id"] == selected_initial[0]["metaorder_id"]
    assert selected_enriched[0]["leader_notional_usd_at_signal"] == 300.0
    assert selected_enriched[0]["confirmation_burst_ms"] == 2_000


def test_execution_propage_uniquement_les_features_connues_au_signal() -> None:
    def live(event_id: str, ts_ms: int, action: str) -> dict:
        return {
            **_entry(event_id, ts_ms, action=action),
            "source": "LIVE_WS",
            "is_snapshot": False,
            "observed_at_ms": ts_ms + 25,
            "received_at_ms": ts_ms + 25,
            "source_dataset_id": f"dataset-{event_id}",
            "source_shard_sha256": "a" * 64,
            "source_raw_sha256": "b" * 64,
            "source_catalog_sha256": "c" * 64,
            "source_quality_status": "SAFE",
            "source_manifest_verified": True,
            "source_replay_compatible": True,
        }

    metaorders = cluster_metaorders(
        [
            live("first", 1_000, "OPEN"),
            live("second", 2_000, "ADD"),
            live("future", 9_000, "ADD"),
        ]
    )[0]
    selected, _audit = select_observed_continuations(
        metaorders, required_observed_fills=2
    )
    signal_ms = selected[0]["signal_ts_ms"]
    books = [
        {
            **_book(ts_ms, bid, ask, causal=True),
            "source_dataset_id": "safe-l2-dataset",
            "source_shard_sha256": "a" * 64,
            "source_raw_sha256": "b" * 64,
            "source_catalog_sha256": "c" * 64,
            "source_quality_status": "SAFE",
            "source_manifest_verified": True,
            "source_replay_compatible": True,
            "exchange_ts_ms": ts_ms,
            "received_at_ms": ts_ms,
        }
        for ts_ms, bid, ask in (
            (signal_ms, 99.0, 101.0),
            (signal_ms + COPY_DELAY_MS, 100.0, 102.0),
            (signal_ms + COPY_DELAY_MS + 300_000, 109.0, 111.0),
        )
    ]

    trade, reason = execute_metaorder(selected[0], books, horizon_ms=300_000)

    assert reason == "LIQUIDATABLE_NET"
    assert trade is not None
    assert trade["confirmation_fill_count"] == 2
    assert trade["leader_notional_usd_at_signal"] == 200.0
    assert trade["confirmation_burst_ms"] == 1_000
    assert trade["member_event_ids_at_signal"] == ["first", "second"]
    assert trade["leader_id"] == "0xA"
    assert trade["leader_fill_evidence_status"] == "SAFE_CAUSAL_COMPLETE"
    assert trade["leader_fill_evidence_missing_count"] == 0
    assert trade["execution_book_safe_evidence_status"] == "SAFE_CAUSAL_COMPLETE"
    assert trade["execution_book_unverified_count"] == 0
    assert [row["event_id"] for row in trade["leader_fill_evidence_refs"]] == [
        "first", "second",
    ]
    assert all(row["received_at_ms"] <= trade["signal_ts_ms"] for row in trade["leader_fill_evidence_refs"])
    assert trade["execution_book_evidence_status"] == "STRUCTURALLY_COMPLETE"
    assert [row["role"] for row in trade["execution_book_evidence_refs"]] == [
        "REFERENCE", "ENTRY", "EXIT",
    ]
    assert all(
        row["dataset_id"] == "safe-l2-dataset"
        and row["shard_sha256"] == "a" * 64
        and row["raw_frame_sha256"] == "b" * 64
        for row in trade["execution_book_evidence_refs"]
    )


def test_execution_reference_book_ne_peut_pas_etre_postérieur_au_signal() -> None:
    metaorder = cluster_metaorders([_entry("asof", 1_000)])[0][0]
    books = [
        _book(990, 99.0, 101.0, line=1),
        _book(1_001, 90.0, 92.0, line=2),
        _book(61_000, 100.0, 102.0, line=3),
        _book(361_000, 109.0, 111.0, line=4),
    ]

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert reason == "LIQUIDATABLE_NET"
    assert trade is not None
    assert trade["reference_ts_ms"] == 990


def test_continuation_refuse_un_prefix_historique_ou_non_monotone() -> None:
    rows = [
        {
            **_entry("first", 1_000, action="OPEN"),
            "source": "LIVE_WS", "is_snapshot": False, "observed_at_ms": 1_025,
        },
        _entry("history", 2_000, action="ADD"),
        {
            **_entry("third", 3_000, action="ADD"),
            "source": "LIVE_WS", "is_snapshot": False, "observed_at_ms": 3_025,
        },
    ]
    selected, audit = select_observed_continuations(cluster_metaorders(rows)[0])

    assert selected == []
    assert audit["noncausal_prefix_rejected"] == 1


def test_metaorder_live_emploie_reception_locale_et_backfill_ne_prouve_pas_forward() -> None:
    live = {
        **_entry("live", 1_000),
        "source": "LIVE_WS",
        "is_snapshot": False,
        "observed_at_ms": 1_025,
    }
    history = _entry("history", 2_000)
    metaorders, audit = cluster_metaorders([live, history], gap_ms=1)

    by_id = {row["member_event_ids"][0]: row for row in metaorders}
    assert by_id["live"]["signal_ts_ms"] == 1_025
    assert by_id["live"]["causal_forward_eligible"] is True
    assert by_id["history"]["causal_forward_eligible"] is False
    assert audit["causal_forward_metaorders"] == 1

    books = {
        "BTC": [
            _book(1_025, 99.0, 101.0, line=1, causal=True),
            _book(61_025, 100.0, 102.0, line=2, causal=True),
            _book(361_025, 109.0, 111.0, line=3, causal=True),
            _book(2_000, 99.0, 101.0, line=4),
            _book(62_000, 100.0, 102.0, line=5),
            _book(362_000, 109.0, 111.0, line=6),
        ]
    }
    books["BTC"].sort(key=lambda row: row["ts_ms"])
    trades, diagnostics = replay_metaorders(
        metaorders,
        books,
        horizon_ms=300_000,
        require_causal_observation=True,
    )

    assert len(trades) == 1 and trades[0]["signal_source"] == "LIVE_WS"
    assert diagnostics["NON_CAUSAL_FORWARD_SIGNAL"] == 1


def test_forward_refuse_un_carnet_non_causal() -> None:
    entry = {
        **_entry("live", 1_000),
        "source": "LIVE_WS",
        "is_snapshot": False,
        "observed_at_ms": 1_025,
    }
    metaorder = cluster_metaorders([entry])[0][0]
    books = [
        _book(1_025, 99.0, 101.0),
        _book(61_025, 100.0, 102.0),
        _book(361_025, 109.0, 111.0),
    ]

    trades, diagnostics = replay_metaorders(
        [metaorder], {"BTC": books}, horizon_ms=300_000,
        require_causal_observation=True,
    )

    assert trades == []
    assert diagnostics["NON_CAUSAL_FORWARD_BOOK"] == 1


def test_loader_separe_historique_et_tape_ws_causale(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "carnet_venues.jsonl").write_text(json.dumps({
        "coin": "BTC", "collecte_ts": 1.0, "hl_bid": 99.0,
        "hl_ask": 101.0, "taille_min_usd": 500.0,
    }) + "\n", encoding="utf-8")
    causal = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "BTC", "received_at_ms": 2_010, "exchange_ts_ms": 2_000,
        "bid": 100.0, "ask": 102.0, "capacity_usd": 700.0,
        "source": "HYPERLIQUID_L2_WS", "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
    }
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(causal) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert [row["causal_observation"] for row in books["BTC"]] == [False, True]
    assert books["BTC"][1]["ts_ms"] == 2_010
    assert books["BTC"][0]["source_timestamp_raw"] == "1.0"
    assert books["BTC"][0]["source_timestamp_unit"] == "s_since_unix_epoch_utc"
    assert books["BTC"][0]["timestamp_unit"] == "ms_since_unix_epoch"
    assert books["BTC"][1]["exchange_ts_ms"] == 2_000
    assert books["BTC"][1]["received_at_ms"] == 2_010
    assert audit["source_counts"] == {
        "historical_observed": 1,
        "causal_ws": 1,
        "causal_info_checkpoint": 0,
    }


def test_l2_tape_gap_epoch_survives_loader_and_blocks_forward_replay(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    books = [
        {
            "schema_version": "hypersmart.copy_vault_l2.v1",
            "coin": "BTC",
            "received_at_ms": ts_ms,
            "exchange_ts_ms": ts_ms - 10,
            "bid": bid,
            "ask": ask,
            "capacity_usd": 1_000.0,
            "source": "HYPERLIQUID_L2_WS",
            "data_origin": "REAL_OBSERVED",
            "causal_observation": True,
            "connection_id": "connection-a",
            "l2_gap_epoch": gap_epoch,
        }
        for ts_ms, bid, ask, gap_epoch in zip(
            (1_000, 61_000, 361_000),
            (99.0, 100.0, 109.0),
            (101.0, 102.0, 111.0),
            (0, 1, 1),
            strict=True,
        )
    ]
    (data / "copy_vault_l2_tape.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in books),
        encoding="utf-8",
    )
    metaorder = cluster_metaorders([
        {
            **_entry("forward-gap", 1_000),
            "source": "LIVE_WS",
            "is_snapshot": False,
            "observed_at_ms": 1_000,
        }
    ])[0][0]

    loaded_books, _audit = load_observed_books(tmp_path, coins={"BTC"})
    trades, diagnostics = replay_metaorders(
        [metaorder],
        loaded_books,
        horizon_ms=300_000,
        require_causal_observation=True,
    )

    assert [row["l2_gap_epoch"] for row in loaded_books["BTC"]] == [0, 1, 1]
    assert trades == []
    assert diagnostics["L2_GAP_EPOCH_CROSSED"] == 1


def test_historical_loader_floors_fractional_epoch_seconds_at_utc_midnight(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    row = {
        "coin": "BTC", "collecte_ts": 1_793_145_600.0009,
        "hl_bid": 99.0, "hl_ask": 101.0, "taille_min_usd": 500.0,
    }
    (data / "carnet_venues.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert books["BTC"][0]["ts_ms"] == 1_793_145_600_000
    assert books["BTC"][0]["source_timestamp_raw"] == "1793145600.0009"
    assert audit["invalid_rows"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("received_at_ms", 2_010.5),
        ("exchange_ts_ms", 2_000.5),
        ("received_at_ms", "2010"),
        ("exchange_ts_ms", "2000"),
        ("received_at_ms", 1_700_000_000_000_000_000),
        ("exchange_ts_ms", 1_700_000_000_000_000_000),
    ],
)
def test_causal_loader_rejects_fractional_string_or_nanosecond_timestamps(
    tmp_path, field, value
) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    row = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "BTC", "received_at_ms": 2_010, "exchange_ts_ms": 2_000,
        "bid": 100.0, "ask": 102.0, "capacity_usd": 700.0,
        "source": "HYPERLIQUID_L2_WS", "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
    }
    row[field] = value
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert books == {}
    assert audit["invalid_rows"] == 1


def test_causal_loader_rejects_source_receive_drift_beyond_causal_tolerance(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    row = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "BTC", "received_at_ms": 32_001, "exchange_ts_ms": 2_000,
        "bid": 100.0, "ask": 102.0, "capacity_usd": 700.0,
        "source": "HYPERLIQUID_L2_WS", "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
    }
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert books == {}
    assert audit["invalid_rows"] == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [("hl_bid", float("nan")), ("hl_ask", float("inf")),
     ("taille_min_usd", float("nan")), ("hl_bid", True)],
)
def test_loader_refuse_un_top_historique_non_fini(tmp_path, field, value) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    row = {
        "coin": "BTC", "collecte_ts": 1.0, "hl_bid": 99.0,
        "hl_ask": 101.0, "taille_min_usd": 500.0,
    }
    row[field] = value
    (data / "carnet_venues.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert books == {}
    assert audit["invalid_rows"] == 1


def test_loader_refuse_un_carnet_causal_dont_la_profondeur_est_non_finie(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    row = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "BTC", "received_at_ms": 2_010, "exchange_ts_ms": 2_000,
        "bid": 100.0, "ask": 102.0, "capacity_usd": 700.0,
        "bids5": [[100.0, float("nan")]],
        "asks5": [[102.0, 2.0]],
        "source": "HYPERLIQUID_L2_WS", "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
    }
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert books == {}
    assert audit["invalid_rows"] == 1


def test_loader_refuse_un_booleen_comme_niveau_l2(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    row = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "BTC", "received_at_ms": 2_010, "exchange_ts_ms": 2_000,
        "bid": 100.0, "ask": 102.0, "capacity_usd": 700.0,
        "bids5": [[100.0, True]], "asks5": [[102.0, 2.0]],
        "source": "HYPERLIQUID_L2_WS", "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
    }
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert books == {}
    assert audit["invalid_rows"] == 1


def test_loader_refuse_un_carnet_causal_avec_un_seul_cote_l2(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    row = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "BTC", "received_at_ms": 2_010, "exchange_ts_ms": 2_000,
        "bid": 100.0, "ask": 102.0, "capacity_usd": 700.0,
        "bids5": [[100.0, 2.0]],
        "source": "HYPERLIQUID_L2_WS", "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
    }
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert books == {}
    assert audit["invalid_rows"] == 1


@pytest.mark.parametrize(
    ("bid", "ask", "bids", "asks", "reason"),
    [
        (100.0, 102.0, [[99.0, 1.0], [100.0, 2.0]], [[102.0, 1.0]],
         "L2_BIDS_INVALID_ORDER_OR_VALUE"),
        (100.0, 103.0, [[100.0, 1.0]], [[103.0, 1.0], [102.0, 2.0]],
         "L2_ASKS_INVALID_ORDER_OR_VALUE"),
        (100.0, 102.0, [[100.0, 1.0], [100.0, 2.0]], [[102.0, 1.0]],
         "L2_BIDS_INVALID_ORDER_OR_VALUE"),
        (100.0, 102.0, [[100.0, 1.0]], [[102.0, 1.0], [102.0, 2.0]],
         "L2_ASKS_INVALID_ORDER_OR_VALUE"),
        (99.0, 102.0, [[100.0, 1.0]], [[102.0, 1.0]], "L2_BBO_MISMATCH"),
        (100.0, 103.0, [[100.0, 1.0]], [[102.0, 1.0]], "L2_BBO_MISMATCH"),
        (100.0, 102.0, [[100.0, 1.0]], [[99.0, 1.0]], "L2_BOOK_CROSSED"),
    ],
)
def test_loader_quarantaine_un_carnet_causal_l2_incoherent(
    tmp_path, bid, ask, bids, asks, reason
) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    row = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "BTC", "received_at_ms": 2_010, "exchange_ts_ms": 2_000,
        "bid": bid, "ask": ask, "capacity_usd": 700.0,
        "bids5": bids, "asks5": asks,
        "source": "HYPERLIQUID_L2_WS", "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
    }
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert books == {}
    assert audit["invalid_rows"] == 1
    assert audit["invalid_l2_structure_rows"] == 1
    assert audit["l2_rejection_reasons"] == {reason: 1}
    metaorder = cluster_metaorders([_entry("invalid-l2", 2_010)])[0][0]
    trades, replay_audit = replay_metaorders(
        [metaorder], books, horizon_ms=300_000
    )
    assert trades == []
    assert replay_audit["NO_OBSERVED_BOOK_FOR_COIN"] == 1


def test_loader_accepte_checkpoint_info_causal_frais(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    row = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "BTC", "received_at_ms": 2_010, "exchange_ts_ms": 2_000,
        "bid": 100.0, "ask": 102.0, "capacity_usd": 700.0,
        "bids5": [[100.0, 2.0], [99.0, 5.0]],
        "asks5": [[102.0, 2.0], [103.0, 5.0]],
        "source": "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT",
        "data_origin": "REAL_OBSERVED", "causal_observation": True,
        "checkpoint_stage": "ENTRY", "checkpoint_target_ms": 2_005,
        "checkpoint_id": "mo-1:ENTRY", "metaorder_id": "mo-1",
        "collector_protocol": CHECKPOINT_COLLECTOR_PROTOCOL,
        "instrument_identity_schema": INSTRUMENT_IDENTITY_SCHEMA,
    }
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert books["BTC"][0]["source"] == "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT"
    assert books["BTC"][0]["bids5"] == [[100.0, 2.0], [99.0, 5.0]]
    assert books["BTC"][0]["asks5"] == [[102.0, 2.0], [103.0, 5.0]]
    assert audit["source_counts"]["causal_info_checkpoint"] == 1
    assert audit["causal_forward_rows"] == 1


def test_execution_refuse_un_l2_invalide_au_lieu_du_repli_bbo() -> None:
    signal_ms = 1_000
    metaorder = cluster_metaorders([_entry("bad-depth", signal_ms)])[0][0]
    books = [
        _book(signal_ms - 100, 99.0, 101.0),
        _book(signal_ms + COPY_DELAY_MS, 100.0, 102.0, line=2),
        _book(signal_ms + COPY_DELAY_MS + 300_000, 101.0, 103.0, line=3),
    ]
    books[1]["bids5"] = [[99.0, 2.0], [100.0, 1.0]]

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert trade is None
    assert reason == "INVALID_OBSERVED_BOOK_L2"


def test_loader_quarantaine_tout_metaordre_avec_checkpoint_duplique(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)

    def checkpoint(
        metaorder_id: str,
        stage: str,
        checkpoint_id: str,
        received_at_ms: int,
    ) -> dict:
        return {
            "schema_version": "hypersmart.copy_vault_l2.v1",
            "coin": "BTC",
            "received_at_ms": received_at_ms,
            "exchange_ts_ms": received_at_ms - 10,
            "bid": 100.0,
            "ask": 102.0,
            "capacity_usd": 700.0,
            "source": "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT",
            "data_origin": "REAL_OBSERVED",
            "causal_observation": True,
            "checkpoint_stage": stage,
            "checkpoint_target_ms": received_at_ms - 5,
            "checkpoint_id": checkpoint_id,
            "metaorder_id": metaorder_id,
            "collector_protocol": CHECKPOINT_COLLECTOR_PROTOCOL,
            "instrument_identity_schema": INSTRUMENT_IDENTITY_SCHEMA,
        }

    rows = [
        checkpoint("mo-bad", "REFERENCE", "mo-bad:REFERENCE", 2_010),
        checkpoint("mo-bad", "ENTRY", "mo-bad:ENTRY", 2_020),
        checkpoint("mo-bad", "ENTRY", "mo-bad:ENTRY", 2_030),
        checkpoint("mo-good", "ENTRY", "mo-good:ENTRY", 2_040),
    ]
    (data / "copy_vault_l2_tape.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert [row["metaorder_id"] for row in books["BTC"]] == ["mo-good"]
    assert audit["duplicate_checkpoint_ids"] == 1
    assert audit["duplicate_checkpoint_rows"] == 1
    assert audit["quarantined_checkpoint_metaorders"] == 1
    assert audit["quarantined_checkpoint_rows"] == 3


def test_loader_quarantaine_chaque_metaordre_partageant_un_checkpoint_id(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)

    def checkpoint(metaorder_id: str, checkpoint_id: str, received_at_ms: int) -> dict:
        return {
            "schema_version": "hypersmart.copy_vault_l2.v1",
            "coin": "BTC",
            "received_at_ms": received_at_ms,
            "exchange_ts_ms": received_at_ms - 10,
            "bid": 100.0,
            "ask": 102.0,
            "capacity_usd": 700.0,
            "source": "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT",
            "data_origin": "REAL_OBSERVED",
            "causal_observation": True,
            "checkpoint_stage": "ENTRY",
            "checkpoint_target_ms": received_at_ms - 5,
            "checkpoint_id": checkpoint_id,
            "metaorder_id": metaorder_id,
            "collector_protocol": CHECKPOINT_COLLECTOR_PROTOCOL,
            "instrument_identity_schema": INSTRUMENT_IDENTITY_SCHEMA,
        }

    rows = [
        checkpoint("mo-a", "shared:ENTRY", 2_010),
        checkpoint("mo-b", "shared:ENTRY", 2_020),
        checkpoint("mo-good", "mo-good:ENTRY", 2_030),
    ]
    (data / "copy_vault_l2_tape.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert [row["metaorder_id"] for row in books["BTC"]] == ["mo-good"]
    assert audit["duplicate_checkpoint_ids"] == 1
    assert audit["duplicate_checkpoint_rows"] == 1
    assert audit["quarantined_checkpoint_metaorders"] == 2
    assert audit["quarantined_checkpoint_rows"] == 2


def test_loader_refuse_checkpoint_ancien_protocole(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    row = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "BTC", "received_at_ms": 2_010, "exchange_ts_ms": 2_000,
        "bid": 100.0, "ask": 102.0, "capacity_usd": 700.0,
        "source": "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT",
        "data_origin": "REAL_OBSERVED", "causal_observation": True,
        "checkpoint_stage": "ENTRY", "checkpoint_target_ms": 2_005,
        "checkpoint_id": "mo-1:ENTRY", "metaorder_id": "mo-1",
        "collector_protocol": "copy_vault_checkpoint_companion_v1_obsolete",
    }
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert books == {}
    assert audit["checkpoint_protocol_mismatches_rejected"] == 1


def test_loader_refuse_checkpoint_info_dont_horloge_est_trop_vieille(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    row = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "BTC", "received_at_ms": 50_001, "exchange_ts_ms": 1,
        "bid": 100.0, "ask": 102.0, "capacity_usd": 700.0,
        "source": "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT",
        "data_origin": "REAL_OBSERVED", "causal_observation": True,
    }
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert books == {}
    assert audit["invalid_rows"] == 1


def test_protocol_inputs_excluent_backfill_et_carnet_non_causal() -> None:
    historical = cluster_metaorders([_entry("history", 1_000)])[0][0]
    live = cluster_metaorders([{
        **_entry("live", 2_000),
        "source": "LIVE_WS",
        "is_snapshot": False,
        "observed_at_ms": 2_025,
    }])[0][0]
    books = {
        "BTC": [
            _book(1_000, 99.0, 101.0),
            _book(2_025, 100.0, 102.0, causal=True),
        ],
        "ETH": [_book(3_000, 10.0, 11.0, causal=True)],
    }

    metaorders, causal_books, audit = select_causal_protocol_inputs(
        [historical, live], books
    )

    assert [row["metaorder_id"] for row in metaorders] == [live["metaorder_id"]]
    assert list(causal_books) == ["BTC"]
    assert len(causal_books["BTC"]) == 1
    assert audit["causal_protocol_metaorders"] == 1
    assert audit["historical_or_noncausal_metaorders_excluded"] == 1
    assert audit["causal_protocol_book_rows"] == 1
    assert audit["historical_or_noncausal_book_rows_excluded"] == 2


def test_calibration_causale_refuse_un_signal_historique() -> None:
    historical = cluster_metaorders([
        _entry(f"history-{index}", 1_000 + index * 4_000_000)
        for index in range(12)
    ])[0]
    books = {
        "BTC": [
            _book(1_000, 99.0, 101.0, causal=True),
            _book(61_000, 100.0, 102.0, causal=True),
            _book(361_000, 109.0, 111.0, causal=True),
        ]
    }

    result = calibrate_train_only(
        historical,
        books,
        require_causal_observation=True,
    )

    assert result["selection_eligible"] is False
    assert result["causal_observation_required"] is True
    assert all(
        row["diagnostics"].get("NON_CAUSAL_FORWARD_SIGNAL", 0) > 0
        for row in result["grid"]
    )


def test_calibration_ne_traite_pas_un_hit_rate_float_arrondi_comme_tous_gagnants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade_count = 1 << 54
    winning_trade_count = trade_count - 1
    assert winning_trade_count / trade_count == 1.0

    fake_summary = {
        "positions_fermees": trade_count,
        "winning_trade_count": winning_trade_count,
        "hit_rate": 1.0,
        "profit_factor": None,
        "profit_factor_exact_decimal": None,
        "net_pnl_usd_exact_decimal": "1",
        "LIQUIDATABLE_NET": True,
        "economic_reconciliation_ok": True,
    }
    monkeypatch.setattr(
        copy_vault_executable,
        "replay_metaorders",
        lambda *args, **kwargs: ([], {}),
    )
    monkeypatch.setattr(
        copy_vault_executable,
        "summarize",
        lambda _trades: dict(fake_summary),
    )

    result = calibrate_train_only(
        [{"signal_ts_ms": timestamp} for timestamp in (1, 2, 3)],
        {"BTC": []},
    )

    assert result["selection_eligible"] is False
    assert all(
        row["economic_gate"]["all_wins_without_loss_denominator"] is False
        for row in result["grid"]
    )


def test_stale_reference_is_refused_instead_of_using_future_price() -> None:
    metaorder = cluster_metaorders([_entry("a", 1_000)])[0][0]
    books = [_book(40_001, 99.0, 101.0)]

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert trade is None
    assert reason == "STALE_OR_MISSING_REFERENCE_BOOK"


@pytest.mark.parametrize(
    ("connection_ids", "gap_epochs", "expected_reason"),
    [
        (["ws-a", "ws-b", "ws-b"], [0, 1, 1], "L2_CONNECTION_GAP_CROSSED"),
        (["ws-a", "ws-a", "ws-a"], [0, 1, 1], "L2_GAP_EPOCH_CROSSED"),
        (["ws-a", "ws-a", "ws-a"], [0, None, 1], "L2_GAP_EPOCH_IDENTITY_INCOMPLETE"),
    ],
)
def test_replay_refuses_book_triplets_crossing_observed_l2_gaps(
    connection_ids: list[str],
    gap_epochs: list[int | None],
    expected_reason: str,
) -> None:
    metaorder = cluster_metaorders([_entry("gap-crossing", 1_000)])[0][0]
    books = [
        {
            **_book(ts_ms, bid, ask),
            "connection_id": connection_id,
            "l2_gap_epoch": gap_epoch,
        }
        for ts_ms, bid, ask, connection_id, gap_epoch in zip(
            (1_000, 61_000, 361_000),
            (99.0, 100.0, 109.0),
            (101.0, 102.0, 111.0),
            connection_ids,
            gap_epochs,
            strict=True,
        )
    ]

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert trade is None
    assert reason == expected_reason


@pytest.mark.parametrize(
    ("identity_field", "expected_reason"),
    [
        ("connection_id", "L2_CONNECTION_IDENTITY_INCOMPLETE"),
        ("l2_gap_epoch", "L2_GAP_EPOCH_IDENTITY_INCOMPLETE"),
    ],
)
def test_causal_replay_refuses_missing_l2_gap_identity_instead_of_assuming_no_gap(
    identity_field: str,
    expected_reason: str,
) -> None:
    metaorder = cluster_metaorders([_entry("missing-gap-identity", 1_000)])[0][0]
    books = [
        {**_book(ts_ms, bid, ask), "causal_observation": True}
        for ts_ms, bid, ask in zip(
            (1_000, 61_000, 361_000),
            (99.0, 100.0, 109.0),
            (101.0, 102.0, 111.0),
            strict=True,
        )
    ]
    if identity_field == "l2_gap_epoch":
        for row in books:
            row["connection_id"] = "same-connection"

    trade, reason = execute_metaorder(
        metaorder,
        books,
        horizon_ms=300_000,
        require_causal_books=True,
    )

    assert trade is None
    assert reason == expected_reason


def test_causal_replay_accepts_complete_same_connection_gap_epoch_identity() -> None:
    metaorder = cluster_metaorders([_entry("complete-gap-identity", 1_000)])[0][0]
    books = [
        {
            **_book(ts_ms, bid, ask),
            "causal_observation": True,
            "connection_id": "same-connection",
            "l2_gap_epoch": 0,
        }
        for ts_ms, bid, ask in zip(
            (1_000, 61_000, 361_000),
            (99.0, 100.0, 109.0),
            (101.0, 102.0, 111.0),
            strict=True,
        )
    ]

    trade, reason = execute_metaorder(
        metaorder,
        books,
        horizon_ms=300_000,
        require_causal_books=True,
    )

    assert reason == "LIQUIDATABLE_NET"
    assert trade is not None


def test_forward_replay_quarantines_causal_window_with_missing_gap_receipt() -> None:
    metaorder = cluster_metaorders([_entry("missing-gap-receipt", 1_000)])[0][0]
    metaorder["causal_forward_eligible"] = True
    books = [
        {**_book(ts_ms, bid, ask), "causal_observation": True}
        for ts_ms, bid, ask in zip(
            (1_000, 61_000, 361_000),
            (99.0, 100.0, 109.0),
            (101.0, 102.0, 111.0),
            strict=True,
        )
    ]

    trades, diagnostics = replay_metaorders(
        [metaorder],
        {"BTC": books},
        horizon_ms=300_000,
        require_causal_observation=True,
    )

    assert trades == []
    assert diagnostics["completed_positions"] == 0
    assert diagnostics["L2_CONNECTION_IDENTITY_INCOMPLETE"] == 1


def test_unsorted_continuous_books_are_rejected_before_replay() -> None:
    metaorder = cluster_metaorders([_entry("unsorted", 1_000)])[0][0]
    books = [
        _book(61_000, 100.0, 102.0, line=1),
        _book(990, 99.0, 101.0, line=2),
        _book(361_000, 109.0, 111.0, line=3),
    ]

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert trade is None
    assert reason == "UNSORTED_BOOK_TIMESTAMPS"


@pytest.mark.parametrize(
    ("book_index", "field", "value"),
    [(0, "bid", float("nan")), (1, "ask", float("inf")),
     (2, "capacity_usd", float("nan")), (2, "capacity_usd", -1.0),
     (0, "bid", True)],
)
def test_executeur_refuse_un_top_selectionne_non_economique(
    book_index, field, value
) -> None:
    metaorder = cluster_metaorders([_entry("invalid-book", 1_000)])[0][0]
    books = [
        _book(1_000, 99.0, 101.0),
        _book(61_000, 100.0, 102.0),
        _book(361_000, 109.0, 111.0),
    ]
    books[book_index][field] = value

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert trade is None
    assert reason == "INVALID_OBSERVED_BOOK"


def test_execution_refuse_une_position_traversant_un_funding_non_mesure() -> None:
    signal_ms = 3_500_000
    metaorder = cluster_metaorders([_entry("funding-gap", signal_ms)])[0][0]
    books = [
        _book(signal_ms - 10, 99.0, 101.0, line=1),
        _book(signal_ms + COPY_DELAY_MS, 100.0, 102.0, line=2),
        _book(signal_ms + COPY_DELAY_MS + 300_000, 109.0, 111.0, line=3),
    ]

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert trade is None
    assert reason == "FUNDING_BOUNDARY_UNPRICED"


def test_execution_refuse_entree_exactement_a_la_frontiere_de_funding() -> None:
    # La position entre au timestamp de règlement; l'ordre relatif fill/règlement
    # n'est pas prouvé par les timestamps seuls, donc le replay doit refuser.
    signal_ms = 3_540_000
    metaorder = cluster_metaorders([_entry("funding-boundary", signal_ms)])[0][0]
    books = [
        _book(signal_ms - 10, 99.0, 101.0, line=1),
        _book(signal_ms + COPY_DELAY_MS, 100.0, 102.0, line=2),
        _book(signal_ms + COPY_DELAY_MS + 300_000, 109.0, 111.0, line=3),
    ]

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert trade is None
    assert reason == "FUNDING_BOUNDARY_UNPRICED"


def _checkpoint_book(
    metaorder_id: str, stage: str, ts_ms: int, target_ms: int, *, line: int
) -> dict:
    checkpoint_suffix = (
        f"EXIT:{stage.removeprefix('EXIT_')}"
        if stage.startswith("EXIT_")
        else stage
    )
    return {
        **_book(ts_ms, 99.0 + line, 101.0 + line, line=line, causal=True),
        "metaorder_id": metaorder_id,
        "checkpoint_stage": stage,
        "checkpoint_id": f"{metaorder_id}:{checkpoint_suffix}",
        "checkpoint_target_ms": target_ms,
        "collector_protocol": CHECKPOINT_COLLECTOR_PROTOCOL,
        "instrument_identity_schema": INSTRUMENT_IDENTITY_SCHEMA,
        "writer_run_id": "copy-writer-clean",
        "clean_epoch_ms": 500,
    }


def test_executeur_lie_les_trois_books_au_metaordre_exact() -> None:
    metaorder = cluster_metaorders([_entry("bound", 1_000, action="OPEN")])[0][0]
    identifier = metaorder["metaorder_id"]
    books = [
        _checkpoint_book(identifier, "REFERENCE", 1_000, 1_000, line=1),
        _checkpoint_book(identifier, "ENTRY", 61_000, 61_000, line=2),
        _checkpoint_book(identifier, "EXIT_300000", 361_000, 361_000, line=3),
    ]

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert reason == "LIQUIDATABLE_NET"
    assert trade is not None
    assert trade["book_binding_method"] == "EXACT_METAORDER_CHECKPOINTS"
    assert trade["checkpoint_writer_run_id"] == "copy-writer-clean"
    assert trade["checkpoint_clean_epoch_ms"] == 500
    assert trade["all_checkpoints_post_clean_epoch"] is True


def test_executeur_refuse_un_checkpoint_reference_recu_apres_le_signal() -> None:
    metaorder = cluster_metaorders([_entry("late-reference", 1_000, action="OPEN")])[0][0]
    identifier = metaorder["metaorder_id"]
    books = [
        _checkpoint_book(identifier, "REFERENCE", 1_001, 1_000, line=1),
        _checkpoint_book(identifier, "ENTRY", 61_000, 61_000, line=2),
        _checkpoint_book(identifier, "EXIT_300000", 361_000, 361_000, line=3),
    ]

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert trade is None
    assert reason == "STALE_EXACT_METAORDER_CHECKPOINT"


def test_executeur_certifiable_lie_frais_et_raisons_zero_canoniques() -> None:
    metaorder = cluster_metaorders([_entry("economic", 1_000, action="OPEN")])[0][0]
    identifier = metaorder["metaorder_id"]
    books = [
        _checkpoint_book(identifier, "REFERENCE", 1_000, 1_000, line=1),
        _checkpoint_book(identifier, "ENTRY", 61_000, 61_000, line=2),
        _checkpoint_book(identifier, "EXIT_300000", 361_000, 361_000, line=3),
    ]
    for row in books:
        row.pop("connection_id")
        row.pop("l2_gap_epoch")

    trade, reason = execute_metaorder(
        metaorder,
        books,
        horizon_ms=300_000,
        require_causal_books=True,
        economic_mode=EconomicRunMode.CERTIFIABLE,
    )

    assert reason == "LIQUIDATABLE_NET"
    assert trade is not None
    assert trade["fee_provenance_source"] == "CANONICAL_ECONOMIC_ASSUMPTION_REGISTRY"
    assert trade["economic_contract"]["certification"]["ready"] is True
    assert len(trade["assumption_snapshot_hash"]) == 64
    assert trade["cost_component_receipts"]["slippage"]["zero_reason"] == (
        "MEASURED_ZERO"
    )


def test_executeur_certifiable_refuse_un_override_local_de_frais() -> None:
    metaorder = cluster_metaorders([_entry("economic", 1_000, action="OPEN")])[0][0]
    with pytest.raises(EconomicConfigError, match="fee_bps local interdit"):
        execute_metaorder(
            metaorder,
            [],
            horizon_ms=300_000,
            fee_bps=1.0,
            economic_mode=EconomicRunMode.CERTIFIABLE,
        )


@pytest.mark.parametrize(
    ("overrides", "metaorder_overrides", "expected_reason"),
    [
        ({"notional_usd": True}, {}, "INVALID_EXECUTION_PARAMETERS"),
        ({"horizon_ms": True}, {}, "INVALID_EXECUTION_PARAMETERS"),
        ({"direction_multiplier": True}, {}, "INVALID_EXECUTION_PARAMETERS"),
        ({}, {"signal_ts_ms": True}, "INVALID_METAORDER"),
        ({}, {"direction": True}, "INVALID_METAORDER"),
    ],
)
def test_executeur_refuse_les_booleens_dans_les_champs_numeriques(
    overrides: dict[str, object],
    metaorder_overrides: dict[str, object],
    expected_reason: str,
) -> None:
    metaorder = {
        **cluster_metaorders([_entry("boolean", 1_000, action="OPEN")])[0][0],
        **metaorder_overrides,
    }
    parameters = {"horizon_ms": 300_000, **overrides}

    trade, reason = execute_metaorder(metaorder, [], **parameters)

    assert trade is None
    assert reason == expected_reason


def test_evaluation_gelee_certifiable_refuse_un_horizon_hors_protocole() -> None:
    with pytest.raises(EconomicConfigError, match="horizon"):
        evaluate_frozen(
            [],
            {},
            frozen_parameters={
                "selected_horizon_ms": 123_456,
                "walk_forward_bounds": {},
                "causal_observation_required_all_segments": True,
            },
            frozen_at_ms=900_000,
            economic_mode=EconomicRunMode.CERTIFIABLE,
        )


def test_evaluation_gelee_certifiable_exige_la_causalite_sur_tous_les_segments() -> None:
    with pytest.raises(EconomicConfigError, match="causalite"):
        evaluate_frozen(
            [],
            {},
            frozen_parameters={
                "selected_horizon_ms": 300_000,
                "walk_forward_bounds": {
                    "train_start_ms": 1,
                    "train_end_ms": 2,
                    "validation_start_ms": 400_000,
                    "validation_end_ms": 400_001,
                    "oos_start_ms": 800_000,
                    "oos_end_ms": 800_001,
                    "purge_ms": COPY_DELAY_MS + 300_000 + MAX_TARGET_LAG_MS,
                },
            },
            frozen_at_ms=900_000,
            economic_mode=EconomicRunMode.CERTIFIABLE,
        )


def test_preuve_temporelle_ne_revendiqe_jamais_un_no_lookahead_non_prouve() -> None:
    proof = temporal_evidence({
        "segments": {"oos": {"summary": {}}, "forward": {"summary": {}}},
        "trades": {"forward": []},
        "causal_observation_required_all_segments": False,
        "temporal_purge_verified": False,
    })

    assert proof["oos"]["no_lookahead"] is False
    assert proof["oos"]["purged"] is False


@pytest.mark.parametrize(
    ("oos_exact", "placebo_exact", "expected"),
    [
        ("5.0000000000000002", "5.0000000000000001", True),
        ("5.0000000000000001", "5.0000000000000002", False),
    ],
)
def test_placebo_comparison_uses_exact_decimal_nets(
    oos_exact: str, placebo_exact: str, expected: bool
) -> None:
    proof = temporal_evidence({
        "segments": {
            "oos": {"summary": {
                "positions_fermees": 1,
                "net_pnl_usd": 5.0,
                "net_pnl_usd_exact_decimal": oos_exact,
            }},
            "forward": {"summary": {"positions_fermees": 1}},
        },
        "placebo_inverted_oos": {"summary": {
            "positions_fermees": 1,
            "net_pnl_usd": 5.0,
            "net_pnl_usd_exact_decimal": placebo_exact,
        }},
        "trades": {"forward": [{"causal_forward_eligible": True}]},
        "causal_observation_required_all_segments": True,
        "temporal_purge_verified": True,
    })

    assert proof["placebos"]["beaten"] is expected
    assert proof["placebos"]["candidate_net_usd_exact_decimal"] == oos_exact
    assert proof["placebos"]["placebo_net_usd_exact_decimal"] == placebo_exact
    assert json.dumps(proof, allow_nan=False, sort_keys=True)


def test_executeur_ne_peut_pas_emprunter_les_checkpoints_dun_autre_metaordre() -> None:
    metaorder = cluster_metaorders([_entry("wanted", 1_000, action="OPEN")])[0][0]
    books = [
        _checkpoint_book("other", "REFERENCE", 1_000, 1_000, line=1),
        _checkpoint_book("other", "ENTRY", 61_000, 61_000, line=2),
        _checkpoint_book("other", "EXIT_300000", 361_000, 361_000, line=3),
    ]

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert trade is None
    assert reason == "MISSING_EXACT_METAORDER_CHECKPOINT"


def test_executeur_refuse_un_checkpoint_id_non_canonique() -> None:
    metaorder = cluster_metaorders([_entry("bound", 1_000, action="OPEN")])[0][0]
    identifier = metaorder["metaorder_id"]
    books = [
        _checkpoint_book(identifier, "REFERENCE", 1_000, 1_000, line=1),
        _checkpoint_book(identifier, "ENTRY", 61_000, 61_000, line=2),
        _checkpoint_book(identifier, "EXIT_300000", 361_000, 361_000, line=3),
    ]
    books[-1]["checkpoint_id"] = f"{identifier}:EXIT_300000"

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert trade is None
    assert reason == "CHECKPOINT_ID_BINDING_MISMATCH"


def test_long_and_short_use_marketable_prices_and_reconcile_costs() -> None:
    books = [
        _book(1_000, 99.0, 101.0, line=1),
        _book(61_000, 100.0, 102.0, line=2),
        _book(361_000, 109.0, 111.0, line=3),
    ]
    long_meta = cluster_metaorders([_entry("long", 1_000)])[0][0]
    short_meta = cluster_metaorders([_entry("short", 1_000, direction=-1)])[0][0]

    long_trade, long_reason = execute_metaorder(long_meta, books, horizon_ms=300_000)
    short_trade, short_reason = execute_metaorder(short_meta, books, horizon_ms=300_000)

    assert long_reason == short_reason == "LIQUIDATABLE_NET"
    assert long_trade is not None and short_trade is not None
    assert long_trade["entry_price"] == pytest.approx(102.0)
    assert long_trade["exit_price"] == pytest.approx(109.0)
    assert short_trade["entry_price"] == pytest.approx(100.0)
    assert short_trade["exit_price"] == pytest.approx(111.0)
    for trade in (long_trade, short_trade):
        expected = (
            trade["gross_pnl_usd"]
            - trade["fees_usd"]
            - trade["spread_cost_usd"]
            - trade["slippage_cost_usd"]
            - trade["latency_cost_usd"]
        )
        assert math.isclose(expected, trade["net_pnl_usd"], abs_tol=1e-8)
        assert trade["liquidatable_net"] is True
        assert trade["paper_read_only"] is True and trade["real_execution"] is False


def test_certifiable_walks_each_l2_side_and_receipts_observed_slippage() -> None:
    books = [
        _book(1_000, 99.0, 101.0, line=1),
        {
            **_book(61_000, 100.0, 102.0, line=2),
            "bids5": [[100.0, 0.5], [99.0, 2.0]],
            "asks5": [[102.0, 0.5], [104.0, 2.0]],
        },
        {
            **_book(361_000, 109.0, 111.0, line=3),
            "bids5": [[109.0, 0.5], [108.0, 2.0]],
            "asks5": [[111.0, 0.5], [113.0, 2.0]],
        },
    ]
    metaorder = cluster_metaorders([_entry("walk", 1_000)])[0][0]

    trade, reason = execute_metaorder(
        metaorder,
        books,
        horizon_ms=300_000,
        economic_mode=EconomicRunMode.CERTIFIABLE,
    )

    assert reason == "LIQUIDATABLE_NET"
    assert trade is not None
    assert trade["entry_price"] > 102.0
    assert trade["exit_price"] < 109.0
    assert trade["slippage_cost_usd"] > 0.0
    assert trade["slippage_zero_reason"] is None
    assert trade["cost_component_receipts"]["slippage"]["zero_reason"] is None
    assert trade["cost_component_receipts"]["slippage"]["formula_id"] == (
        "copy_vault.observed_l2_vwap.v1"
    )
    assert math.isclose(
        trade["gross_pnl_usd"]
        - trade["fees_usd"]
        - trade["spread_cost_usd"]
        - trade["slippage_cost_usd"]
        - trade["latency_cost_usd"],
        trade["net_pnl_usd"],
        abs_tol=1e-8,
    )


def test_certifiable_refuses_missing_or_insufficient_exact_l2_depth() -> None:
    metaorder = cluster_metaorders([_entry("depth", 1_000)])[0][0]
    missing_levels = [
        {key: value for key, value in _book(1_000, 99.0, 101.0).items() if key not in {"bids5", "asks5"}},
        {key: value for key, value in _book(61_000, 100.0, 102.0).items() if key not in {"bids5", "asks5"}},
        {key: value for key, value in _book(361_000, 109.0, 111.0).items() if key not in {"bids5", "asks5"}},
    ]
    trade, reason = execute_metaorder(
        metaorder,
        missing_levels,
        horizon_ms=300_000,
        economic_mode=EconomicRunMode.CERTIFIABLE,
    )
    assert trade is None and reason == "MISSING_EXACT_L2_LEVELS"

    insufficient_exit = [
        _book(1_000, 99.0, 101.0),
        _book(61_000, 100.0, 102.0),
        {
            **_book(361_000, 109.0, 111.0),
            "bids5": [[109.0, 0.1]],
        },
    ]
    trade, reason = execute_metaorder(
        metaorder,
        insufficient_exit,
        horizon_ms=300_000,
        economic_mode=EconomicRunMode.CERTIFIABLE,
    )
    assert trade is None and reason == "INSUFFICIENT_OBSERVED_EXIT_DEPTH"


def test_capacity_and_duplicate_trade_guards_fail_closed() -> None:
    metaorder = cluster_metaorders([_entry("a", 1_000)])[0][0]
    books = [
        _book(1_000, 99.0, 101.0),
        _book(61_000, 100.0, 102.0, capacity=149.99),
        _book(361_000, 109.0, 111.0),
    ]
    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)
    assert trade is None and reason == "OBSERVED_TOP_CAPACITY_TOO_LOW"

    dense = [
        _book(1_000, 99.0, 101.0),
        _book(61_000, 100.0, 102.0),
        _book(361_000, 109.0, 111.0),
    ]
    trades, diagnostics = replay_metaorders(
        [metaorder, dict(metaorder)], {"BTC": dense}, horizon_ms=300_000
    )
    assert len(trades) == 1
    assert diagnostics["DUPLICATE_TRADE_ID_REJECTED"] == 1
    assert summarize(trades)["duplicate_trade_ids"] == 0


def test_all_win_profit_factor_is_unmeasured_not_json_infinity() -> None:
    metaorder = cluster_metaorders([_entry("winner", 1_000)])[0][0]
    books = [
        _book(1_000, 99.0, 101.0),
        _book(61_000, 100.0, 102.0),
        _book(361_000, 109.0, 111.0),
    ]
    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert reason == "LIQUIDATABLE_NET"
    assert trade is not None and trade["net_pnl_usd"] > 0
    summary = summarize([trade])
    assert summary["sample_count"] == 1
    assert summary["profit_factor"] is None
    assert "Infinity" not in __import__("json").dumps(summary)


def test_empty_trade_summary_does_not_report_zero_economics() -> None:
    summary = summarize([])
    assert summary["sample_count"] == 0

    assert summary["positions_fermees"] == 0
    for key in (
        "gross_pnl_usd",
        "fees_usd",
        "spread_cost_usd",
        "slippage_cost_usd",
        "latency_cost_usd",
        "net_pnl_usd",
        "net_pnl_usd_exact_decimal",
        "roi_pct",
        "max_drawdown_usd",
        "max_drawdown_usd_exact_decimal",
        "hit_rate",
    ):
        assert summary[key] is None
    assert summary["LIQUIDATABLE_NET"] is False
    assert summary["economic_reconciliation_ok"] is False
    json.dumps(summary, allow_nan=False)


def test_summary_profit_factor_does_not_round_tiny_loss_into_false_edge() -> None:
    positive = "1." + "0" * 99 + "1"
    negative = "-1." + "0" * 99 + "2"
    rows = [
        {
            "trade_id": f"precision-{index}",
            "exit_ts_ms": index + 1,
            "gross_pnl_usd": pnl,
            "fees_usd": "0",
            "spread_cost_usd": "0",
            "slippage_cost_usd": "0",
            "latency_cost_usd": "0",
            "net_pnl_usd": pnl,
            "liquidatable_net": True,
        }
        for index, pnl in enumerate((positive, negative))
    ]

    result = summarize(rows)

    assert Decimal(result["net_pnl_usd_exact_decimal"]) < 0
    assert Decimal(result["profit_factor_exact_decimal"]) < 1
    assert result["profit_factor"] < 1.0
    assert Decimal(result["max_drawdown_usd_exact_decimal"]) > 1


def test_walk_forward_selects_on_train_and_forward_is_strictly_post_freeze() -> None:
    entries = []
    books = []
    spacing = 4_000_000
    for index in range(20):
        signal = 1_000 + index * spacing
        entries.append({
            **_entry(f"e-{index}", signal),
            "source": "LIVE_WS",
            "is_snapshot": False,
            "observed_at_ms": signal,
        })
        books.extend([
            _book(signal, 99.0, 101.0, line=index * 3 + 1, causal=True),
            _book(signal + 60_000, 100.0, 102.0, line=index * 3 + 2, causal=True),
            _book(signal + 360_000, 109.0, 111.0, line=index * 3 + 3, causal=True),
        ])
    metaorders = cluster_metaorders(entries)[0]
    # Freeze the protocol on the first 16 observations, then expose four
    # genuinely later causal observations as the forward segment.
    calibration = calibrate_train_only(metaorders[:16], {"BTC": books})
    assert calibration["selection_scope"] == "TRAIN_ONLY"
    assert calibration["selection_eligible"] is True

    freeze_at = int(metaorders[15]["signal_ts_ms"])
    parameters = {
        "selected_horizon_ms": calibration["selected_horizon_ms"],
        "walk_forward_bounds": calibration["bounds"],
        "causal_observation_required_all_segments": True,
    }
    evaluation = evaluate_frozen(
        metaorders,
        {"BTC": books},
        frozen_parameters=parameters,
        frozen_at_ms=freeze_at,
        economic_mode=EconomicRunMode.CERTIFIABLE,
    )
    temporal = temporal_evidence(evaluation)

    assert temporal["oos"]["no_lookahead"] is True
    assert temporal["forward"]["post_freeze"] is True
    assert evaluation["economic_contract"]["certification"]["ready"] is True
    assert len(evaluation["assumption_snapshot_hash"]) == 64
    assert all(
        trade["assumption_snapshot_hash"]
        == evaluation["assumption_snapshot_hash"]
        for rows in evaluation["trades"].values()
        for trade in rows
    )
    assert all(
        trade["signal_ts_ms"] > freeze_at
        for trade in evaluation["trades"]["forward"]
    )
    assert temporal["placebos"]["beaten"] is True


def test_new_proof_policy_uses_only_complete_utc_days_after_freeze(monkeypatch) -> None:
    day_ms = 86_400_000
    frozen_at_ms = 1_725_571_200_000 + 12 * 60 * 60 * 1000
    proof_start_ms = ((frozen_at_ms // day_ms) + 1) * day_ms
    as_of_ms = proof_start_ms + 2 * day_ms + 12 * 60 * 60 * 1000
    calls = []

    def recording_replay(*args, start_ms=None, end_ms=None, **kwargs):
        del args, kwargs
        calls.append((start_ms, end_ms))
        return [], {"metaorders_considered": 0, "completed_positions": 0}

    monkeypatch.setattr(
        "hl_observer.backtesting.copy_vault_executable.replay_metaorders",
        recording_replay,
    )
    result = evaluate_frozen(
        [],
        {},
        frozen_parameters={
            "selected_horizon_ms": 300_000,
            "walk_forward_bounds": {
                "train_start_ms": 1,
                "train_end_ms": 2,
                "validation_start_ms": 3,
                "validation_end_ms": 4,
                "oos_start_ms": 5,
                "oos_end_ms": 6,
            },
            "post_freeze_proof_policy": "FIRST_TWO_COMPLETE_UTC_DAYS_AFTER_FREEZE_V1",
            "causal_observation_required_all_segments": True,
        },
        frozen_at_ms=frozen_at_ms,
        evaluated_at_ms=as_of_ms,
        economic_mode=EconomicRunMode.CERTIFIABLE,
    )

    assert calls[:4] == [
        (1, 2),
        (3, 4),
        (proof_start_ms, proof_start_ms + day_ms - 1),
        (proof_start_ms + day_ms, proof_start_ms + 2 * day_ms - 1),
    ]
    assert calls[4] == (proof_start_ms, proof_start_ms + day_ms - 1)
    assert result["proof_window"] == {
        "policy": "FIRST_TWO_COMPLETE_UTC_DAYS_AFTER_FREEZE_V1",
        "frozen_at_ms": frozen_at_ms,
        "evaluated_at_ms": as_of_ms,
        "proof_start_ms": proof_start_ms,
        "completed_cutoff_exclusive_ms": proof_start_ms + 2 * day_ms,
        "complete_days_available": 2,
        "oos_day_start_ms": proof_start_ms,
        "oos_day_end_ms": proof_start_ms + day_ms - 1,
        "forward_start_ms": proof_start_ms + day_ms,
        "forward_end_ms": proof_start_ms + 2 * day_ms - 1,
    }


def test_protocol_signature_invalidates_pre_vwap_pre_complete_day_freezes() -> None:
    signature = protocol_signature()

    assert signature["calibration_protocol"] == (
        "copy_vault_executable_walk_forward_v8_explicit_l2_gap_identity"
    )
    assert signature["causal_book_gap_identity_policy"] == (
        "same_connection_and_explicit_gap_epoch_required_for_causal_stream_triplets_v1"
    )
    assert signature["paper_equity_usd"] == 200.0
    assert signature["max_gross_exposure_usd"] == 200.0
    assert signature["notional_usd"] == 150.0
    assert signature["execution_pricing_policy"] == (
        "observed_side_specific_l2_vwap_full_size_v1"
    )
    assert signature["minimum_complete_proof_days"] == 2
    assert signature["post_freeze_proof_policy"] == (
        "FIRST_TWO_COMPLETE_UTC_DAYS_AFTER_FREEZE_V1"
    )


def test_calibration_uses_candidate_horizon_specific_purge() -> None:
    entries = [
        {
            **_entry(f"e-{index}", 1_000 + index * 4_000_000),
            "source": "LIVE_WS",
            "is_snapshot": False,
            "observed_at_ms": 1_000 + index * 4_000_000,
        }
        for index in range(16)
    ]
    metaorders = cluster_metaorders(entries)[0]

    calibration = calibrate_train_only(metaorders, {"BTC": []})

    for row in calibration["grid"]:
        expected = COPY_DELAY_MS + int(row["horizon_ms"]) + MAX_TARGET_LAG_MS
        assert row["bounds"]["purge_ms"] == expected
    assert len({row["bounds"]["purge_ms"] for row in calibration["grid"]}) == len(HORIZONS_MS)


def test_selected_bounds_match_selected_horizon_and_default_is_shortest() -> None:
    entries = [
        {
            **_entry(f"e-{index}", 1_000 + index * 4_000_000),
            "source": "LIVE_WS",
            "is_snapshot": False,
            "observed_at_ms": 1_000 + index * 4_000_000,
        }
        for index in range(16)
    ]
    metaorders = cluster_metaorders(entries)[0]

    result = calibrate_train_only(metaorders, {"BTC": []})

    assert result["selection_eligible"] is False
    assert result["selected_horizon_ms"] == HORIZONS_MS[0]
    assert result["bounds"] == result["grid"][0]["bounds"]
    assert result["bounds"] == temporal_bounds(
        metaorders,
        purge_ms=COPY_DELAY_MS + HORIZONS_MS[0] + MAX_TARGET_LAG_MS,
    )


def test_calibration_never_selects_the_least_bad_losing_horizon(monkeypatch) -> None:
    entries = [
        {
            **_entry(f"e-{index}", 1_000 + index * 4_000_000),
            "source": "LIVE_WS",
            "is_snapshot": False,
            "observed_at_ms": 1_000 + index * 4_000_000,
        }
        for index in range(20)
    ]
    metaorders, _ = cluster_metaorders(entries, gap_ms=60_000)

    def losing_replay(*args, horizon_ms, **kwargs):
        del args, kwargs
        return [
                {
                    "trade_id": f"{horizon_ms}-{index}",
                    "exit_ts_ms": 10_000 + index,
                    "gross_pnl_usd": 0.1,
                "fees_usd": 0.1,
                "spread_cost_usd": 0.1,
                "slippage_cost_usd": 0.0,
                "latency_cost_usd": 0.0,
                "net_pnl_usd": -0.1,
                "liquidatable_net": True,
            }
            for index in range(8)
        ], {}

    monkeypatch.setattr(
        "hl_observer.backtesting.copy_vault_executable.replay_metaorders",
        losing_replay,
    )
    result = calibrate_train_only(metaorders, {"BTC": []})

    assert result["selection_eligible"] is False
    assert result["status"] == "KILL_TRAIN_NO_POSITIVE_RECONCILED_CANDIDATE"
    assert all(row["sample_eligible"] is True for row in result["grid"])
    assert all(row["eligible"] is False for row in result["grid"])


def test_calibration_ranks_candidates_by_unrounded_decimal_net(monkeypatch) -> None:
    entries = [
        {
            **_entry(f"exact-rank-{index}", 1_000 + index * 4_000_000),
            "source": "LIVE_WS",
            "is_snapshot": False,
            "observed_at_ms": 1_000 + index * 4_000_000,
        }
        for index in range(20)
    ]
    metaorders, _ = cluster_metaorders(entries, gap_ms=60_000)

    def replay_with_close_nets(*args, horizon_ms, **kwargs):
        del args, kwargs
        amount = (
            "1.0000000000000000002"
            if horizon_ms == max(HORIZONS_MS)
            else "1.0000000000000000001"
        )
        return [
            {
                "trade_id": f"{horizon_ms}-{index}",
                "exit_ts_ms": index + 1,
                "gross_pnl_usd": amount,
                "fees_usd": "0",
                "spread_cost_usd": "0",
                "slippage_cost_usd": "0",
                "latency_cost_usd": "0",
                "net_pnl_usd": amount,
                "liquidatable_net": True,
            }
            for index in range(8)
        ], {}

    monkeypatch.setattr(
        "hl_observer.backtesting.copy_vault_executable.replay_metaorders",
        replay_with_close_nets,
    )

    result = calibrate_train_only(metaorders, {"BTC": []})

    assert result["selection_eligible"] is True
    assert result["selected_horizon_ms"] == max(HORIZONS_MS)
