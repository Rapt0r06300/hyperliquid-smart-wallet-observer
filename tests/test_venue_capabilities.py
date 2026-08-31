import pytest

from hl_observer.research.venue_capabilities import (
    NON_IMPLEMENTE,
    OFFLINE_READY,
    REQUIRES_NETWORK,
    RegistreCapacitesVenues,
    registre_par_defaut,
)
from hl_observer.runtime.capability_reconciliation import CapabilityReconciliationError


def test_registre_par_defaut_honnete():
    r = registre_par_defaut()
    assert r.capacite("hyperliquid") == OFFLINE_READY
    assert r.capacite("dydx") == OFFLINE_READY and r.capacite("binance") == OFFLINE_READY
    assert r.capacite("bybit") == REQUIRES_NETWORK and r.capacite("nansen") == REQUIRES_NETWORK
    rd = r.ready()
    assert rd["ready"] is True                                   # aucune requise NON_IMPLEMENTE
    assert "bybit" in rd["requiert_reseau"] and "hyperliquid" in rd["offline_ready"]
    assert r.flux_supportes("hyperliquid") == ["book", "funding", "liquidations", "oi", "trades"]


def test_venue_requise_non_implementee_bloque():
    r = RegistreCapacitesVenues()
    r.declarer("hyperliquid", OFFLINE_READY, requis=True)
    r.declarer("okx", NON_IMPLEMENTE, requis=True)
    rd = r.ready()
    assert rd["ready"] is False and "okx" in rd["requises_non_pretes"]


def test_registre_reconcilie_exactement_venues_chargees_et_desactivees():
    r = registre_par_defaut()
    receipt = r.reconcile_loaded(run_id="venue-bootstrap", state_version="b" * 40)
    assert receipt.require_ready().counts == {
        "expected": 14,
        "loaded": 3,
        "unavailable": 0,
        "intentionally_disabled": 11,
    }
    assert {item.capability_id for item in receipt.loaded} == {
        "venue:binance",
        "venue:dydx",
        "venue:hyperliquid",
    }


def test_registre_bloque_si_hyperliquid_declare_n_est_pas_charge():
    r = registre_par_defaut()
    receipt = r.reconcile_loaded(
        run_id="venue-bootstrap-missing",
        state_version="c" * 40,
        loaded_venues=("binance", "dydx"),
    )
    assert receipt.ready is False
    assert "CAPABILITY_MISSING:venue:hyperliquid" in receipt.blocking_reasons


def test_registre_refuse_venue_inconnue_ou_reseau_non_prouve_charge():
    r = registre_par_defaut()
    with pytest.raises(CapabilityReconciliationError, match="VENUE_LOADED_UNDECLARED"):
        r.reconcile_loaded(
            run_id="unknown-loaded",
            state_version="e" * 40,
            loaded_venues=("hyperliquid", "venue-inventee"),
        )
    with pytest.raises(
        CapabilityReconciliationError, match="VENUE_LOADED_WITHOUT_OFFLINE_PROOF"
    ):
        r.reconcile_loaded(
            run_id="network-unproven",
            state_version="f" * 40,
            loaded_venues=("hyperliquid", "bybit"),
        )
