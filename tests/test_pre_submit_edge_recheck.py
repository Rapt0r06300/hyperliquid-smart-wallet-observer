"""[ARB #21] pre-submit edge recheck : un edge évaporé entre détection et envoi ne doit pas être exécuté."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.pre_submit_edge_recheck import recheck_avant_envoi   # noqa: E402


def test_edge_maintenu_autorise():
    r = recheck_avant_envoi(40.0, 35.0, seuil_net_bps=30.0)
    assert r["envoyer"] is True and r["degradation_bps"] == 5.0


def test_edge_evapore_bloque():
    r = recheck_avant_envoi(40.0, 20.0, seuil_net_bps=30.0)
    assert r["envoyer"] is False and r["raison"] == "EDGE_EVAPORE_AVANT_ENVOI"


def test_edge_courant_non_mesurable_bloque():
    r = recheck_avant_envoi(40.0, None, seuil_net_bps=30.0)
    assert r["envoyer"] is False and r["raison"] == "EDGE_COURANT_NON_MESURABLE"
