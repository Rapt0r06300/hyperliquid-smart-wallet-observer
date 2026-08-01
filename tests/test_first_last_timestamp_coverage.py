"""[pépite 260] first/last timestamp coverage : première/dernière observation et couverture réelle."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.dataset.first_last_timestamp_coverage import CouvertureDataset   # noqa: E402


def test_couverture_partielle():
    c = CouvertureDataset()
    for ts in (300.0, 500.0, 800.0):
        c.observer(ts)
    r = c.resume(0.0, 1000.0)                       # span observe 500 / attendu 1000
    assert r["premier"] == 300.0 and r["dernier"] == 800.0 and r["couverture"] == 0.5


def test_aucune_observation_couverture_zero():
    assert CouvertureDataset().resume(0.0, 1000.0)["couverture"] == 0.0


def test_ts_invalide_ignore():
    c = CouvertureDataset()
    c.observer(float("nan")); c.observer(100.0)
    assert c.resume(0.0, 100.0)["n"] == 1
