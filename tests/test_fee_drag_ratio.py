"""[pépite 284] fee-drag ratio : un leader proche de zéro avant fees est une mauvaise cible de réplication."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.fee_drag_ratio import fee_drag   # noqa: E402


def test_bonne_cible():
    r = fee_drag(fees=10.0, edge_brut=100.0)      # ratio 0.1, edge net 90
    assert r["ratio"] == 0.1 and r["mauvaise_cible"] is False and r["edge_net_estime"] == 90.0


def test_fees_mangent_edge():
    r = fee_drag(fees=95.0, edge_brut=90.0)       # ratio > 1
    assert r["mauvaise_cible"] is True


def test_edge_brut_non_positif():
    assert fee_drag(10.0, 0.0)["ratio"] == "UNMEASURABLE"
