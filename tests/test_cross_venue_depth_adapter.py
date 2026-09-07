from __future__ import annotations

import json
from pathlib import Path

from hl_observer.config.cross_venue_instruments import MAPPING_SCHEMA_VERSION
from hl_observer.simulation.cross_venue_depth_adapter import (
    enrich_trades_with_depth,
    finalize_judgement,
    load_depth_snapshots,
)


def _trade() -> dict:
    return {
        "trade_id": "x" * 64,
        "coin": "BTC",
        "ts_in": 10_000.0,
        "ts_out": 12_000.0,
        "gross_signal_bps": 40.0,
        "fees_bps": 16.0,
        "spread_cost_bps": 4.0,
        "latency_cost_bps": 2.0,
        "net_bps": 18.0,
        "net_usd": 0.027,
        "two_leg": True,
        "LIQUIDATABLE_NET": False,
    }


def test_depth_uses_only_at_or_before_snapshots_and_proves_capacity():
    snapshots = {
        "BTC": [
            {"_ts_ms": 9_500, "_capacity_usd": 100.0},
            {"_ts_ms": 10_100, "_capacity_usd": 1.0},  # future at entry: must NOT be used
            {"_ts_ms": 11_500, "_capacity_usd": 100.0},
        ]
    }
    [trade] = enrich_trades_with_depth([_trade()], snapshots, notional_usd=15.0, freshness_ms=1_000.0)
    assert trade["slippage_bps"] == 0.0
    assert trade["entry_capacity_usd"] == 100.0
    assert trade["exit_capacity_usd"] == 100.0
    assert trade["entry_depth_age_ms"] == 500.0
    assert trade["LIQUIDATABLE_NET"] is True
    assert trade["economic_reconciled"] is True


def test_stale_or_missing_depth_never_becomes_zero_slippage():
    snapshots = {"BTC": [{"_ts_ms": 1_000, "_capacity_usd": 100.0}]}
    [trade] = enrich_trades_with_depth([_trade()], snapshots, notional_usd=15.0, freshness_ms=1_000.0)
    assert trade["slippage_bps"] is None
    assert trade["LIQUIDATABLE_NET"] is False
    assert "STALE" in trade["depth_reason"]


def test_insufficient_top_capacity_is_non_liquidatable():
    snapshots = {
        "BTC": [
            {"_ts_ms": 9_500, "_capacity_usd": 10.0},
            {"_ts_ms": 11_500, "_capacity_usd": 100.0},
        ]
    }
    [trade] = enrich_trades_with_depth([_trade()], snapshots, notional_usd=15.0, freshness_ms=1_000.0)
    assert trade["slippage_bps"] is None
    assert trade["depth_reason"] == "ENTRY_TOP_CAPACITY_INSUFFICIENT"


def test_load_depth_snapshots_converts_collecte_seconds_to_ms(tmp_path: Path):
    path = tmp_path / "runtime" / "data" / "carnet_venues.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "coin": "btc",
                "collecte_ts": 1_786_552_000.125,
                "taille_min_usd": 42.0,
                "instrument_mapping_schema": MAPPING_SCHEMA_VERSION,
                "instrument_mapping_exact": True,
                "atomic_snapshot_certified": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    rows = load_depth_snapshots(tmp_path)
    assert rows["BTC"][0]["_ts_ms"] == 1_786_552_000_125
    assert rows["BTC"][0]["_capacity_usd"] == 42.0


def test_load_depth_snapshots_rejects_uncertified_mapping_and_four_side_provenance(tmp_path: Path):
    path = tmp_path / "runtime" / "data" / "carnet_venues.jsonl"
    path.parent.mkdir(parents=True)
    rows = [
        {"coin": "BTC", "collecte_ts": 1_786_552_000.100, "taille_min_usd": 50.0},
        {
            "coin": "ETH",
            "collecte_ts": 1_786_552_000.200,
            "taille_min_usd": 50.0,
            "instrument_mapping_schema": MAPPING_SCHEMA_VERSION,
            "instrument_mapping_exact": False,
            "atomic_snapshot_certified": False,
        },
        {
            "coin": "SOL",
            "collecte_ts": 1_786_552_000.300,
            "taille_min_usd": 50.0,
            "instrument_mapping_schema": MAPPING_SCHEMA_VERSION,
            "instrument_mapping_exact": True,
            "atomic_snapshot_certified": True,
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    snapshots = load_depth_snapshots(tmp_path)
    assert set(snapshots) == {"SOL"}
    assert snapshots["SOL"][0]["_capacity_usd"] == 50.0


def test_finalize_judgement_keeps_missing_depth_fail_closed():
    trade = _trade()
    base = {
        "n_trades": 1,
        "positions_ouvertes": 1,
        "positions_fermees": 1,
        "LIQUIDATABLE_NET": False,
    }
    result = finalize_judgement([trade], base, notional_usd=15.0)
    assert result["slippage_cost_usd"] is None
    assert result["LIQUIDATABLE_NET"] is False
    assert result["depth_measured_trades"] == 0
