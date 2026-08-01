"""[lot2 #96] strategy removal purge : la suppression purge le state, aucune position fantôme."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.strategy_removal_purge import RegistreStrategies   # noqa: E402


def test_purge_efface_le_state():
    r = RegistreStrategies()
    r.enregistrer("strat1", positions={"BTC": 0.5}, config={"levier": 3})
    assert r.etat("strat1") is not None
    out = r.supprimer("strat1")
    assert out["purge"] is True and out["aucun_fantome"] is True and r.etat("strat1") is None


def test_suppression_inexistante():
    assert RegistreStrategies().supprimer("zzz")["purge"] is False


def test_state_isole_par_copie():
    r = RegistreStrategies()
    r.enregistrer("s", positions={"BTC": 0.5})
    r.etat("s")["positions"]["BTC"] = 999                 # mutation de la copie
    assert r.etat("s")["positions"]["BTC"] == 0.5
