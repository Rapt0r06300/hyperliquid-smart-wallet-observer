"""[ALL lot2 #21] account-specific fees : taux du compte prioritaire sur le barème public."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.fees_model.account_specific_fees import taux_effectif_bps   # noqa: E402


def test_taux_compte_prioritaire():
    r = taux_effectif_bps(taux_compte_bps=2.0, taux_public_bps=5.0)
    assert r["taux_bps"] == 2.0 and r["source"] == "COMPTE"


def test_fallback_public():
    r = taux_effectif_bps(taux_compte_bps=None, taux_public_bps=5.0)
    assert r["taux_bps"] == 5.0 and r["source"] == "PUBLIC"


def test_aucun_non_mesurable():
    r = taux_effectif_bps()
    assert r["taux_bps"] == "UNMEASURABLE"               # jamais 0 suppose
