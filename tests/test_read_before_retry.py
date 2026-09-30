"""[ARB #34] read-before-retry : état ambigu -> lire l'ordre avant tout renvoi, jamais retry aveugle."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.read_before_retry import decider_retry, LIRE_ETAT, RETRY, STOP   # noqa: E402


def test_ambigu_lire_avant_renvoi():
    assert decider_retry("TIMEOUT")["action"] == LIRE_ETAT
    assert decider_retry("UNKNOWN_STATE")["action"] == LIRE_ETAT


def test_rejet_net_autorise_retry():
    assert decider_retry("REJECTED")["action"] == RETRY


def test_fill_confirme_stop():
    assert decider_retry("TIMEOUT", fill_confirme=True)["action"] == STOP
    assert decider_retry("???")["action"] == LIRE_ETAT               # inconnu = prudence
