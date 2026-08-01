"""[COPY-VAULT lot2 #54] liquidation-distance gate : leader proche de liquidation -> pas d'augmentation copiée."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.liquidation_distance_gate import peut_augmenter   # noqa: E402


def test_distance_suffisante():
    r = peut_augmenter(10.0, seuil_pct=5.0)
    assert r["peut_augmenter"] is True


def test_trop_proche_bloque():
    r = peut_augmenter(2.0, seuil_pct=5.0)
    assert r["peut_augmenter"] is False and r["peut_reduire"] is True and r["raison"] == "TROP_PROCHE_LIQUIDATION"


def test_distance_inconnue_bloque():
    assert peut_augmenter(None)["peut_augmenter"] is False
