"""#36 — le registre empêche de re-tester ce qui est déjà mort, et nomme ce qui reste ouvert."""
from __future__ import annotations

from hl_observer.research.registre_hypotheses import est_morte, pistes_ouvertes, verdict


def test_les_pistes_mortes_sont_marquees():
    for h in ("copy_trading", "market_making", "lead_lag_btc_alts"):
        assert est_morte(h) is True
        assert verdict(h)["preuve"]                       # chaque mort a sa PREUVE chiffrée


def test_le_carry_est_vivant_et_les_liquidations_ouvertes():
    assert est_morte("carry_delta_neutre") is False
    assert "liquidations" in pistes_ouvertes()


def test_hypothese_inconnue_est_testable():
    assert verdict("une_idee_jamais_testee") is None and est_morte("une_idee_jamais_testee") is False
