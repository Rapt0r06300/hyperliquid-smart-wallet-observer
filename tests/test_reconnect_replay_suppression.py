"""[COPY-VAULT #61] reconnect replay suppression : les événements rediffusés ne créent aucun nouvel intent."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.reconnect_replay_suppression import doit_creer_intent   # noqa: E402


def test_nouvel_evenement_cree_intent():
    r = doit_creer_intent(11, dernier_traite=10)
    assert r["creer"] is True and r["raison"] == "NOUVEL_EVENEMENT"


def test_rejeu_supprime():
    assert doit_creer_intent(10, dernier_traite=10)["creer"] is False   # seq deja traite
    assert doit_creer_intent(7, dernier_traite=10)["creer"] is False    # rediffusion apres reconnect


def test_invalide_supprime():
    assert doit_creer_intent(None, dernier_traite=10)["creer"] is False
