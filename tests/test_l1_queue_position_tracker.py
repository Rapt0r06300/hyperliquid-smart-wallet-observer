"""[lot2 #86] L1 queue-position tracker : le volume devant nous se consomme avant qu'on soit rempli."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.l1_queue_position_tracker import TrackerQueueL1   # noqa: E402


def test_volume_devant_consomme_dabord():
    t = TrackerQueueL1(volume_devant=5.0)
    t.entrer(2.0)
    r = t.trade_consomme(5.0)                             # consomme les 5 devant, ne nous remplit pas
    assert r["notre_fill"] == 0.0 and t.position() == 0.0


def test_fill_apres_la_queue():
    t = TrackerQueueL1(volume_devant=3.0)
    t.entrer(2.0)
    r = t.trade_consomme(4.0)                             # 3 devant + 1 pour nous
    assert r["notre_fill"] == 1.0 and r["reste_notre_qte"] == 1.0


def test_volume_invalide():
    t = TrackerQueueL1(volume_devant=3.0)
    assert t.trade_consomme(-1.0)["ok"] is False
