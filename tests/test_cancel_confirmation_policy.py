"""[ARB lot2 #11] cancel-confirmation policy : confirmation avant remplacement selon la venue."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.cancel_confirmation_policy import doit_confirmer   # noqa: E402


def test_venue_exige_confirmation():
    assert doit_confirmer("HL")["confirmer"] is True


def test_venue_remplacement_direct():
    assert doit_confirmer("BINANCE")["confirmer"] is False


def test_venue_inconnue_prudence():
    r = doit_confirmer("KRAKEN")
    assert r["confirmer"] is True and r["raison"] == "VENUE_INCONNUE_PRUDENCE"
