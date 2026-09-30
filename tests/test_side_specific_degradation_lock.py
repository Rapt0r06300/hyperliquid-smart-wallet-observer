"""[ALL #96] side-specific degradation lock : verrouiller seulement le côté qui se dégrade, pas l'autre."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.side_specific_degradation_lock import VerrouCote   # noqa: E402


def test_verrou_uniquement_le_cote_fautif():
    v = VerrouCote(seuil=2, fenetre_ms=60_000.0, duree_lock_ms=300_000.0)
    v.enregistrer_degradation("BTC", "LONG", now_ms=0.0)
    v.enregistrer_degradation("BTC", "LONG", now_ms=1000.0)   # 2e -> lock LONG
    assert v.autorise("BTC", "LONG", now_ms=2000.0)["autorise"] is False
    assert v.autorise("BTC", "SHORT", now_ms=2000.0)["autorise"] is True   # SHORT reste libre


def test_lock_expire():
    v = VerrouCote(seuil=1, duree_lock_ms=300_000.0)
    v.enregistrer_degradation("ETH", "SHORT", now_ms=0.0)
    assert v.autorise("ETH", "SHORT", now_ms=400_000.0)["autorise"] is True


def test_cote_normalise():
    v = VerrouCote(seuil=1)
    v.enregistrer_degradation("BTC", "BUY", now_ms=0.0)   # BUY == LONG
    assert v.autorise("BTC", "LONG", now_ms=100.0)["autorise"] is False
