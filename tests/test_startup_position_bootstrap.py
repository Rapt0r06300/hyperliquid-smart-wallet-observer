"""[COPY-VAULT #58] startup bootstrap : aucun fill traité avant d'avoir chargé l'état complet du vault."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.startup_position_bootstrap import Bootstrap   # noqa: E402


def test_bloque_avant_bootstrap():
    b = Bootstrap()
    assert b.pret() is False
    assert b.peut_traiter_fill()["ok"] is False and b.peut_traiter_fill()["raison"] == "BOOTSTRAP_NON_FAIT"


def test_pret_apres_chargement():
    b = Bootstrap()
    r = b.charger_etat({"BTC": 0.5, "ETH": -2.0})
    assert r["n_positions"] == 2 and b.pret() is True
    assert b.peut_traiter_fill()["ok"] is True


def test_baseline_disponible():
    b = Bootstrap()
    b.charger_etat({"BTC": 0.5})
    assert b.position_initiale("BTC") == 0.5 and b.position_initiale("XYZ") == 0.0
