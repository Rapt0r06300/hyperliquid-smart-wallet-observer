"""Coverage regression for fail-closed handling of an unknown quote/base unit."""

from hl_observer.risk_gates.quote_quantity_pretrade import notional_reel, valider


def test_unite_inconnue_refuse_fail_closed():
    resultat = notional_reel(500.0, unite="CONTRACTS")

    assert resultat == {"notional": "UNMEASURABLE", "raison": "UNITE_INCONNUE"}
    assert valider(500.0, unite="CONTRACTS", notional_max=1000.0) == {
        "ok": False,
        "raison": "UNITE_INCONNUE",
    }
