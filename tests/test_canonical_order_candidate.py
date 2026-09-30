"""[ALL #87] canonical OrderCandidate : toute intention pré-validée par le même objet avant le PaperEngine."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.canonical_order_candidate import creer_candidat   # noqa: E402


def test_candidat_valide():
    r = creer_candidat(coin="btc", cote="buy", quantite=0.5, prix=100.0, type_exec="maker",
                       budget_disponible=100.0)
    assert r["valide"] is True and r["coin"] == "BTC" and r["notional"] == 50.0


def test_champ_invalide_refuse():
    r = creer_candidat(coin="BTC", cote="LONGISH", quantite=0.5, prix=100.0, type_exec="MAKER",
                       budget_disponible=100.0)
    assert r["valide"] is False and "COTE_INVALIDE" in r["erreurs"]


def test_notional_depasse_budget():
    r = creer_candidat(coin="BTC", cote="BUY", quantite=2.0, prix=100.0, type_exec="TAKER",
                       budget_disponible=100.0)
    assert r["valide"] is False and "NOTIONAL_DEPASSE_BUDGET" in r["erreurs"]
