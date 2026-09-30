"""[ALL #86] controller/executor separation : le controller détecte (sans état), l'executor possède le cycle de vie."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.controller_executor_separation import Controller, Executor, controller_sans_etat   # noqa: E402


def test_controller_produit_des_candidats_purs():
    c = Controller()
    cands = c.detecter([{"coin": "BTC"}, {"coin": "ETH"}])
    assert len(cands) == 2 and all(x["possede_position"] is False for x in cands)


def test_controller_na_pas_detat_de_position():
    assert controller_sans_etat(Controller()) is True


def test_executor_possede_le_cycle_de_vie():
    ex = Executor({"coin": "BTC"})
    ex.prendre_en_charge(0.5)
    assert ex.position == 0.5 and ex.etat == "RUNNING"
