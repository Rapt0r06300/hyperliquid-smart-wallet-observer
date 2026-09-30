"""[pépite 210] missing-local-order : ordre actif source absent de notre state machine."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.missing_local_order_detector import detecter   # noqa: E402


def test_manquant_detecte():
    r = detecter(["o1"], ["o1", "o2"])
    assert r["manquants_en_local"] == ["o2"] and r["a_des_manquants"] is True


def test_coherent():
    assert detecter(["o1", "o2"], ["o1", "o2"])["a_des_manquants"] is False


def test_local_en_trop_ignore():
    assert detecter(["o1", "o3"], ["o1"])["manquants_en_local"] == []
