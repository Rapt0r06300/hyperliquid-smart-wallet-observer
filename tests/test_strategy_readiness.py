"""AUD-043 — READY_STRATEGIES : barrière PAR FAMILLE (données requises + warm-up), deny-by-default."""
from __future__ import annotations

from hl_observer.execution_core.warmup_barrier import BarriereWarmup
from hl_observer.strategies import strategy_readiness as R
from hl_observer.strategies.active_scope import active_strategy_families


def test_famille_ready_si_toutes_ses_sources_requises_pretes():
    etats = {"bbo-collector": "READY", "userfills-live": True, "allmids-collector": "OK"}
    r = R.ready_strategies(etats)
    assert r["lead_lag"].ready and r["lead_lag"].raison == "READY"
    assert r["cross_venue_dislocation"].ready
    assert r["copy_vault"].ready


def test_deny_by_default_si_source_requise_absente():
    r = R.ready_strategies({"allmids-collector": True})   # ni bbo, ni userfills
    assert r["lead_lag"].ready is False and "bbo-collector" in r["lead_lag"].missing_sources
    assert r["copy_vault"].ready is False and "userfills-live" in r["copy_vault"].missing_sources


def test_source_presente_mais_pas_prete_bloque():
    r = R.ready_strategies({"bbo-collector": "DOWN"})      # présente mais pas READY
    assert r["lead_lag"].ready is False and "bbo-collector" in r["lead_lag"].missing_sources


def test_granularite_par_famille_distincte_de_ready_core():
    r = R.ready_strategies({"bbo-collector": True})
    assert r["lead_lag"].ready is True
    assert r["copy_vault"].ready is False


def test_warmup_incomplet_bloque_puis_debloque():
    w = BarriereWarmup()
    w.exiger("lead_lag", buffer="bbo", minimum=100)
    r = R.ready_strategies({"bbo-collector": True}, warmup=w)
    assert r["lead_lag"].ready is False and r["lead_lag"].raison == "WARMUP_INCOMPLET"
    w.observer("lead_lag", buffer="bbo", n=100)
    r2 = R.ready_strategies({"bbo-collector": True}, warmup=w)
    assert r2["lead_lag"].ready is True


def test_famille_sans_dependance_declaree_reste_non_ready(monkeypatch):
    monkeypatch.setattr(R, "active_strategy_families", lambda: frozenset({"lead_lag"}))
    monkeypatch.setattr(R, "required_sources", lambda _fam: frozenset())

    r = R.ready_strategies({})

    assert r["lead_lag"].ready is False
    assert r["lead_lag"].data_ready is False
    assert r["lead_lag"].missing_sources == frozenset()
    assert r["lead_lag"].raison == "AUCUNE_DEPENDANCE_DECLAREE"


def test_all_active_families_ready():
    tout = {"bbo-collector": True, "userfills-live": True, "allmids-collector": True}
    assert R.all_active_families_ready(tout) is True
    assert R.all_active_families_ready({"bbo-collector": True}) is False
    assert R.families_ready(tout) == frozenset(active_strategy_families())
