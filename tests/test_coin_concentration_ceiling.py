"""[COPY-VAULT #84] coin concentration ceiling : plusieurs vaults sur le même coin = une seule concentration."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.coin_concentration_ceiling import exposition_admissible   # noqa: E402


def test_agregation_et_plafond():
    r = exposition_admissible({"vA": 3000.0, "vB": 4000.0}, equity=10000.0, part_max=0.5)
    assert r["agregee"] == 7000.0 and r["plafond"] == 5000.0 and r["depasse"] is True
    assert r["facteur_reduction"] == round(5000.0 / 7000.0, 8)


def test_sous_plafond():
    r = exposition_admissible({"vA": 1000.0, "vB": 1000.0}, equity=10000.0, part_max=0.5)
    assert r["depasse"] is False and r["facteur_reduction"] == 1.0


def test_equity_invalide():
    assert exposition_admissible({"vA": 1000.0}, equity=0.0)["refuse"] is True
