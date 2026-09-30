from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hl_observer.alerts.coverage import load_source_coverage_universe
from hl_observer.alerts.coverage_runtime import read_runtime_coverage_observations
from hl_observer.ui.alert_projection_router import create_alert_projection_router
from tools import collecter_allmids as collector

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "config/alerts/source_coverage_universe.json"
NOW = 10_000


def _cache(root: Path, *, mode: str = "LIVE") -> Path:
    collector.ecrire_cache(
        root, {"BTC": 60_000.0}, fetched_at_ms=9_500,
        transport_latency_ms=12.5, data_mode=mode,
    )
    return root / collector.SORTIE


def _read(root: Path, now: int = NOW) -> tuple[list, list]:
    return read_runtime_coverage_observations(
        root, load_source_coverage_universe(UNIVERSE), evaluated_at_ms=now,
    )


def test_collecteur_actif_mesure_la_requete_et_identifie_les_fixtures(tmp_path: Path) -> None:
    assert collector.une_passe(tmp_path, post_allmids=lambda: {"BTC": "60000"}) == 1
    payload = json.loads((tmp_path / collector.SORTIE).read_bytes())
    capture = payload["coverage_capture"]
    assert capture["data_mode"] == "TEST_FIXTURE"
    assert capture["transport_latency_ms"] >= 0
    assert capture["fetched_at_ms"] == payload["ts_ms"]
    assert capture["endpoint"] == "https://api.hyperliquid.xyz/info"
    assert capture["request_type"] == "allMids"
    assert capture["paper_read_only"] is True
    assert capture["real_execution"] is False


@pytest.mark.parametrize("value", ["inf", "Infinity", float("inf"), True, False])
def test_prix_non_fini_ou_booleen_ne_valide_pas_un_echantillon(value: object) -> None:
    assert collector.parser_allmids({"BTC": value}) == {}


def test_cache_reel_lisible_borne_sans_ecriture_ni_droits_inventes(tmp_path: Path) -> None:
    path = _cache(tmp_path)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    observations, diagnostics = _read(tmp_path)
    assert len(observations) == 1
    observation = observations[0]
    assert observation["source_id"] == "hyperliquid-info-allmids"
    assert observation["connection_state"] == "CONNECTED"
    assert observation["source_status"] == "HEALTHY"
    assert observation["latency_ms"] == 12.5
    assert observation["last_successful_refresh_ms"] == 9_500
    assert observation["entitlement"] == observation["license_class"] == "UNKNOWN"
    assert diagnostics[0]["validation_scope"] == "LOCAL_COLLECTOR_RESPONSE_NOT_GLOBAL_COVERAGE"
    assert diagnostics[0]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert before == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_cache_perime_ne_devient_pas_connecte_et_latence_reste_la_mesure(tmp_path: Path) -> None:
    _cache(tmp_path)
    observations, diagnostics = _read(tmp_path, now=20_000)
    assert observations[0]["connection_state"] == "UNKNOWN"
    assert observations[0]["source_status"] == "STALE"
    assert observations[0]["latency_ms"] == 12.5
    assert diagnostics[0]["age_ms"] == 10_500


@pytest.mark.parametrize("mutation", ["hash", "future", "schema", "safety", "endpoint", "size", "missing_capture"])
def test_cache_invalide_ou_incomplet_refuse_sans_inventer_de_connexion(tmp_path: Path, mutation: str) -> None:
    path = _cache(tmp_path)
    payload = json.loads(path.read_bytes())
    if mutation == "hash":
        payload["mids"]["BTC"] += 1
    elif mutation == "future":
        collector.ecrire_cache(tmp_path, {"BTC": 1.0}, fetched_at_ms=NOW + 1,
                              transport_latency_ms=2.0, data_mode="LIVE")
        payload = json.loads(path.read_bytes())
    elif mutation == "schema":
        payload["coverage_capture"]["schema_version"] = "untrusted.v2"
    elif mutation == "safety":
        payload["coverage_capture"]["real_execution"] = True
    elif mutation == "endpoint":
        payload["coverage_capture"]["endpoint"] = "https://example.invalid/info"
    elif mutation == "size":
        payload["extra"] = "x" * 1_048_577
    else:
        del payload["coverage_capture"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()
    observations, diagnostics = _read(tmp_path)
    assert observations == []
    assert diagnostics[0]["state"] == "REJECTED"
    assert path.read_bytes() == before


def test_fixture_ne_s_infiltre_pas_dans_la_couverture_live(tmp_path: Path) -> None:
    _cache(tmp_path, mode="TEST_FIXTURE")
    observations, diagnostics = _read(tmp_path)
    assert observations == []
    assert diagnostics[0]["reason"] == "NON_LIVE_CAPTURE"


def test_chemin_absent_ne_cree_rien(tmp_path: Path) -> None:
    observations, diagnostics = _read(tmp_path)
    assert observations == []
    assert diagnostics[0]["state"] == "MISSING"
    assert list(tmp_path.iterdir()) == []


def test_endpoint_couverture_recalcule_les_ages_sans_toucher_ledger(tmp_path: Path) -> None:
    _cache(tmp_path)
    clock = [NOW]
    app = FastAPI()
    app.include_router(create_alert_projection_router(
        tmp_path / "runtime/data/alert_spine/projections/alerts_dashboard.json",
        clock_ms=lambda: clock[0], coverage_root=tmp_path, coverage_universe_path=UNIVERSE,
    ))
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    with TestClient(app) as client:
        first = client.get("/api/alerts/coverage")
        assert first.status_code == 200
        payload = first.json()
        assert payload["coverage_receipt"]["counts"]["actually_connected_sources"] == 1
        assert payload["coverage_receipt"]["operational_state"] == "BLOCKED"
        assert payload["completeness_attestation"]["coverage_state"] == "COVERAGE_UNKNOWN"
        clock[0] += 10_000
        second = client.get("/api/alerts/coverage").json()
        assert second["coverage_receipt"]["counts"]["actually_connected_sources"] == 0
        assert client.post("/api/alerts/coverage", json={"operational_state": "READY"}).status_code == 405
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


def test_endpoint_configuration_manquante_refuse_au_lieu_de_retourner_vert(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(create_alert_projection_router(
        tmp_path / "alerts_dashboard.json", coverage_root=tmp_path,
        coverage_universe_path=tmp_path / "missing.json",
    ))
    with TestClient(app) as client:
        assert client.get("/api/alerts/coverage").status_code == 503
