"""[pépite 258] same-timestamp retention : 10 événements au même ts survivent à cache→disk→replay."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.dataset.same_timestamp_retention import StockHorodatage   # noqa: E402


def test_dix_memes_ts_survivent():
    s = StockHorodatage()
    for i in range(10):
        s.ajouter(1000, {"i": i})
    disque = s.serialiser()                        # cache -> disk
    rejoue = StockHorodatage.depuis_serialise(disque).rejouer()   # disk -> replay
    assert len(rejoue) == 10 and [e["i"] for e in rejoue] == list(range(10))


def test_ordre_stable_multi_ts():
    s = StockHorodatage()
    s.ajouter(2000, "b"); s.ajouter(1000, "a"); s.ajouter(2000, "c")
    assert s.rejouer() == ["a", "b", "c"]          # tri par (ts, rang d'arrivee)


def test_taille():
    s = StockHorodatage()
    s.ajouter(1, "x")
    assert s.taille() == 1
