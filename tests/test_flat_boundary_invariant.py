"""[pépite 294] flat-boundary invariant : à la fermeture, la somme algébrique des deltas de l'epoch revient à zéro."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.flat_boundary_invariant import verifier   # noqa: E402


def test_epoch_boucle_a_zero():
    r = verifier([+5.0, +3.0, -8.0])
    assert r["etat"] == "OK" and r["somme"] == 0.0


def test_residu_non_nul_violation():
    r = verifier([+5.0, -3.0])                      # résidu +2
    assert r["etat"] == "VIOLATION" and r["raison"] == "RESIDU_NON_NUL"


def test_delta_non_fini_fail_closed():
    assert verifier([float("inf"), -1.0])["etat"] == "VIOLATION"
    assert verifier([])["raison"] == "AUCUN_DELTA"
