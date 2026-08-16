from __future__ import annotations

import sqlite3
from pathlib import Path

from hl_observer.ops.dataset_sqlite_inventory import main


def _database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE fills (id INTEGER PRIMARY KEY, coin TEXT)")
        connection.execute("INSERT INTO fills VALUES (1, 'BTC')")
        connection.commit()
    finally:
        connection.close()
    return path


def test_cli_sqlite_inventory_ecrit_les_deux_rapports(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")

    code = main(["--root", str(tmp_path)])

    assert code == 0
    assert (tmp_path / "runtime" / "reports" / "datasets" / "SQLITE_INVENTORY.json").is_file()
    assert (tmp_path / "runtime" / "reports" / "datasets" / "SQLITE_INVENTORY.md").is_file()


def test_cli_sqlite_inventory_refuse_un_workspace_absent(tmp_path: Path) -> None:
    code = main(["--root", str(tmp_path / "absent")])
    assert code == 2


def test_cli_sqlite_inventory_ne_tente_pas_d_ouvrir_une_copie_corrompue(tmp_path: Path) -> None:
    bad = tmp_path / "runtime" / "data" / "old.sqlite3.corrupted-20260708"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"not sqlite")

    code = main(["--root", str(tmp_path)])

    assert code == 0
    report = (tmp_path / "runtime" / "reports" / "datasets" / "SQLITE_INVENTORY.json").read_text(
        encoding="utf-8"
    )
    assert "QUARANTINED_NAME" in report
