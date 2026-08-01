"""[lot2 #89] batch-submit maker layers : couches estampillées d'un timestamp/snapshot partagé."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.batch_submit_maker_layers import preparer_batch   # noqa: E402


def test_timestamp_partage():
    couches = [{"prix": 100.0, "taille": 1.0}, {"prix": 99.5, "taille": 2.0}]
    r = preparer_batch(couches, ts_ms=1000.0, snapshot_id="snap1")
    assert r["ok"] is True and r["n"] == 2
    assert all(c["ts_ms"] == 1000.0 and c["snapshot_id"] == "snap1" for c in r["couches"])


def test_couche_invalide_ignoree():
    r = preparer_batch([{"prix": 100.0, "taille": 0.0}, {"prix": 99.5, "taille": 2.0}],
                       ts_ms=1000.0, snapshot_id="s")
    assert r["n"] == 1


def test_ts_manquant_refuse():
    assert preparer_batch([{"prix": 100.0, "taille": 1.0}], ts_ms=None, snapshot_id="s")["ok"] is False
