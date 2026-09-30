"""[ARB #36] failure-specific retry : le remède dépend de la catégorie (timeout->réconcilier, etc.)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import failure_specific_retry as FSR   # noqa: E402


def test_remedes_par_categorie():
    assert FSR.politique_retry("TIMEOUT")["action"] == FSR.RECONCILIER
    assert FSR.politique_retry("INVALID_QUANTITY min_notional")["action"] == FSR.RECALCULER
    assert FSR.politique_retry("STALE price")["action"] == FSR.ABANDONNER


def test_connector_attend():
    assert FSR.politique_retry("CONNECTOR disconnect")["action"] == FSR.ATTENDRE_ET_REESSAYER


def test_inconnu_reconcilie_par_prudence():
    assert FSR.politique_retry("banana")["action"] == FSR.RECONCILIER
