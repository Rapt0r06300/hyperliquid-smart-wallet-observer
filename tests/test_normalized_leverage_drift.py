"""[COPY-VAULT lot2 #56] normalized leverage drift : levier qui grimpe sans alpha proportionnel -> suspect."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.normalized_leverage_drift import detecter   # noqa: E402


def test_levier_sans_alpha_suspect():
    r = detecter(levier_avant=2.0, levier_apres=4.0, alpha_avant=1.0, alpha_apres=1.05, tolerance=1.2)
    assert r["suspect"] is True and r["raison"] == "LEVIER_SANS_ALPHA"


def test_proportionne_ok():
    r = detecter(levier_avant=2.0, levier_apres=4.0, alpha_avant=1.0, alpha_apres=2.0, tolerance=1.2)
    assert r["suspect"] is False


def test_levier_non_augmente():
    r = detecter(levier_avant=2.0, levier_apres=2.0, alpha_avant=1.0, alpha_apres=1.0)
    assert r["suspect"] is False and r["raison"] == "LEVIER_NON_AUGMENTE"
