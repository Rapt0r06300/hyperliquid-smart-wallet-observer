"""[pépite 222] filled quantity lot invariant : un partial fill simulé respecte le quantum de l'instrument."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.filled_quantity_lot_invariant import respecte_lot, arrondir_au_lot   # noqa: E402


def test_multiple_du_lot():
    assert respecte_lot(0.3, lot_size=0.1)["valide"] is True
    assert respecte_lot(0.37, lot_size=0.1)["valide"] is False


def test_arrondi_au_lot():
    assert arrondir_au_lot(0.37, lot_size=0.1) == 0.3


def test_entree_invalide():
    assert respecte_lot(0.3, lot_size=0.0)["valide"] is False
