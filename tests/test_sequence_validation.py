"""[DATA lot2 #32] validation stricte des sequence numbers : saut = GAP, recul = RECUL."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.sequence_validation import valider, OK, GAP, RECUL   # noqa: E402


def test_sequence_ok():
    assert valider(10, 11)["etat"] == OK


def test_gap():
    r = valider(10, 13)
    assert r["etat"] == GAP and r["manques"] == 2


def test_recul_et_invalide():
    assert valider(10, 9)["etat"] == RECUL
    assert valider(None, 11)["etat"] == GAP
