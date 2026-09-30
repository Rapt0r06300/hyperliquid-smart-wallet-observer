"""[COPY-VAULT #67] flip as two operations : long->short = fermer l'ancien puis ouvrir le nouveau."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.flip_as_two_operations import decomposer, FERMER, OUVRIR   # noqa: E402


def test_vrai_flip_deux_operations():
    r = decomposer(2.0, -1.5)                                 # long 2 -> short 1.5
    assert r["flip"] is True and len(r["operations"]) == 2
    assert r["operations"][0] == {"op": FERMER, "quantite": 2.0}
    assert r["operations"][1] == {"op": OUVRIR, "quantite": 1.5}


def test_meme_cote_est_un_resize():
    r = decomposer(2.0, 3.0)                                  # long -> long plus gros
    assert r["flip"] is False and r["operations"][0]["op"] == OUVRIR


def test_entree_invalide():
    assert decomposer(None, -1.5)["operations"] == "UNMEASURABLE"
