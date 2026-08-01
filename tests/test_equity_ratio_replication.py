"""[COPY-VAULT #51] equity-ratio replication : taille = leader_fill x notre_equity/leader_equity."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.equity_ratio_replication import taille_paper   # noqa: E402


def test_mise_a_lechelle():
    r = taille_paper(10.0, notre_equity=5000.0, leader_equity=100000.0)
    assert r["taille"] == 0.5 and r["ratio_equity"] == 0.05   # 10 * 5000/100000


def test_equity_leader_nulle_refuse():
    r = taille_paper(10.0, notre_equity=5000.0, leader_equity=0.0)
    assert r["taille"] == "UNMEASURABLE" and r["refuse"] is True   # jamais 1:1 ni division par 0


def test_entree_invalide():
    assert taille_paper(None, notre_equity=5000.0, leader_equity=100000.0)["refuse"] is True
