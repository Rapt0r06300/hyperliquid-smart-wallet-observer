"""[DATA lot2 #28] subscription chunking : découpe les subscriptions en lots <= limite WS."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.subscription_chunking import decouper   # noqa: E402


def test_decoupage():
    r = decouper(["a", "b", "c", "d", "e"], max_par_chunk=2)
    assert r["chunks"] == [["a", "b"], ["c", "d"], ["e"]] and r["n_chunks"] == 3
    assert r["tous_sous_limite"] is True


def test_liste_vide():
    assert decouper([], max_par_chunk=2)["n_chunks"] == 0


def test_limite_invalide():
    assert decouper(["a"], max_par_chunk=0)["chunks"] == "UNMEASURABLE"
