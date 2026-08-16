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
        connection.executemany(
            "INSERT INTO fills VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "0xabc", "BTC", 1_780_000_000_000, "B", 100.0, 2.0, 3.5, 0.1, "SECRET_RAW_PAYLOAD"),
                (2, "0xabc", "ETH", 1_780_000_001_000, "S", 200.0, 1.0, -1.5, 0.2, "SECRET_RAW_PAYLOAD_2"),
                (3, "0xdef", "BTC", 1_780_000_002_000, "B", 101.0, 3.0, 4.0, 0.1, "SECRET_RAW_PAYLOAD_3"),
            ],
        )
        connection.execute("CREATE INDEX idx_fills_exchange_ts ON fills(exchange_ts)")
        connection.execute("CREATE INDEX idx_fills_coin ON fills(coin)")
        connection.execute(
            "CREATE TABLE paper_trades ("
            "id INTEGER PRIMARY KEY, family TEXT, coin TEXT, status TEXT, net_pnl_usd REAL, opened_at_ms INTEGER)"
        )
        connection.executemany(
            "INSERT INTO paper_trades VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "copy_vault", "BTC", "CLOSED", 2.0, 1_780_000_000_000),
                (2, "lead_lag", "BTC", "CLOSED", -0.5, 1_780_000_001_000),
            ],
        )
        connection.execute(
            "CREATE TABLE raw_events (id INTEGER PRIMARY KEY, response_payload_json TEXT)"
        )
        connection.execute("INSERT INTO raw_events VALUES (1, 'PRIVATE_RAW_EVENT')")
        connection.commit()
    finally:
        connection.close()
    return path


def test_catalog_sqlite_research_ne_propose_que_les_colonnes_sures_et_decrit_les_filtres(tmp_path: Path) -> None:
    path = _database(tmp_path / "data" / "hl_observer.sqlite3")

    catalog = build_sqlite_research_catalog(tmp_path)

    assert catalog["schema"] == "hypersmart.sqlite_research_catalog.v2"
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
    assert table["time_filter_column"] == "exchange_ts"
    assert table["coin_filter_supported"] is True
    assert table["wallet_filter_column"] == "wallet_address"
    assert "raw_events" not in catalog["table_sources"]
    assert path.stat().st_size > 0


def test_iterateur_sqlite_stream_des_fills_sans_raw_json(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")

    rows = list(iter_research_rows(tmp_path, "fills"))

    assert len(rows) == 3
    assert [row["exchange_ts"] for row in rows] == sorted(row["exchange_ts"] for row in rows)
    assert rows[0]["coin"] == "BTC"
    assert rows[0]["closed_pnl"] == 3.5
    assert all("raw_json" not in row for row in rows)
    assert "SECRET_RAW_PAYLOAD" not in repr(rows)
    assert rows[0]["_source_database"].endswith("hl_observer.sqlite3")


def test_iterateur_filtre_periode_coin_et_wallet_sans_concatener_les_valeurs_sql(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")

    rows = list(
        iter_research_rows(
            tmp_path,
            "fills",
            start_ms=1_780_000_001_500,
            end_ms=1_780_000_002_500,
            coin="btc",
            wallet="0xdef",
        )
    )

    assert len(rows) == 1
    assert rows[0]["id"] == 3
    assert rows[0]["coin"] == "BTC"
    assert rows[0]["wallet_address"] == "0xdef"


def test_iterateur_filtre_famille_sur_les_trades_paper_historiques(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")

    rows = list(iter_research_rows(tmp_path, "paper_trades", family="copy_vault"))

    assert len(rows) == 1
    assert rows[0]["family"] == "copy_vault"
    assert rows[0]["net_pnl_usd"] == 2.0


def test_iterateur_refuse_une_table_hors_allowlist_et_une_periode_non_supportee(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")
    with pytest.raises(ValueError):
        list(iter_research_rows(tmp_path, "raw_events"))
    with pytest.raises(ValueError):
        list(iter_research_rows(tmp_path, "wallet_scores", start_ms=1))
    with pytest.raises(ValueError):
        list(iter_research_rows(tmp_path, "fills", start_ms=10, end_ms=1))


def test_export_jsonl_derive_reste_local_filtrable_et_sans_colonne_brute(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")
    output = tmp_path / "derived" / "fills.jsonl"

    result = stream_table_to_jsonl(
        tmp_path,
        "fills",
        output,
        start_ms=1_780_000_001_000,
        coin="BTC",
    )

    assert result["rows"] == 1
    assert result["filters"]["coin"] == "BTC"
    text = output.read_text(encoding="utf-8")
    assert '"id": 3' in text
    assert "SECRET_RAW_PAYLOAD" not in text


def test_bases_corrompues_ne_sont_jamais_sources_de_recherche(tmp_path: Path) -> None:
    good = _database(tmp_path / "data" / "hl_observer.sqlite3")
    bad = tmp_path / "runtime" / "data" / "old.sqlite3.corrupted-20260708"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"not sqlite")

    sources = safe_sqlite_databases(tmp_path)

    assert good in sources
    assert bad not in sources
