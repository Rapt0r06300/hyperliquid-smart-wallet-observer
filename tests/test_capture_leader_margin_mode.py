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
