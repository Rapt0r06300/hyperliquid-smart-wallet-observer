"""[DATA lot2 #68] raw playback harness : rejoue des messages bruts dans l'ordre via un handler."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.raw_playback_harness import Playback   # noqa: E402


def test_rejoue_dans_lordre():
    vus = []
    pb = Playback([1, 2, 3])
    r = pb.rejouer(lambda m: vus.append(m))
    assert vus == [1, 2, 3] and r["traites"] == 3 and r["erreurs"] == 0


def test_erreur_comptee_pas_masquee():
    def handler(m):
        if m == 2:
            raise ValueError("boom")
    r = Playback([1, 2, 3]).rejouer(handler)
    assert r["traites"] == 2 and r["erreurs"] == 1        # continue malgré l'erreur


def test_nombre():
    assert Playback([1, 2]).nombre() == 2
