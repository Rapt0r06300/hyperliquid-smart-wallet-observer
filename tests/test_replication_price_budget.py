"""[COPY-VAULT #72] replication-price budget : écart max autorisé entre fill leader et notre prix exécutable."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.replication_price_budget import dans_budget   # noqa: E402


def test_dans_le_budget():
    r = dans_budget(100.0, 100.05, budget_bps=10.0)      # 5 bps <= 10
    assert r["ok"] is True and r["ecart_bps"] == 5.0


def test_hors_budget():
    r = dans_budget(100.0, 100.2, budget_bps=10.0)       # 20 bps > 10
    assert r["ok"] is False and r["raison"] == "ECART_PRIX_HORS_BUDGET"


def test_prix_invalide_refuse():
    assert dans_budget(0.0, 100.0, budget_bps=10.0)["ok"] is False
