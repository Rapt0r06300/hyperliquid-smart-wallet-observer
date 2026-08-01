"""[DATA lot2 #69] persister snapshot->deltas en ordre causal : pas de réordonnancement, hors-ordre refusé."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.causal_snapshot_delta_persist import PersistanceCausale, SNAPSHOT, DELTA   # noqa: E402


def test_ordre_causal_respecte():
    p = PersistanceCausale()
    assert p.ajouter(type_entree=SNAPSHOT, seq=1)["ok"] is True
    assert p.ajouter(type_entree=DELTA, seq=2)["ok"] is True
    assert p.ajouter(type_entree=DELTA, seq=3)["ok"] is True
    assert p.ordre() == [1, 2, 3]


def test_ecriture_hors_ordre_refusee():
    p = PersistanceCausale()
    p.ajouter(type_entree=SNAPSHOT, seq=5)
    r = p.ajouter(type_entree=DELTA, seq=3)              # seq plus petit
    assert r["ok"] is False and r["raison"] == "ECRITURE_HORS_ORDRE_CAUSAL"


def test_delta_sans_snapshot_refuse():
    p = PersistanceCausale()
    assert p.ajouter(type_entree=DELTA, seq=1)["ok"] is False
