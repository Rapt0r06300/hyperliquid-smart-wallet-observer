from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hl_observer.datasets.sqlite_research_source import (
    build_sqlite_research_catalog,
    iter_research_rows,
    safe_sqlite_databases,
    stream_table_to_jsonl,
)


def _database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE fills ("
            "id INTEGER PRIMARY KEY, wallet_address TEXT, coin TEXT, exchange_ts INTEGER, "
            "side TEXT, price REAL, size REAL, closed_pnl REAL, fee REAL, raw_json TEXT)"
        )
        connection.execute(
            "INSERT INTO fills VALUES (1, '0xabc', 'BTC', 1780000000000, 'B', 100.0, 2.0, 3.5, 0.1, 'SECRET_RAW_PAYLOAD')"
        )
        connection.execute(
            "CREATE TABLE raw_events (id INTEGER PRIMARY KEY, response_payload_json TEXT)"
        )
        connection.execute("INSERT INTO raw_events VALUES (1, 'PRIVATE_RAW_EVENT')")
        connection.commit()
    finally:
        connection.close()
    return path


def test_catalog_sqlite_research_ne_propose_que_les_colonnes_sures(tmp_path: Path) -> None:
    path = _database(tmp_path / "data" / "hl_observer.sqlite3")

    catalog = build_sqlite_research_catalog(tmp_path)

    assert catalog["read_only"] is True
    assert catalog["raw_json_columns_excluded"] is True
    assert catalog["readable_database_count"] == 1
    assert "fills" in catalog["table_sources"]
    table = next(
        item
        for database in catalog["databases"]
        for item in database["tables"]
        if item["name"] == "fills"
    )
    assert "closed_pnl" in table["safe_columns"]
    assert "raw_json" not in table["safe_columns"]
    assert "raw_events" not in catalog["table_sources"]
    assert path.stat().st_size > 0


def test_iterateur_sqlite_stream_des_fills_sans_raw_json(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")

    rows = list(iter_research_rows(tmp_path, "fills"))

    assert len(rows) == 1
    assert rows[0]["coin"] == "BTC"
    assert rows[0]["closed_pnl"] == 3.5
    assert "raw_json" not in rows[0]
    assert "SECRET_RAW_PAYLOAD" not in repr(rows[0])
    assert rows[0]["_source_database"].endswith("hl_observer.sqlite3")


def test_iterateur_refuse_une_table_hors_allowlist(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")
    with pytest.raises(ValueError):
        list(iter_research_rows(tmp_path, "raw_events"))


def test_export_jsonl_derive_reste_local_et_sans_colonne_brute(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")
    output = tmp_path / "derived" / "fills.jsonl"

    result = stream_table_to_jsonl(tmp_path, "fills", output)

    assert result["rows"] == 1
    text = output.read_text(encoding="utf-8")
    assert "BTC" in text
    assert "SECRET_RAW_PAYLOAD" not in text


def test_bases_corrompues_ne_sont_jamais_sources_de_recherche(tmp_path: Path) -> None:
    good = _database(tmp_path / "data" / "hl_observer.sqlite3")
    bad = tmp_path / "runtime" / "data" / "old.sqlite3.corrupted-20260708"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"not sqlite")

    sources = safe_sqlite_databases(tmp_path)

    assert good in sources
    assert bad not in sources
