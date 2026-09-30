"""[pépite 211] zombie-order : annulé localement mais encore OPEN/PARTIAL à la source."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.zombie_order_detector import detecter   # noqa: E402


def test_zombie_detecte():
    r = detecter(["o1", "o2"], {"o1": "OPEN", "o2": "CANCELED"})
    assert r["zombies"] == ["o1"] and r["a_des_zombies"] is True


def test_partial_est_zombie():
    assert detecter(["o1"], {"o1": "PARTIALLY_FILLED"})["zombies"] == ["o1"]


def test_aucun_zombie():
    assert detecter(["o1"], {"o1": "CANCELED"})["a_des_zombies"] is False
