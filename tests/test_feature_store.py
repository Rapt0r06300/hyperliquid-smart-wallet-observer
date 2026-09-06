"""J1 — feature store point-in-time : as_of ne renvoie JAMAIS le futur."""
from __future__ import annotations

from hl_observer.features.feature_store import FeatureStore


def test_as_of_renvoie_la_derniere_valeur_passee():
    s = FeatureStore()
    s.ecrire("f", 100, "a"); s.ecrire("f", 200, "b"); s.ecrire("f", 300, "c")
    assert s.as_of("f", 250) == "b"        # derniere <= 250
    assert s.as_of("f", 300) == "c"
    assert s.as_of("f", 350) == "c"


def test_as_of_jamais_le_futur():
    s = FeatureStore()
    s.ecrire("f", 200, "b")
    assert s.as_of("f", 100) is None       # rien de disponible avant 200 -> pas de lecture du futur


def test_as_of_serie_absente_reste_fail_closed():
    s = FeatureStore()
    assert s.as_of("inconnue", 250) is None


def test_ecrasement_meme_estampille():
    s = FeatureStore()
    s.ecrire("f", 100, "a"); s.ecrire("f", 100, "z")
    assert s.as_of("f", 100) == "z" and len(s.historique("f")) == 1


def test_insertion_desordonnee_reste_triee():
    s = FeatureStore()
    s.ecrire("f", 300, "c"); s.ecrire("f", 100, "a"); s.ecrire("f", 200, "b")
    assert s.as_of("f", 250) == "b"
