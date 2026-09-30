"""[pépite 283] turnover penalty : un turnover excessif peut rendre l'alpha incopiable après coûts."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.turnover_penalty import penalite   # noqa: E402


def test_sous_seuil_pas_de_penalite():
    r = penalite(notional_traite=200.0, equity=100.0, seuil_turnover=5.0)   # turnover 2 < 5
    assert r["penalite"] == 0.0 and r["turnover"] == 2.0


def test_au_dessus_seuil_penalise():
    r = penalite(notional_traite=1000.0, equity=100.0, seuil_turnover=5.0)  # turnover 10 > 5
    assert r["penalite"] > 0.0 and r["au_dessus_seuil"] is True


def test_equity_invalide():
    assert penalite(100.0, 0.0)["penalite"] == "UNMEASURABLE"
