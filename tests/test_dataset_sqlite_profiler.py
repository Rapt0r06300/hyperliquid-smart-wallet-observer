from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from hl_observer.datasets.sqlite_profiler import (
    discover_sqlite_artifacts,
    profile_sqlite_database,
    profile_sqlite_workspace,
    write_sqlite_inventory,
)


def _database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE fills (id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT, closed_pnl REAL, secret TEXT)"
        )
        connection.execute(
            "CREATE TABLE positions (id INTEGER PRIMARY KEY, coin TEXT, size REAL)"
        )
        connection.execute(
            "INSERT INTO fills(coin, closed_pnl, secret) VALUES ('BTC', 1.25, 'NE_DOIT_JAMAIS_SORTIR')"
        )
        connection.execute("CREATE INDEX idx_fills_coin ON fills(coin)")
        connection.commit()
        connection.execute("ANALYZE")
        connection.commit()
    finally:
        connection.close()
    return path


def test_sqlite_profiler_ouvre_la_base_en_lecture_seule_et_decrit_le_schema(tmp_path: Path) -> None:
    path = _database(tmp_path / "data" / "hl_observer.sqlite3")
    before = path.stat().st_mtime_ns
    result = profile_sqlite_database(tmp_path, path, quick_check=True)
    after = path.stat().st_mtime_ns

    assert result["status"] == "READABLE_READ_ONLY"
    assert result["read_only_requested"] is True
    assert result["role"] == "PRIMARY"
    assert result["sqlite"]["quick_check"] == "ok"
    assert {"fills", "positions"}.issubset(result["schema"]["interesting_tables"])
    assert before == after
    assert "NE_DOIT_JAMAIS_SORTIR" not in json.dumps(result, ensure_ascii=False)


def test_sqlite_profiler_met_les_anciennes_bases_corrompues_en_quarantaine(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "data" / "hypersmart_simulation_session.sqlite3.corrupted-20260708"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"pas une vraie base")

    result = profile_sqlite_database(tmp_path, path)

    assert result["status"] == "QUARANTINED_NAME"
    assert result["opened"] is False
    assert result["quarantined_by_name"] is True


def test_sqlite_workspace_separe_bases_et_sidecars(tmp_path: Path) -> None:
    database = _database(tmp_path / "runtime" / "data" / "hypersmart_simulation_session.sqlite3")
    sidecar = Path(str(database) + "-wal")
    sidecar.write_bytes(b"wal factice pour inventaire")

    profile = profile_sqlite_workspace(tmp_path)

    assert profile["database_count"] == 1
    assert profile["readable_database_count"] == 1
    assert profile["sidecar_count"] == 1
    assert profile["economic_research_candidate_count"] == 1


def test_sqlite_inventory_ecrit_des_rapports_sans_contenu_des_lignes(tmp_path: Path) -> None:
    _database(tmp_path / "data" / "hl_observer.sqlite3")

    json_path, md_path, profile = write_sqlite_inventory(tmp_path)

    assert json_path.is_file()
    assert md_path.is_file()
    assert profile["read_only"] is True
    text = json_path.read_text(encoding="utf-8") + md_path.read_text(encoding="utf-8")
    assert "NE_DOIT_JAMAIS_SORTIR" not in text
    assert "READABLE_READ_ONLY" in text


def test_discovery_sqlite_repere_aussi_les_copies_corrompues_pour_les_quarantainer(tmp_path: Path) -> None:
    good = _database(tmp_path / "data" / "hl_observer.sqlite3")
    bad = tmp_path / "runtime" / "data" / "old.sqlite3.corrupted-20260708"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"x")

    found = discover_sqlite_artifacts(tmp_path)

    assert good in found
    assert bad in found
