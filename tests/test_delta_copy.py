"""[COPY-VAULT #64] delta-copy : copier le changement du fill, jamais reconstruire toute la position."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.delta_copy import delta, appliquer_delta   # noqa: E402


def test_delta_est_le_changement():
    r = delta(2.0, 3.5)
    assert r["delta"] == 1.5 and r["sens"] == "ACHAT" and r["a_copier"] == 1.5   # pas 3.5


def test_reduction_delta_negatif():
    r = delta(2.0, 0.5)
    assert r["delta"] == -1.5 and r["sens"] == "VENTE"


def test_appliquer_et_invalide():
    assert appliquer_delta(10.0, 1.5)["position"] == 11.5
    assert delta(None, 3.5)["delta"] == "UNMEASURABLE"
