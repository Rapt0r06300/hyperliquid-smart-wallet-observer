"""[ARB lot2 #3] quantity-reduction amend : réduction de qté préserve la queue, changement de prix la détruit."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.quantity_reduction_amend import effet_sur_queue   # noqa: E402


def test_reduction_preserve():
    r = effet_sur_queue(prix_avant=100.0, prix_apres=100.0, qte_avant=1.0, qte_apres=0.6)
    assert r["preserve_queue"] is True and r["type"] == "REDUCTION_QTE"


def test_changement_prix_detruit():
    r = effet_sur_queue(prix_avant=100.0, prix_apres=100.1, qte_avant=1.0, qte_apres=1.0)
    assert r["preserve_queue"] is False and r["type"] == "CHANGEMENT_PRIX"


def test_augmentation_recule():
    r = effet_sur_queue(prix_avant=100.0, prix_apres=100.0, qte_avant=1.0, qte_apres=1.5)
    assert r["preserve_queue"] is False and r["type"] == "AUGMENTATION_QTE"
