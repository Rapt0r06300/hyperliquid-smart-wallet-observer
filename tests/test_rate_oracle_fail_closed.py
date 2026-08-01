"""[ARB #39] rate-oracle fail-closed : une conversion manquante ne devient jamais 1.0 implicite."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.rate_oracle_fail_closed import convertir   # noqa: E402


def test_conversion_via_taux():
    r = convertir(100.0, "USDT", "USD", oracle={"USDT->USD": 0.9995})
    assert r["valeur"] == 99.95 and r["refuse"] is False


def test_meme_quote_passthrough():
    r = convertir(100.0, "USD", "USD", oracle={})
    assert r["valeur"] == 100.0 and r["taux"] == 1.0


def test_taux_absent_fail_closed():
    r = convertir(100.0, "XYZ", "USD", oracle={"USDT->USD": 0.9995})
    assert r["valeur"] == "UNMEASURABLE" and r["refuse"] is True     # jamais 1.0 supposé
