"""[ALL lot2 #22] invalidation fee-cache : cache invalidé dès un changement de tier."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.fees_model.fee_cache_invalidation import CacheFrais   # noqa: E402


def test_invalidation_au_changement_tier():
    c = CacheFrais()
    c.poser("HL", taux_bps=3.0, tier="T1")
    assert c.obtenir("HL") == 3.0
    r = c.signaler_tier("HL", tier_courant="T2")         # tier a changé
    assert r["invalide"] is True and c.obtenir("HL") is None


def test_tier_inchange_conserve():
    c = CacheFrais()
    c.poser("HL", taux_bps=3.0, tier="T1")
    assert c.signaler_tier("HL", tier_courant="T1")["invalide"] is False
    assert c.obtenir("HL") == 3.0


def test_pas_de_cache():
    assert CacheFrais().signaler_tier("HL", tier_courant="T1")["raison"] == "PAS_DE_CACHE"
