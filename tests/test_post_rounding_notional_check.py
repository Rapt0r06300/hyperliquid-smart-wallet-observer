"""[COPY-VAULT #56] post-rounding notional check : re-vérifier le minimum exécutable APRÈS arrondi."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.post_rounding_notional_check import verifier   # noqa: E402


def test_au_dessus_du_min():
    r = verifier(0.5, 100.0, min_notional=10.0)
    assert r["ok"] is True and r["notional"] == 50.0


def test_sous_le_min_apres_arrondi():
    r = verifier(0.05, 100.0, min_notional=10.0)          # 5$ < 10$
    assert r["ok"] is False and r["raison"] == "SOUS_MIN_APRES_ARRONDI"


def test_entree_invalide_refuse():
    assert verifier(None, 100.0, min_notional=10.0)["ok"] is False
