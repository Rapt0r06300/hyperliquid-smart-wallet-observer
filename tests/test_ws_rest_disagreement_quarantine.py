"""[COPY-VAULT lot2 #50] WS/REST quarantine : aucun OPEN/ADD tant qu'une divergence WS/REST n'est pas résolue."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.ws_rest_disagreement_quarantine import Quarantaine   # noqa: E402


def test_divergence_met_en_quarantaine():
    q = Quarantaine(tolerance=1e-6)
    r = q.evaluer("vaultA", valeur_ws=1.0, valeur_rest=1.5)
    assert r["quarantaine"] is True
    assert q.peut_open_add("vaultA")["peut_open_add"] is False
    assert q.peut_open_add("vaultA")["peut_reduce"] is True    # réduire reste permis


def test_accord_leve_la_quarantaine():
    q = Quarantaine()
    q.evaluer("vaultA", valeur_ws=1.0, valeur_rest=1.5)
    q.evaluer("vaultA", valeur_ws=1.0, valeur_rest=1.0)
    assert q.peut_open_add("vaultA")["peut_open_add"] is True


def test_donnee_manquante_quarantaine():
    q = Quarantaine()
    assert q.evaluer("vaultA", valeur_ws=None, valeur_rest=1.0)["quarantaine"] is True
