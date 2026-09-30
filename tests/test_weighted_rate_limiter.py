"""[ALL lot2 #23] rate limiter pondéré : budget en poids par fenêtre, pas en simple compte de requêtes."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.api_governance.weighted_rate_limiter import LimiteurPondere   # noqa: E402


def test_budget_en_poids():
    lim = LimiteurPondere(budget_poids=10.0, fenetre_ms=60_000.0)
    assert lim.consommer(poids=6.0, now_ms=0.0)["ok"] is True
    assert lim.consommer(poids=5.0, now_ms=1000.0)["ok"] is False   # 6+5 > 10
    assert lim.consommer(poids=4.0, now_ms=1000.0)["ok"] is True    # 6+4 = 10 ok


def test_fenetre_glissante_libere():
    lim = LimiteurPondere(budget_poids=10.0, fenetre_ms=1000.0)
    lim.consommer(poids=10.0, now_ms=0.0)
    assert lim.consommer(poids=5.0, now_ms=2000.0)["ok"] is True    # ancien poids hors fenêtre


def test_poids_invalide():
    assert LimiteurPondere().consommer(poids=-1.0, now_ms=0.0)["ok"] is False
