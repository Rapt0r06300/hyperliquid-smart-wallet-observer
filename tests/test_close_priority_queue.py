"""[COPY-VAULT #76] close priority queue : fermetures/réductions ordonnées devant les ouvertures."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.close_priority_queue import FilePrioriteFermeture   # noqa: E402


def test_fermetures_devant():
    f = FilePrioriteFermeture()
    f.ajouter({"action": "OPEN", "coin": "BTC"})
    f.ajouter({"action": "CLOSE", "coin": "ETH"})
    f.ajouter({"action": "ADD", "coin": "SOL"})
    f.ajouter({"action": "REDUCE", "coin": "XRP"})
    ordre = [it["action"] for it in f.ordonner()]
    assert ordre[:2] == ["CLOSE", "REDUCE"] and ordre[2:] == ["OPEN", "ADD"]


def test_stable_a_priorite_egale():
    f = FilePrioriteFermeture()
    f.ajouter({"action": "CLOSE", "coin": "A"})
    f.ajouter({"action": "CLOSE", "coin": "B"})
    assert [it["coin"] for it in f.ordonner()] == ["A", "B"]   # ordre d'arrivée préservé


def test_action_inconnue_basse_priorite():
    f = FilePrioriteFermeture()
    f.ajouter({"action": "???", "coin": "A"})
    f.ajouter({"action": "CLOSE", "coin": "B"})
    assert f.ordonner()[0]["coin"] == "B"
