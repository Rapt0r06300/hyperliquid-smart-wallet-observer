"""[DATA lot2 #35] idle-socket watchdog : un socket ouvert mais silencieux est mort et doit être réouvert."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.idle_socket_watchdog import etat_socket, VIVANT, MORT   # noqa: E402


def test_socket_vivant():
    r = etat_socket(1000.0, 3000.0, timeout_ms=5000.0)
    assert r["etat"] == VIVANT and r["reouvrir"] is False


def test_socket_silencieux_mort():
    r = etat_socket(1000.0, 9000.0, timeout_ms=5000.0)
    assert r["etat"] == MORT and r["reouvrir"] is True


def test_activite_inconnue_mort():
    assert etat_socket(None, 9000.0, timeout_ms=5000.0)["etat"] == MORT
