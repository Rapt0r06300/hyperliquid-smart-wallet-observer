"""[ARB #44] emergency residual policy : budget de gap dépassé -> priorité à la réduction du risque."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.emergency_residual_policy import politique, REDUIRE_RISQUE, CONSERVER_SPREAD   # noqa: E402


def test_budget_ok_conserve_le_spread():
    r = politique(10.0, 40.0, fraction_tolerable=0.5)                # budget 20, mouvement 10
    assert r["action"] == CONSERVER_SPREAD and r["priorite_risque"] is False


def test_budget_depasse_reduit_le_risque():
    r = politique(25.0, 40.0, fraction_tolerable=0.5)                # budget 20, mouvement 25
    assert r["action"] == REDUIRE_RISQUE and r["priorite_risque"] is True


def test_non_chiffrable_reduit_le_risque():
    assert politique(None, 40.0)["action"] == REDUIRE_RISQUE
