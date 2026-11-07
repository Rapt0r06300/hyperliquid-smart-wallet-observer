"""Famille A #1 : repli BBO.

Quand le carnet L2 complet manque, la tape BBO fournit un top-of-book causal
(1 niveau) : donnees reelles, causales (fraicheur 30 s), profondeur honnetement
limitee. Cela augmente les jours actifs scoreables sans inventer de profondeur
ni introduire de look-ahead.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.copy_vault_book_loader import load_observed_books
from hl_observer.backtesting.copy_vault_v21_frozen import _reference_depth_features

_SHA = "ab" * 32  # 64 hex


def _bbo_row(
    *, coin: str = "BTC", received: int = 2_010, exchange: int = 2_000,
    bid_px: float = 100.0, bid_sz: float = 5.0,
    ask_px: float = 102.0, ask_sz: float = 3.0,
) -> dict:
    return {
        "schema_version": "hypersmart.copy_vault_bbo.v1",
        "coin": coin,
        "received_at_ms": received,
        "exchange_ts_ms": exchange,
        "bid_px": bid_px, "bid_sz": bid_sz,
        "ask_px": ask_px, "ask_sz": ask_sz,
        "source_raw_sha256": _SHA,
        "source_dataset_id": "copy_vault_bbo/BTC/2026",
        "source_shard_sha256": _SHA,
        "source_catalog_sha256": _SHA,
        "source_quality_status": "SAFE",
        "source_manifest_verified": True,
        "source_replay_compatible": True,
    }


def _write_bbo(tmp_path: Path, rows: list[dict]) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "copy_vault_bbo_tape.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_bbo_tape_yields_causal_one_level_safe_book(tmp_path: Path) -> None:
    _write_bbo(tmp_path, [_bbo_row()])

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert "BTC" in books and len(books["BTC"]) == 1
    row = books["BTC"][0]
    assert row["causal_observation"] is True
    assert row["bid"] == 100.0 and row["ask"] == 102.0
    assert row["bids5"] == [[100.0, 5.0]] and row["asks5"] == [[102.0, 3.0]]
    assert row["source_quality_status"] == "SAFE"
    assert audit["bbo_rows_read"] == 1
    assert audit["safe_causal_rows"] == 1
    assert audit["replay_grade_ready"] is True


def test_bbo_book_is_accepted_by_v21_reference_depth(tmp_path: Path) -> None:
    _write_bbo(tmp_path, [_bbo_row()])
    books, _audit = load_observed_books(tmp_path, coins={"BTC"})

    feats = _reference_depth_features(
        {"signal_ts_ms": 2_050, "direction": 1}, books["BTC"]
    )
    assert feats is not None
    imbalance, capacity = feats
    # bid_usd=500, ask_usd=306 -> imbalance = (500-306)/806 > 0, capacity = min = 306.
    assert capacity == 306.0
    assert imbalance > 0


def test_bbo_future_rows_excluded_by_causal_cutoff(tmp_path: Path) -> None:
    _write_bbo(tmp_path, [
        _bbo_row(received=2_010, exchange=2_000),
        _bbo_row(received=9_000, exchange=8_995, bid_px=101.0),
    ])
    books, audit = load_observed_books(tmp_path, coins={"BTC"}, as_of_ms=3_000)
    assert len(books.get("BTC", [])) == 1
    assert audit["future_rows_rejected"] == 1


def test_bbo_rejects_stale_or_crossed_top_of_book(tmp_path: Path) -> None:
    _write_bbo(tmp_path, [
        _bbo_row(received=100_000, exchange=10_000),   # drift 90 s > 30 s
        _bbo_row(received=2_010, exchange=2_000, ask_px=99.0),  # croise (ask<bid)
        _bbo_row(received=2_020, exchange=2_010, bid_sz=0.0),   # taille nulle
    ])
    books, audit = load_observed_books(tmp_path, coins={"BTC"})
    assert books.get("BTC", []) == []
    assert audit["invalid_rows"] >= 3
