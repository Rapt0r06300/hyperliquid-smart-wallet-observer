from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.cross_venue_certified import (
    FOUR_FILL_CONTRACT_VERSION,
    SOURCE_MODE,
    build_four_fill_cycle,
    certify_atomic_row,
    load_certified_atomic_series,
    vwap_for_notional,
)


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
    row["hl_bids5"] = _levels(99.95, bid=True, size=size); row["hl_asks5"] = _levels(100.05, bid=False, size=size)
    row["bin_bids5"] = _levels(99.95, bid=True, size=size); row["bin_asks5"] = _levels(100.05, bid=False, size=size)
    return row


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
    entry = certify_atomic_row(_row()); exit_ = certify_atomic_row(_exit())
    entry["books"]["BIN"]["asks"] = [(100.0, 0.01)]
    cycle = build_four_fill_cycle(entry, exit_, direction=1, notional_usd=15.0, fees_bps_total=2.0)
    assert cycle["economic_eligible"] is False
    assert cycle["partial_fill_detected"] is True and cycle["naked_leg_risk"] is True
    assert cycle["net_pnl_usd"] is None


def test_loader_ne_requalifie_jamais_les_anciennes_lignes(tmp_path: Path):
    target = tmp_path / "runtime/data/carnet_venues.jsonl"; target.parent.mkdir(parents=True)
    legacy = {"coin": "BTC", "hl_bid": 101.0, "hl_ask": 101.1, "bin_bid": 99.9, "bin_ask": 100.0, "taille_min_usd": 1000.0, "collecte_ts": 1.0, "read_only": True, "real_execution": False}
    certified = _row(); certified["observation_id"] = "certified"
    target.write_text(json.dumps(legacy) + "\n" + json.dumps(certified) + "\n", encoding="utf-8")
    series, depth, meta = load_certified_atomic_series(tmp_path)
    assert len(series["BTC"]) == 1 and len(depth["BTC"]) == 1
    assert depth["BTC"][0][1] == 999.0
    assert meta["source_mode"] == SOURCE_MODE and meta["certified_snapshots"] == 1
    assert meta["capacity_definition"] == "minimum USD capacity on the four BBO top levels"
    assert meta["legacy_uncertified_rows_rejected"] == 1 and meta["legacy_rows_never_upgraded"] is True
