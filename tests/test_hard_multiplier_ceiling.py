"""[COPY-VAULT #54] hard multiplier ceiling : taille copiée bornée en dur a leader_fill x multiplier_max."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.hard_multiplier_ceiling import plafonner   # noqa: E402


def test_plafond_dur():
    r = plafonner(10.0, leader_fill=2.0, multiplier_max=3.0)
    assert r["taille"] == 6.0 and r["plafonnee"] is True   # 10 borné a 2*3=6


def test_sous_plafond_inchange():
    r = plafonner(4.0, leader_fill=2.0, multiplier_max=3.0)
    assert r["taille"] == 4.0 and r["plafonnee"] is False


def test_signe_preserve_et_invalide():
    assert plafonner(-10.0, leader_fill=2.0, multiplier_max=3.0)["taille"] == -6.0
    assert plafonner(None, leader_fill=2.0)["refuse"] is True
