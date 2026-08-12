"""AUD-049 / AUD-059 — runtime vs economic data readiness, deny-by-default."""
from __future__ import annotations

from hl_observer.ops.preuve_de_vie import SOURCES_HARVEST
from hl_observer.strategies import strategy_data_dependencies as D
from hl_observer.strategies.active_scope import active_strategy_families


def test_chaque_famille_active_a_des_dependances_declarees():
    for fam in active_strategy_families():
        assert D.required_sources(fam), f"famille active {fam} sans source runtime requise"
        assert D.economic_required_sources(fam), f"famille active {fam} sans source economique requise"
    assert D.active_families_have_declared_dependencies() is True
    assert D.active_families_have_declared_economic_dependencies() is True


def test_deny_by_default_famille_inconnue():
    assert D.required_sources("famille_bidon") == frozenset()
    assert D.economic_required_sources("famille_bidon") == frozenset()
    r = D.evaluate_family_data_readiness("famille_bidon", ["bbo-collector"])
    e = D.evaluate_family_economic_readiness("famille_bidon", ["bbo-collector"])
    assert r.ready is False and r.required == frozenset()
    assert e.ready is False and e.required == frozenset()


def test_runtime_lead_lag_requiert_bbo_sans_exiger_l2():
    r = D.evaluate_family_data_readiness("lead_lag", ["bbo-collector"])
    assert r.ready is True and r.missing == frozenset()
    assert D.required_sources("lead_lag") == frozenset({"bbo-collector"})


def test_preuve_economique_lead_lag_requiert_l2():
    r = D.evaluate_family_economic_readiness("lead_lag", ["bbo-collector"])
    assert r.ready is False and r.missing == frozenset({"carnet-collector"})
    r2 = D.evaluate_family_economic_readiness("lead_lag", ["bbo-collector", "carnet-collector"])
    assert r2.ready is True


def test_copy_vault_runtime_et_economique():
    runtime = D.required_sources("copy_vault")
    economic = D.economic_required_sources("copy_vault")
    assert runtime == frozenset({"userfills-live", "allmids-collector"})
    assert economic == frozenset({"userfills-live", "allmids-collector", "carnet-collector"})


def test_cross_venue_runtime_bbo_economic_bbo_plus_l2():
    assert D.required_sources("cross_venue_dislocation") == frozenset({"bbo-collector"})
    assert D.economic_required_sources("cross_venue_dislocation") == frozenset(
        {"bbo-collector", "carnet-collector"}
    )


def test_les_sources_requises_sont_reelles_dans_SOURCES_HARVEST():
    noms = {s.nom for s in SOURCES_HARVEST}
    manifests = (
        D.strategy_data_dependencies(),
        D.economic_strategy_data_dependencies(),
    )
    for manifest in manifests:
        for fam, sources in manifest.items():
            for source in sources:
                assert source in noms, f"{fam} requiert une source absente de SOURCES_HARVEST: {source}"
