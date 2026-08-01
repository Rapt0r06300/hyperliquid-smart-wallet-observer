"""[pépite 297] copyability erosion monitor : si (leader edge − notre edge) augmente durablement, vault déclassé."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.copyability_erosion_monitor import MoniteurErosion   # noqa: E402


def test_erosion_declasse():
    m = MoniteurErosion(min_echantillons=4)
    for leader, notre in ((1.0, 0.0), (1.0, 0.0), (5.0, 0.0), (5.0, 0.0)):   # gaps 1,1,5,5
        m.observer(leader, notre)
    v = m.verdict()
    assert v["declasse"] is True and v["hausse"] == 4.0


def test_stable_pas_de_declassement():
    m = MoniteurErosion(min_echantillons=4)
    for _ in range(4):
        m.observer(2.0, 0.0)                     # gaps stables à 2
    assert m.verdict()["declasse"] is False


def test_donnees_insuffisantes():
    m = MoniteurErosion(min_echantillons=4)
    m.observer(5.0, 0.0); m.observer(5.0, 0.0)
    assert m.verdict()["raison"] == "DONNEES_INSUFFISANTES"
