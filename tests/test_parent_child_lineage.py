"""[pépite 212] parent/child lineage : retry/amend/replacement rattachés au même economic_intent_id."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.parent_child_lineage import LignageIntent   # noqa: E402


def test_meme_intent():
    lg = LignageIntent()
    lg.enregistrer(economic_intent_id="I1", venue_order_id="v1")
    lg.enregistrer(economic_intent_id="I1", venue_order_id="v2")   # remplacement
    assert lg.meme_intent("v1", "v2")["meme_intent"] is True
    assert lg.ordres_de("I1") == ["v1", "v2"]


def test_intents_differents():
    lg = LignageIntent()
    lg.enregistrer(economic_intent_id="I1", venue_order_id="v1")
    lg.enregistrer(economic_intent_id="I2", venue_order_id="v2")
    assert lg.meme_intent("v1", "v2")["meme_intent"] is False


def test_inconnu():
    assert LignageIntent().meme_intent("x", "y")["meme_intent"] is False
