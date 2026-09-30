"""[pépite 291] position epoch ID : chaque cycle FLAT→OPEN→...→FLAT reçoit une identité unique."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.position_epoch_id import TraceurEpoch   # noqa: E402


def test_ouverture_incremente():
    t = TraceurEpoch()
    assert t.observer(5.0)["transition"] == "OUVERTURE"
    assert t.epoch_courant() == 1


def test_cycle_complet_puis_nouveau():
    t = TraceurEpoch()
    t.observer(5.0)                        # epoch 1 ouvert
    assert t.observer(0.0)["transition"] == "FERMETURE" and t.epoch_courant() is None
    assert t.observer(3.0)["epoch_id"] == 2   # nouvel epoch


def test_pas_de_transition_en_cours():
    t = TraceurEpoch()
    t.observer(5.0)
    assert t.observer(6.0)["transition"] == "AUCUNE"
