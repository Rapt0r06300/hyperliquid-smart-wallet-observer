"""[DATA lot2 #33] missing-update detector : saut de séquence ou delta incohérent -> RESYNC."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.missing_update_detector import analyser, CONTINUER, RESYNC   # noqa: E402


def test_sequence_coherente_continue():
    assert analyser(seq_precedent=10, seq_courant=11)["action"] == CONTINUER


def test_saut_declenche_resync():
    assert analyser(seq_precedent=10, seq_courant=15)["action"] == RESYNC


def test_delta_incoherent_avec_snapshot():
    r = analyser(seq_precedent=10, seq_courant=11, base_delta=7, seq_snapshot=9)
    assert r["action"] == RESYNC and r["raison"] == "DELTA_INCOHERENT_AVEC_SNAPSHOT"
