"""[pépite 215] stable same-timestamp ordering : tie-break déterministe par seq, rien ne disparaît."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.stable_same_timestamp_ordering import trier   # noqa: E402


def test_meme_ts_ordre_par_seq():
    evts = [{"ts": 100.0, "seq": 3}, {"ts": 100.0, "seq": 1}, {"ts": 100.0, "seq": 2}]
    r = trier(evts)
    assert [e["seq"] for e in r["ordonnes"]] == [1, 2, 3] and r["n"] == 3   # aucun disparu


def test_ts_differents():
    r = trier([{"ts": 200.0, "seq": 1}, {"ts": 100.0, "seq": 5}])
    assert [e["ts"] for e in r["ordonnes"]] == [100.0, 200.0]


def test_invalide_rejete():
    r = trier([{"ts": 100.0}, {"ts": 100.0, "seq": 1}])
    assert r["n"] == 1 and r["rejetes"] == 1
