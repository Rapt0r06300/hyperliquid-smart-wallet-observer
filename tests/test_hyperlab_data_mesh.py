"""[Bloc 32] Catalogue Data Mesh SQLite + migrations idempotentes."""
import os

from hl_observer.hyperlab import data_mesh_catalog as dm


def test_bootstrap_et_migrations_idempotentes(tmp_path):
    db = os.path.join(str(tmp_path), "mesh.db")
    conn = dm.ouvrir(db)
    r1 = dm.bootstrap(conn, ts=1000.0)
    assert r1["appliquees"] == ["0001_init"]
    # relancer : rien de reapplique
    r2 = dm.bootstrap(conn, ts=1001.0)
    assert r2["appliquees"] == []
    assert "0001_init" in dm.version_schema(conn)


def test_enregistrer_et_lister(tmp_path):
    db = os.path.join(str(tmp_path), "mesh.db")
    conn = dm.ouvrir(db)
    dm.bootstrap(conn, ts=1000.0)
    dm.enregistrer_dataset(conn, name="bybit_silver", etage="silver", path="/x/silver",
                           n_rows=3, venue="bybit", content_hash="abc", ts=1002.0)
    dm.enregistrer_dataset(conn, name="gold", etage="gold", path="/x/gold", n_rows=3, ts=1003.0)
    tous = dm.lister_datasets(conn)
    assert len(tous) == 2
    silver = dm.lister_datasets(conn, etage="silver")
    assert len(silver) == 1 and silver[0]["venue"] == "bybit" and silver[0]["n_rows"] == 3


def test_migration_additionnelle_tracee(tmp_path):
    db = os.path.join(str(tmp_path), "mesh.db")
    conn = dm.ouvrir(db)
    dm.bootstrap(conn, ts=1000.0)
    migr = [("0002_add_source", "ALTER TABLE datasets ADD COLUMN source TEXT;", "colonne source")]
    a = dm.appliquer_migrations(conn, migr, ts=1004.0)
    assert a["appliquees"] == ["0002_add_source"]
    # idempotent
    b = dm.appliquer_migrations(conn, migr, ts=1005.0)
    assert b["appliquees"] == []
    cols = [r[1] for r in conn.execute("PRAGMA table_info(datasets)")]
    assert "source" in cols
