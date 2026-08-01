"""[pépite 285] leader execution efficiency : fills vs BBO/mid causal pour distinguer alpha et qualité d'exécution."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.leader_execution_efficiency import efficience   # noqa: E402


def test_achat_sous_mid_positif():
    r = efficience(fill_prix=99.5, mid_causal=100.0, sens="ACHAT")   # acheté sous le mid
    assert r["meilleur_que_mid"] is True and r["efficience_bps"] == 50.0


def test_vente_sous_mid_negatif():
    r = efficience(fill_prix=99.0, mid_causal=100.0, sens="VENTE")   # vendu sous le mid = mauvais
    assert r["meilleur_que_mid"] is False and r["efficience_bps"] == -100.0


def test_invalides():
    assert efficience(100.0, 0.0, "ACHAT")["efficience_bps"] == "UNMEASURABLE"
    assert efficience(100.0, 100.0, "HOLD")["efficience_bps"] == "UNMEASURABLE"
