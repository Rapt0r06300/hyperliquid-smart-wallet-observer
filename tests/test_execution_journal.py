"""[ARB #48] execution journal : transitions immuables DETECTED->...->CLOSED, sauts d'étape refusés."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import execution_journal as EJ   # noqa: E402


def test_chaine_valide():
    j = EJ.JournalExecution()
    assert j.etat("ep1") == EJ.DETECTED
    for vers in (EJ.VALIDATED, EJ.RESERVED, EJ.SUBMITTED_A, EJ.SUBMITTED_B, EJ.HEDGED, EJ.CLOSED):
        assert j.transition("ep1", vers)["ok"] is True
    assert j.etat("ep1") == EJ.CLOSED


def test_saut_detape_refuse():
    j = EJ.JournalExecution()
    r = j.transition("ep1", EJ.CLOSED)                    # DETECTED -> CLOSED interdit
    assert r["ok"] is False and r["raison"] == "TRANSITION_INTERDITE"
    assert j.etat("ep1") == EJ.DETECTED                   # état inchangé


def test_historique_immuable_et_append_only():
    j = EJ.JournalExecution()
    j.transition("ep1", EJ.VALIDATED)
    h = j.historique("ep1")
    h.append(("HACK", ""))                                # mutation de la copie...
    assert j.historique("ep1")[-1][0] == EJ.VALIDATED     # ...n'affecte pas le journal
