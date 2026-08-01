"""[pépite 251] marketable-limit mode : limit agressif borné plutôt qu'un market illimité."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.marketable_limit_mode import prix_marketable   # noqa: E402


def test_achat_borne_par_collar():
    r = prix_marketable(100.0, "ACHAT", agressivite_bps=5.0, collar_bps=30.0)
    assert r["prix"] == 100.05 and r["borne_collar"] == 100.3


def test_agressivite_plafonnee_au_collar():
    r = prix_marketable(100.0, "ACHAT", agressivite_bps=50.0, collar_bps=30.0)   # agr > collar
    assert r["prix"] == 100.3                             # plafonne au collar


def test_prix_invalide():
    assert prix_marketable(0.0, "ACHAT")["prix"] == "UNMEASURABLE"
