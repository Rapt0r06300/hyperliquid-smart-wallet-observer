"""[DATA lot2 #34] clear-and-reseed : à la reconnexion on purge puis re-seed, jamais continuer l'ancien carnet."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.clear_and_reseed import EtatCarnet, PRET, PURGE   # noqa: E402


def test_non_utilisable_avant_seed():
    c = EtatCarnet()
    assert c.utilisable()["utilisable"] is False and c.etat == PURGE


def test_reconnexion_purge_puis_reseed():
    c = EtatCarnet()
    c.reseed(snapshot_seq=100)
    assert c.utilisable()["utilisable"] is True
    c.reconnecter()                                      # nouvelle connexion -> purge
    assert c.etat == PURGE and c.utilisable()["utilisable"] is False
    c.reseed(snapshot_seq=200)
    assert c.utilisable()["utilisable"] is True and c.seq_base == 200


def test_purge_efface_la_base():
    c = EtatCarnet()
    c.reseed(snapshot_seq=100)
    c.reconnecter()
    assert c.seq_base is None
