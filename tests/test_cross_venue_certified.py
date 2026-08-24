from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.cross_venue_certified import (
    BBO_SOURCE_MODE,
    FOUR_FILL_CONTRACT_VERSION,
    SOURCE_MODE,
    build_four_fill_cycle,
    certify_atomic_bbo_row,
    certify_atomic_row,
    load_certified_atomic_bbo_series,
    load_certified_atomic_series,
    load_preferred_certified_atomic_series,
    vwap_for_notional,
)
from hl_observer.config.cross_venue_instruments import MAPPING_SCHEMA_VERSION


def _levels(best: float, *, bid: bool, size: float = 10.0):
    step = -0.05 if bid else 0.05
    return [[best + i * step, size] for i in range(5)]


def _row(*, coin="BTC", symbol="BTCUSDT", hl_ms=1000.0, bin_ms=1050.0, size=10.0):
    return {
        "coin": coin, "binance_symbol": symbol,
        "hl_bids5": _levels(101.0, bid=True, size=size),
        "hl_asks5": _levels(101.1, bid=False, size=size),
        "bin_bids5": _levels(99.9, bid=True, size=size),
        "bin_asks5": _levels(100.0, bid=False, size=size),
        "hl_received_at_ms": hl_ms, "bin_received_at_ms": bin_ms,
        "taille_min_usd": 1000.0, "read_only": True, "real_execution": False,
    }


def _exit(*, hl_ms=2000.0, bin_ms=2040.0, size=10.0):
    row = _row(hl_ms=hl_ms, bin_ms=bin_ms, size=size)
    row["hl_bids5"] = _levels(99.95, bid=True, size=size)
    row["hl_asks5"] = _levels(100.05, bid=False, size=size)
    row["bin_bids5"] = _levels(99.95, bid=True, size=size)
    row["bin_asks5"] = _levels(100.05, bid=False, size=size)
    return row


def _bbo_row(*, event_id="bbo-1", symbol="BTCUSDT", certified=True):
    capacity = min(101.0 * 10.0, 101.1 * 9.0, 99.9 * 8.0, 100.0 * 7.0)
    return {
        "event_id": event_id,
        "coin": "BTC",
        "binance_symbol": symbol,
        "instrument_mapping_schema": MAPPING_SCHEMA_VERSION,
        "instrument_mapping_exact": symbol == "BTCUSDT",
        "source_mode": BBO_SOURCE_MODE,
        "atomic_bbo_certified": certified,
        "snapshot_wall_ts_ms": 1100.0,
        "hl_received_at_ms": 1000.0,
        "bin_received_at_ms": 1050.0,
        "recu_mono_hl_ns": 1_000_000_000,
        "recu_mono_bin_ns": 1_050_000_000,
        "desync_ms": 50.0,
        "age_hl_ms": 100.0,
        "age_bin_ms": 50.0,
        "hl_bid": 101.0,
        "hl_ask": 101.1,
        "bin_bid": 99.9,
        "bin_ask": 100.0,
        "hl_bid_sz": 10.0,
        "hl_ask_sz": 9.0,
        "bin_bid_sz": 8.0,
        "bin_ask_sz": 7.0,
        "minimum_four_side_top_capacity_usd": capacity,
        "taille_top_usd": capacity,
        "read_only": True,
        "real_execution": False,
    }


def test_certification_refuse_mapping_ou_skew_non_prouves():
    proof = certify_atomic_row(_row())
    assert proof["ok"] is True
    assert proof["minimum_top_level_capacity_usd"] == 999.0
    assert proof["minimum_four_side_capacity_usd"] > proof["minimum_top_level_capacity_usd"]
    assert certify_atomic_row(_row(coin="PEPE", symbol="PEPEUSDT"))["ok"] is False
    assert certify_atomic_row(_row(hl_ms=1000, bin_ms=1500))["ok"] is False


def test_vwap_expose_un_fill_partiel_sans_inventer_la_liquidite():
    result = vwap_for_notional([[100.0, 0.05]], 15.0, side="BUY")
    assert result["complete"] is False
    assert result["filled_notional_usd"] == 5.0
    assert result["remaining_notional_usd"] == 10.0


def test_cycle_certifie_exige_exactement_quatre_fills_complets():
    cycle = build_four_fill_cycle(certify_atomic_row(_row()), certify_atomic_row(_exit()), direction=1, notional_usd=15.0, fees_bps_total=2.0)
    assert cycle["economic_eligible"] is True
    assert cycle["schema_version"] == FOUR_FILL_CONTRACT_VERSION
    assert cycle["fill_count"] == 4 and cycle["four_fills_complete"] is True
    assert cycle["naked_leg_risk"] is False and cycle["net_pnl_usd"] is not None


def test_cycle_partiel_devient_jambe_nue_et_aucun_pnl_economique():
    entry = certify_atomic_row(_row())
    exit_ = certify_atomic_row(_exit())
    entry["books"]["BIN"]["asks"] = [(100.0, 0.01)]
    cycle = build_four_fill_cycle(entry, exit_, direction=1, notional_usd=15.0, fees_bps_total=2.0)
    assert cycle["economic_eligible"] is False
    assert cycle["partial_fill_detected"] is True and cycle["naked_leg_risk"] is True
    assert cycle["net_pnl_usd"] is None


def test_loader_ne_requalifie_jamais_les_anciennes_lignes(tmp_path: Path):
    target = tmp_path / "runtime/data/carnet_venues.jsonl"
    target.parent.mkdir(parents=True)
    legacy = {"coin": "BTC", "hl_bid": 101.0, "hl_ask": 101.1, "bin_bid": 99.9, "bin_ask": 100.0, "taille_min_usd": 1000.0, "collecte_ts": 1.0, "read_only": True, "real_execution": False}
    certified = _row()
    certified["observation_id"] = "certified"
    target.write_text(json.dumps(legacy) + "\n" + json.dumps(certified) + "\n", encoding="utf-8")
    series, depth, meta = load_certified_atomic_series(tmp_path)
    assert len(series["BTC"]) == 1 and len(depth["BTC"]) == 1
    assert depth["BTC"][0][1] == 999.0
    assert meta["source_mode"] == SOURCE_MODE and meta["certified_snapshots"] == 1
    assert meta["capacity_definition"] == "minimum USD capacity on the four BBO top levels"
    assert meta["legacy_uncertified_rows_rejected"] == 1 and meta["legacy_rows_never_upgraded"] is True


def test_certification_bbo_exige_provenance_mapping_timestamps_et_quatre_tailles():
    proof = certify_atomic_bbo_row(_bbo_row())
    assert proof["ok"] is True
    assert proof["source_mode"] == BBO_SOURCE_MODE
    assert proof["minimum_top_level_capacity_usd"] == 700.0

    legacy = _bbo_row(certified=False)
    legacy.pop("bin_ask_sz")
    legacy.pop("snapshot_wall_ts_ms")
    rejected = certify_atomic_bbo_row(legacy)
    assert rejected["ok"] is False
    assert "EXPLICIT_ATOMIC_BBO_PROVENANCE_MISSING" in rejected["reasons"]
    assert "FOUR_SIDE_BBO_MISSING" in rejected["reasons"]
    assert "SNAPSHOT_TIMESTAMP_MISSING" in rejected["reasons"]


def test_certification_bbo_refuse_mapping_skew_ou_capacite_incoherents():
    wrong_mapping = certify_atomic_bbo_row(_bbo_row(symbol="ETHUSDT"))
    assert "INSTRUMENT_MAPPING_NOT_EXACT" in wrong_mapping["reasons"]
    wrong_skew = _bbo_row()
    wrong_skew["desync_ms"] = 10.0
    assert "VENUE_SKEW_NOT_RECONCILED" in certify_atomic_bbo_row(wrong_skew)["reasons"]
    wrong_capacity = _bbo_row()
    wrong_capacity["taille_top_usd"] = 9999.0
    assert "FOUR_SIDE_CAPACITY_NOT_RECONCILED" in certify_atomic_bbo_row(wrong_capacity)["reasons"]


def test_loader_bbo_deduplique_et_ne_requalifie_pas_une_ligne_legacy(tmp_path: Path):
    target = tmp_path / "runtime/data/cross_venue_atomic_bbo.jsonl"
    target.parent.mkdir(parents=True)
    valid = _bbo_row()
    duplicate = dict(valid)
    legacy = _bbo_row(event_id="legacy", certified=False)
    target.write_text(
        "\n".join(json.dumps(row) for row in (valid, duplicate, legacy)) + "\n",
        encoding="utf-8",
    )
    series, depth, meta = load_certified_atomic_bbo_series(tmp_path)
    assert len(series["BTC"]) == 1
    assert depth["BTC"] == [(1100.0, 700.0)]
    assert meta["certified_snapshots"] == 1
    assert meta["duplicates_rejected"] == 1
    assert meta["legacy_uncertified_rows_rejected"] == 1


def test_loader_prefere_bbo_dense_et_replie_sur_l2_si_absent(tmp_path: Path):
    bbo_target = tmp_path / "runtime/data/cross_venue_atomic_bbo.jsonl"
    bbo_target.parent.mkdir(parents=True)
    bbo_target.write_text(json.dumps(_bbo_row()) + "\n", encoding="utf-8")
    _, _, bbo_meta = load_preferred_certified_atomic_series(tmp_path)
    assert bbo_meta["source_mode"] == BBO_SOURCE_MODE

    bbo_target.unlink()
    l2_target = tmp_path / "runtime/data/carnet_venues.jsonl"
    certified_l2 = _row()
    certified_l2["observation_id"] = "l2-1"
    l2_target.write_text(json.dumps(certified_l2) + "\n", encoding="utf-8")
    _, _, l2_meta = load_preferred_certified_atomic_series(tmp_path)
    assert l2_meta["source_mode"] == SOURCE_MODE
    assert l2_meta["preferred_bbo_source"]["certified_snapshots"] == 0
