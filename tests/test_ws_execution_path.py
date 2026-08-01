"""[ARB lot2 #1] WebSocket execution path : canal WS persistant réduit la latence de soumission vs REST."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle import ws_execution_path as WEP   # noqa: E402


def test_ws_ouvert_plus_rapide():
    r = WEP.latence_soumission_ms(canal=WEP.WS, latence_ws_ms=15.0, latence_rest_ms=60.0, ws_ouvert=True)
    assert r["canal"] == WEP.WS and r["latence_ms"] == 15.0


def test_ws_ferme_fallback_rest():
    r = WEP.latence_soumission_ms(canal=WEP.WS, ws_ouvert=False)
    assert r["canal"] == WEP.REST and r["raison"] == "WS_FERME_FALLBACK_REST"


def test_choisir_canal_gain():
    r = WEP.choisir_canal(ws_ouvert=True, latence_ws_ms=15.0, latence_rest_ms=60.0)
    assert r["canal"] == WEP.WS and r["gain_ms"] == 45.0
    assert WEP.choisir_canal(ws_ouvert=False)["canal"] == WEP.REST
