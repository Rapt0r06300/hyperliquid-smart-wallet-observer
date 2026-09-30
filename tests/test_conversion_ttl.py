"""[ARB #40] conversion TTL : un taux au-delà de son âge maximal est UNMEASURABLE, jamais réutilisé."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.conversion_ttl import taux_valide, convertir_avec_ttl   # noqa: E402


def test_dans_le_ttl():
    assert taux_valide(500.0, ttl_ms=1000.0)["valide"] is True
    r = convertir_avec_ttl(100.0, 0.9995, age_ms=500.0, ttl_ms=1000.0)
    assert r["valeur"] == 99.95 and r["refuse"] is False


def test_perime_refuse():
    assert taux_valide(2000.0, ttl_ms=1000.0)["valide"] is False
    r = convertir_avec_ttl(100.0, 0.9995, age_ms=2000.0, ttl_ms=1000.0)
    assert r["valeur"] == "UNMEASURABLE" and r["raison"] == "TAUX_PERIME"


def test_age_inconnu_refuse():
    assert convertir_avec_ttl(100.0, 0.9995, age_ms=None, ttl_ms=1000.0)["refuse"] is True
