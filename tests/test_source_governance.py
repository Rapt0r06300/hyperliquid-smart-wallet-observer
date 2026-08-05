from hl_observer.research.source_governance import (
    RegistreBlockedExternal, cache_paye_expire, politique_basse_latence, pin_versions_endpoints,
    RegistreLicences, politique_cle_read_only, RegistreConformite, sla_source,
    dashboard_sante_mesh, checklist_onboarding, politique_retrait)


def test_registre_blocked_external():
    r = RegistreBlockedExternal()
    r.bloquer("bybit", raison="reseau live", condition_levee="acces reseau + credentials read-only")
    assert r.est_bloque("bybit") is True and r.lister()[0]["raison"] == "reseau live"


def test_cache_paye_expire():
    assert cache_paye_expire(0.0, 3600.0, 4000.0)["expire"] is True
    assert cache_paye_expire(0.0, 3600.0, 1000.0)["expire"] is False


def test_politique_basse_latence():
    assert politique_basse_latence("nansen")["basse_latence_autorisee"] is False
    assert politique_basse_latence("hyperliquid")["basse_latence_autorisee"] is True


def test_pin_versions_endpoints():
    cfg = {"binance": {"version": "v3", "endpoint": "wss://..."}, "okx": {"version": "latest", "endpoint": "x"}}
    r = pin_versions_endpoints(cfg)
    assert r["toutes_pinnees"] is False and r["non_pinnees"] == ["okx"]


def test_registre_licences_et_quota():
    r = RegistreLicences()
    r.enregistrer("nansen", licence="pro", quota_req_jour=1000, cout_usd_mois=150.0)
    assert r.cout_total_mois() == 150.0
    assert r.quota_depasse("nansen", 1500)["depasse"] is True


def test_politique_cle_read_only():
    assert politique_cle_read_only(["read", "market_data"])["read_only"] is True
    assert politique_cle_read_only(["read", "withdraw"])["read_only"] is False


def test_conformite_et_sla():
    c = RegistreConformite()
    c.revue("binance", "OK")
    assert c.utilisable("binance") is True and c.utilisable("inconnue") is False
    assert sla_source({"disponibilite": 0.999, "latence_ms": 50})["respecte_sla"] is True
    assert sla_source({"disponibilite": 0.5, "latence_ms": 50})["respecte_sla"] is False


def test_dashboard_checklist_retrait():
    d = dashboard_sante_mesh({"a": "OK", "b": "DOWN"})
    assert d["global_ok"] is False and d["down"] == ["b"]
    assert checklist_onboarding({"licence": 1, "endpoint": 1, "replay": 1, "lineage": 1, "sla": 1})["complet"] is True
    assert politique_retrait({"consommateurs_prevenus": True})["retirable"] is False
