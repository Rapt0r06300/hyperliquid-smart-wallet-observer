"""[pépite 252] sweep protection collar : consommer le carnet seulement jusqu'à reference ± X bps."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.sweep_protection_collar import executer   # noqa: E402


def test_sweep_coupe_au_collar():
    # ref 100, collar 30 bps -> borne 100.3 ; niveau a 100.5 hors collar
    niveaux = [(100.0, 1.0), (100.2, 1.0), (100.5, 5.0)]
    r = executer(niveaux, 5.0, prix_reference=100.0, sens="ACHAT", collar_bps=30.0)
    assert r["remplie"] == 2.0 and r["reliquat_non_rempli"] == 3.0 and r["sweep_evite"] is True


def test_tout_dans_collar():
    niveaux = [(100.0, 1.0), (100.1, 1.0)]
    r = executer(niveaux, 2.0, prix_reference=100.0, sens="ACHAT", collar_bps=30.0)
    assert r["remplie"] == 2.0 and r["sweep_evite"] is False


def test_entree_invalide():
    assert executer([(100.0, 1.0)], 0.0, prix_reference=100.0, sens="ACHAT")["remplie"] == "UNMEASURABLE"
