"""[COPY-VAULT #82] existing-position conflict rule : pas d'écrasement silencieux d'une position d'un autre module."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.existing_position_conflict_rule import RegistreProprietaires   # noqa: E402


def test_attribution_libre():
    reg = RegistreProprietaires()
    assert reg.demander("BTC", "vaultA")["ok"] is True
    assert reg.proprietaire("BTC") == "vaultA"


def test_conflit_autre_module():
    reg = RegistreProprietaires()
    reg.demander("BTC", "arb_module")
    r = reg.demander("BTC", "vaultA")                     # un autre module tient déjà BTC
    assert r["ok"] is False and r["raison"] == "CONFLIT_POSITION_EXISTANTE"
    assert r["proprietaire_actuel"] == "arb_module"


def test_liberation_puis_reprise():
    reg = RegistreProprietaires()
    reg.demander("BTC", "arb_module")
    reg.liberer("BTC", "arb_module")
    assert reg.demander("BTC", "vaultA")["ok"] is True
