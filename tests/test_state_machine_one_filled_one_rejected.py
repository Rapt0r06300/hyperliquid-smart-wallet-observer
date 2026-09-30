"""[ARB #46] state machine one-filled/one-rejected : cas explicite -> RESIDUAL_UNHEDGED + unwind/retry."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import state_machine_one_filled_one_rejected as SM   # noqa: E402


def test_une_remplie_une_rejetee():
    r = SM.transition("FILLED", "REJECTED")
    assert r["etat"] == SM.RESIDUAL_UNHEDGED and r["action"] == SM.UNWIND_OU_RETRY_HEDGE
    # symétrique
    assert SM.transition("REJECTED", "FILLED")["etat"] == SM.RESIDUAL_UNHEDGED


def test_deux_remplies_hedged_deux_rejetees_flat():
    assert SM.transition("FILLED", "FILLED")["etat"] == SM.HEDGED
    assert SM.transition("REJECTED", "REJECTED")["etat"] == SM.FLAT


def test_statut_non_reconnu_pas_dexception():
    r = SM.transition("FILLED", "banana")
    assert r["etat"] == SM.EN_ATTENTE and r["action"] == SM.REVALIDER
