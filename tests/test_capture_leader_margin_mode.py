"""[COPY-VAULT lot2 #53] capturer le margin mode : isolated/cross normalisé, inconnu -> UNKNOWN."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.capture_leader_margin_mode import capturer, ISOLATED, CROSS, UNKNOWN   # noqa: E402


def test_modes_reconnus():
    assert capturer("isolated")["margin_mode"] == ISOLATED
    assert capturer("CROSS")["margin_mode"] == CROSS


def test_inconnu():
    r = capturer("weird")
    assert r["margin_mode"] == UNKNOWN and r["connu"] is False


def test_alias():
    assert capturer("iso")["margin_mode"] == ISOLATED


def test_espaces_sont_normalises_sans_elargir_le_contrat():
    assert capturer("  cross ")["margin_mode"] == CROSS


def test_objet_ou_booleen_ne_devient_pas_un_mode_valide():
    assert capturer(True)["margin_mode"] == UNKNOWN
    assert capturer({"mode": "CROSS"})["connu"] is False
