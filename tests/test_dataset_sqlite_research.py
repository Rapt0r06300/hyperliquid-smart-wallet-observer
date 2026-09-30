from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from hl_observer.ops.dataset_sqlite_research import main, write_catalog


def _database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE fills ("
            "id INTEGER PRIMARY KEY, wallet_address TEXT, coin TEXT, exchange_ts INTEGER, "
            "closed_pnl REAL, raw_json TEXT)"
        )
        connection.executemany(
            "INSERT INTO fills VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "0xabc", "BTC", 1_780_000_000_000, 2.5, "SECRET_PAYLOAD"),
                (2, "0xabc", "ETH", 1_780_000_001_000, -1.0, "SECRET_PAYLOAD_2"),
                (3, "0xdef", "BTC", 1_780_000_002_000, 4.0, "SECRET_PAYLOAD_3"),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def test_catalogue_sqlite_research_est_ecrit_sans_payload_brut(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")

    json_path, md_path, catalog = write_catalog(tmp_path)

    assert catalog["readable_database_count"] == 1
    assert catalog["schema"] == "hypersmart.sqlite_research_catalog.v2"
    assert json_path.is_file()
    assert md_path.is_file()
    text = json_path.read_text(encoding="utf-8") + md_path.read_text(encoding="utf-8")
    assert "SECRET_PAYLOAD" not in text
    assert "fills" in text
    assert "exchange_ts" in text


def test_cli_sqlite_research_exporte_une_vue_fills_sure(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")

    code = main(["--root", str(tmp_path), "--export-table", "fills", "--limit", "1"])

    assert code == 0
    output = tmp_path / "runtime" / "reports" / "datasets" / "sqlite_views" / "fills.jsonl"
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
    assert payload["coin"] == "BTC"
    assert payload["closed_pnl"] == 2.5
    assert "raw_json" not in payload
    assert "SECRET_PAYLOAD" not in output.read_text(encoding="utf-8")


def test_cli_sqlite_research_filtre_periode_coin_et_wallet(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")

    code = main(
        [
            "--root",
            str(tmp_path),
            "--export-table",
            "fills",
            "--start-ms",
            "1780000001500",
            "--end-ms",
            "1780000002500",
            "--coin",
            "btc",
            "--wallet",
            "0xdef",
        ]
    )

    assert code == 0
    output = tmp_path / "runtime" / "reports" / "datasets" / "sqlite_views" / "fills.jsonl"
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["id"] == 3
    assert rows[0]["coin"] == "BTC"


def test_cli_sqlite_research_refuse_une_periode_inversee(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")

    code = main(
        [
            "--root",
            str(tmp_path),
            "--export-table",
            "fills",
            "--start-ms",
            "20",
            "--end-ms",
            "10",
        ]
    )

    assert code == 2


def test_cli_sqlite_research_refuse_un_workspace_absent(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path / "absent")]) == 2
