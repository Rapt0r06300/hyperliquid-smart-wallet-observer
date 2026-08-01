"""[ALL #91] flip-aware incremental accounting : dépasser la taille ferme puis ouvre l'inverse au bon prix moyen."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.flip_aware_incremental_accounting import appliquer_trade   # noqa: E402


def test_ajout_pondere_le_prix_moyen():
    r = appliquer_trade(1.0, 100.0, 1.0, 110.0)          # long 1@100 + 1@110
    assert r["position_apres"] == 2.0 and r["prix_moyen_apres"] == 105.0 and r["realized_pnl"] == 0.0


def test_reduction_realise_pnl():
    r = appliquer_trade(2.0, 100.0, -1.0, 110.0)         # ferme 1 d'un long a +10
    assert r["position_apres"] == 1.0 and r["realized_pnl"] == 10.0 and r["closed_qty"] == 1.0
    assert r["flip"] is False


def test_flip_ferme_puis_ouvre():
    r = appliquer_trade(1.0, 100.0, -3.0, 110.0)         # long 1 -> vend 3 -> short 2
    assert r["flip"] is True and r["position_apres"] == -2.0
    assert r["closed_qty"] == 1.0 and r["opened_qty"] == 2.0
    assert r["realized_pnl"] == 10.0 and r["prix_moyen_apres"] == 110.0
