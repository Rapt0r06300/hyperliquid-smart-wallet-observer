"""[lot2 #83] transaction costs dans le maker target price : le prix cible intègre déjà les frais."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.transaction_costs_in_target import prix_cible   # noqa: E402


def test_achat_vise_plus_bas():
    r = prix_cible(100.0, "ACHAT", cout_bps=10.0)        # -10 bps
    assert r["prix_cible"] == 99.9


def test_vente_vise_plus_haut():
    r = prix_cible(100.0, "VENTE", cout_bps=10.0)        # +10 bps
    assert r["prix_cible"] == 100.1


def test_prix_invalide():
    assert prix_cible(0.0, "ACHAT", cout_bps=10.0)["prix_cible"] == "UNMEASURABLE"
