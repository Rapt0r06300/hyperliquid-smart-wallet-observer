"""[pépite 209] ghost-order detector : ordre local actif absent de la source autoritaire = fantôme."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.ghost_order_detector import detecter   # noqa: E402


def test_fantome_detecte():
    r = detecter(["o1", "o2"], ["o2"])                   # o1 actif chez nous, absent source
    assert r["fantomes"] == ["o1"] and r["a_des_fantomes"] is True


def test_aucun_fantome():
    assert detecter(["o1"], ["o1", "o2"])["a_des_fantomes"] is False   # o2 orphelin, pas fantome


def test_purge_liste():
    r = detecter(["a", "b"], [])
    assert set(r["a_purger"]) == {"a", "b"} and r["n"] == 2
