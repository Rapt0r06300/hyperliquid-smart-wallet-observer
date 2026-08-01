"""[pépite 278] chunk checksum : distinguer un trou de marché d'une corruption disque."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.dataset.chunk_checksum import checksum, verifier   # noqa: E402


def test_chunk_ok():
    data = b"trade,1,2,3"
    assert verifier(data, checksum(data))["etat"] == "OK"


def test_trou_marche_valide():
    vide = b""
    assert verifier(vide, checksum(vide))["etat"] == "TROU_MARCHE_VALIDE"


def test_corruption():
    data = b"trade,1,2,3"
    assert verifier(b"trade,9,9,9", checksum(data))["etat"] == "CORRUPTION"
