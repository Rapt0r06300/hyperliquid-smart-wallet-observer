"""AUD-049 / AUD-059 — Autorité famille -> données REQUISES (deny-by-default).

`active_scope` dit QUELLES familles peuvent matérialiser une économie paper ; il ne dit rien des
DONNÉES dont chacune a besoin. Ce test verrouille une autorité UNIQUE qui déclare, par famille
active, ses sources requises (identifiants canoniques de SOURCES_HARVEST), en deny-by-default :
famille inconnue -> rien d'offert ; famille active dont une source requise manque -> pas data-ready
(pas de faux vert). 0 réseau.
"""
from __future__ import annotations

from hl_observer.strategies import strategy_data_dependencies as D
from hl_observer.strategies.active_scope import active_strategy_families
from hl_observer.ops.preuve_de_vie import SOURCES_HARVEST


def test_chaque_famille_active_a_des_dependances_declarees():
    for fam in active_strategy_families():
        assert D.required_sources(fam), f"famille active {fam} sans source requise (AUD-049/059)"
    assert D.active_families_have_declared_dependencies() is True


def test_deny_by_default_famille_inconnue():
    assert D.required_sources("famille_bidon") == frozenset()
    r = D.evaluate_family_data_readiness("famille_bidon", ["bbo-collector"])
    assert r.ready is False and r.required == frozenset()


def test_famille_active_pas_ready_si_source_requise_absente():
    r = D.evaluate_family_data_readiness("lead_lag", ["allmids-collector"])
    assert r.ready is False and "bbo-collector" in r.missing


def test_famille_active_ready_si_toutes_sources_presentes():
    r = D.evaluate_family_data_readiness(
        "lead_lag", ["bbo-collector", "carnet-collector", "allmids-collector"]
    )
    assert r.ready is True and r.missing == frozenset()


def test_copy_vault_requiert_fills_et_prix():
    req = D.required_sources("copy_vault")
    assert "userfills-live" in req and "allmids-collector" in req


def test_cross_venue_requiert_bbo_et_profondeur_l2():
    req = D.required_sources("cross_venue_dislocation")
    assert req == frozenset({"bbo-collector", "carnet-collector"})


def test_les_sources_requises_sont_reelles_dans_SOURCES_HARVEST():
    noms = {s.nom for s in SOURCES_HARVEST}
    for fam, sources in D.strategy_data_dependencies().items():
        for s in sources:
            assert s in noms, f"{fam} requiert une source absente de SOURCES_HARVEST: {s}"
