"""[ARB lot2 #24] quota API réservé : la discovery ne touche jamais la réserve cancel/reconcile/hedge."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.api_governance.reserved_api_quota import QuotaReserve   # noqa: E402


def test_discovery_bornee_au_pool_libre():
    q = QuotaReserve(quota_total=100.0, reserve_critique=30.0)
    assert q.libre_pour_discovery() == 70.0
    # discovery peut consommer jusqu'a 70, pas au-dela
    for _ in range(70):
        q.consommer("DISCOVERY", cout=1.0)
    assert q.peut_consommer("DISCOVERY")["ok"] is False and q.peut_consommer("DISCOVERY")["raison"] == "RESERVE_CRITIQUE_PROTEGEE"


def test_critique_accede_a_la_reserve():
    q = QuotaReserve(quota_total=100.0, reserve_critique=30.0)
    for _ in range(70):
        q.consommer("DISCOVERY", cout=1.0)               # pool libre épuisé
    assert q.peut_consommer("CANCEL")["ok"] is True      # le critique puise dans la réserve


def test_categorie_critique():
    q = QuotaReserve(quota_total=10.0, reserve_critique=5.0)
    assert q.peut_consommer("HEDGE")["categorie"] == "HEDGE"
