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
            "CREATE TABLE fills (id INTEGER PRIMARY KEY, wallet_address TEXT, coin TEXT, closed_pnl REAL, raw_json TEXT)"
        )
        connection.execute(
            "INSERT INTO fills VALUES (1, '0xabc', 'BTC', 2.5, 'SECRET_PAYLOAD')"
        )
        connection.commit()
    finally:
        connection.close()


def test_catalogue_sqlite_research_est_ecrit_sans_payload_brut(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")

    json_path, md_path, catalog = write_catalog(tmp_path)

    assert catalog["readable_database_count"] == 1
    assert json_path.is_file()
    assert md_path.is_file()
    text = json_path.read_text(encoding="utf-8") + md_path.read_text(encoding="utf-8")
    assert "SECRET_PAYLOAD" not in text
    assert "fills" in text


def test_cli_sqlite_research_exporte_une_vue_fills_sure(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")

    code = main(["--root", str(tmp_path), "--export-table", "fills"])

    assert code == 0
    output = tmp_path / "runtime" / "reports" / "datasets" / "sqlite_views" / "fills.jsonl"
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
    assert payload["coin"] == "BTC"
    assert payload["closed_pnl"] == 2.5
    assert "raw_json" not in payload
    assert "SECRET_PAYLOAD" not in output.read_text(encoding="utf-8")


def test_cli_sqlite_research_refuse_un_workspace_absent(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path / "absent")]) == 2
