"""[DATA lot2 #31] checksum du carnet : mismatch -> carnet immédiatement INVALID."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.book_checksum import valider, VALID, INVALID   # noqa: E402


def test_checksums_egaux():
    assert valider("abc123", "abc123")["etat"] == VALID


def test_mismatch_invalid():
    r = valider("abc123", "def456")
    assert r["etat"] == INVALID and r["raison"] == "CHECKSUM_MISMATCH_CARNET_DIVERGE"


def test_checksum_absent_failclosed():
    assert valider(None, "abc")["etat"] == INVALID
