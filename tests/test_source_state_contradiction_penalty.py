"""[pépite 298] source-state contradiction penalty : fill=réduction mais report=augmentation → quarantaine + pénalité."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.source_state_contradiction_penalty import evaluer   # noqa: E402


def test_contradiction_reduce_mais_augmente():
    r = evaluer("REDUCE", position_avant=5.0, position_apres=8.0)   # magnitude monte
    assert r["contradiction"] is True and r["quarantaine"] is True and r["penalite_qualite"] == 0.25


def test_coherent_pas_de_penalite():
    r = evaluer("REDUCE", position_avant=8.0, position_apres=5.0)   # magnitude baisse : cohérent
    assert r["contradiction"] is False and r["penalite_qualite"] == 0.0


def test_position_invalide_quarantaine():
    r = evaluer("ADD", position_avant=None, position_apres=5.0)
    assert r["quarantaine"] is True and r["raison"] == "POSITION_INVALIDE"
