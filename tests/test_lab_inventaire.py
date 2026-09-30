"""[LAB α] lab_inventaire : découverte + lecture multi-format (JSONL/JSON/CSV/GZIP/ZIP/SQLite) + LZ4 honnête."""

import gzip
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops.lab_inventaire import (   # noqa: E402
    inventorier, lire_lignes, bundles_depuis_fichier, LabFormatBloque)


def _make(root):
    d = root / "runtime" / "data"
    d.mkdir(parents=True)
    (d / "ticks.jsonl").write_text("\n".join(json.dumps(
        {"coin": "BTC", "px": 60000, "sz": 0.3, "signe": 1, "ts_ms": 1_700_000_000_000 + i,
         "book": {"asks": [[60010, 5]], "bids": [[59990, 5]]}}) for i in range(5)), encoding="utf-8")
    (d / "list.json").write_text(json.dumps([{"coin": "ETH", "px": 3000}]), encoding="utf-8")
    (d / "ofi.csv").write_text("coin,px\nBTC,60000\nETH,3000\n", encoding="utf-8")
    with gzip.open(d / "t.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps({"coin": "SOL", "px": 150}) + "\n")
    with zipfile.ZipFile(d / "a.zip", "w") as z:
        z.writestr("inner.jsonl", json.dumps({"coin": "XRP", "px": 0.5}) + "\n")
    con = sqlite3.connect(str(d / "m.sqlite"))
    con.execute("CREATE TABLE t(coin TEXT, px REAL)")
    con.execute("INSERT INTO t VALUES('BTC', 60000)")
    con.commit()
    con.close()
    return d


def test_inventaire_decouvre_et_classe(tmp_path):
    _make(tmp_path)
    inv = inventorier(tmp_path)
    formats = {f["format"] for f in inv["fichiers"]}
    assert {"JSONL", "JSON", "CSV", "GZIP", "ZIP", "SQLITE"} <= formats
    assert inv["lisibles"] >= 6 and all("hash" in f for f in inv["fichiers"])


def test_lecteurs_par_format(tmp_path):
    d = _make(tmp_path)
    assert next(iter(lire_lignes(d / "ticks.jsonl")))["coin"] == "BTC"
    assert next(iter(lire_lignes(d / "ofi.csv")))["px"] == 60000.0
    assert next(iter(lire_lignes(d / "m.sqlite")))["coin"] == "BTC"
    assert next(iter(lire_lignes(d / "a.zip")))["coin"] == "XRP"


def test_bundles_et_lz4_bloque(tmp_path):
    d = _make(tmp_path)
    b = bundles_depuis_fichier(d / "ticks.jsonl")
    assert len(b) == 5 and "evenements" in b[0]
    (tmp_path / "x.lz4").write_bytes(b"\x00\x01\x02")
    bloque = False
    try:
        list(lire_lignes(tmp_path / "x.lz4"))
    except LabFormatBloque:
        bloque = True
    except Exception:            # lz4 installé mais contenu invalide -> aussi un échec honnête
        bloque = True
    assert bloque
