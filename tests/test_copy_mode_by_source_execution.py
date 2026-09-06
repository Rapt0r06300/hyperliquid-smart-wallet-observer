"""[pépite 282] copy mode by source execution : un vault maker-dépendant n'est pas copiable instantanément en taker."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.copy_mode_by_source_execution import mode_copie   # noqa: E402


def test_maker_dependant_decote_forte():
    r = mode_copie({"taux_maker": 0.9, "taux_taker": 0.1})
    assert r["mode"] == "MAKER_DEPENDANT" and r["copiable_taker_direct"] is False


def test_taker_dominant_direct():
    r = mode_copie({"taux_maker": 0.2, "taux_taker": 0.8})
    assert r["mode"] == "DIRECT_TAKER" and r["copiable_taker_direct"] is True


def test_taux_non_mesure():
    assert mode_copie({"taux_maker": "UNMEASURABLE", "taux_taker": "UNMEASURABLE"})["mode"] == "UNMEASURABLE"


def test_profil_mixte_reste_copiable_avec_decote_moyenne():
    r = mode_copie({"taux_maker": 0.4, "taux_taker": 0.5})
    assert r == {"mode": "MIXTE", "decote_confiance": 0.3, "copiable_taker_direct": True}
