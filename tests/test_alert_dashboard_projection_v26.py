from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hl_observer.alerts.spine import (
    AlertSpinePaths,
    CanonicalAlertWriter,
    build_alert_proposal,
)
from hl_observer.config.settings import Settings
from hl_observer.ui.alert_projection_router import (
    alert_dashboard_capability_manifest,
    create_alert_projection_router,
    default_alert_projection_path,
)
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def _proposal() -> dict[str, object]:
    return build_alert_proposal(
        producer_id="dashboard-producer",
        producer_epoch="dashboard-epoch-1",
        producer_seq=1,
        source_id="primary-wire",
        source_uri="https://example.invalid/dashboard/1",
        source_content_hash=hashlib.sha256(b"dashboard-source").hexdigest(),
        observed_at_ms=1_000,
        fetched_at_ms=2_000,
        verified_at_ms=3_000,
        category="MARKET_EVENT",
        headline="Dashboard projection alert",
        dedup_key="dashboard:1",
        policy_version="dashboard-projection-test.v1",
        ingestion_code_sha="d" * 40,
        entity_ids=["asset:btc"],
        normalized_tickers=["BTC"],
        source_health_state="HEALTHY",
        freshness_state="FRESH",
        deterministic_score_components={"source_authority": 0.8},
        payload={"alert_family": "macro", "research_summary": "Primary evidence"},
    )


def _writer(root: Path) -> CanonicalAlertWriter:
    writer = CanonicalAlertWriter(
        AlertSpinePaths.from_root(root),
        clock_ms=lambda: 10_000,
    )
    writer.producer("dashboard-producer").submit(_proposal())
    writer.process_pending()
    return writer


def _client(projection_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_alert_projection_router(projection_path))
    return TestClient(app, raise_server_exceptions=False)


def test_dashboard_lit_projection_reelle_sans_muter_ledger(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine")
    projection_before = writer.paths.projection_path.read_bytes()
    projection_mtime_before = writer.paths.projection_path.stat().st_mtime_ns
    ledger_before = writer.paths.ledger_path.read_bytes()
    ledger_mtime_before = writer.paths.ledger_path.stat().st_mtime_ns
    client = _client(writer.paths.projection_path)

    response = client.get("/api/alerts/projection")

    assert response.status_code == 200
    assert response.json()["canonical_projection_hash"]
    assert response.json()["paper_read_only"] is True
    assert response.json()["real_execution"] is False
    assert writer.paths.projection_path.read_bytes() == projection_before
    assert writer.paths.projection_path.stat().st_mtime_ns == projection_mtime_before
    assert writer.paths.ledger_path.read_bytes() == ledger_before
    assert writer.paths.ledger_path.stat().st_mtime_ns == ledger_mtime_before
    assert client.post("/api/alerts/projection").status_code == 405
    assert client.post("/api/alerts/capabilities").status_code == 405


def test_dashboard_refuse_projection_absente_sans_reconstruire_ledger(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path / "spine")
    ledger_before = writer.paths.ledger_path.read_bytes()
    writer.paths.projection_path.unlink()

    response = _client(writer.paths.projection_path).get("/api/alerts/projection")

    assert response.status_code == 503
    assert response.json()["detail"] == "ALERT_PROJECTION_MISSING"
    assert not writer.paths.projection_path.exists()
    assert writer.paths.ledger_path.read_bytes() == ledger_before


def test_dashboard_refuse_projection_alteree_meme_si_json_valide(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path / "spine")
    projection = json.loads(writer.paths.projection_path.read_text(encoding="utf-8"))
    projection["materialized_read_model"]["latest_alerts"]["total_alerts"] = 999
    writer.paths.projection_path.write_text(
        json.dumps(projection, sort_keys=True),
        encoding="utf-8",
    )

    response = _client(writer.paths.projection_path).get("/api/alerts/projection")

    assert response.status_code == 503
    assert response.json()["detail"] == "ALERT_READ_MODEL_HASH_MISMATCH"


def test_capacites_dashboard_sont_uniquement_navigation_recherche() -> None:
    manifest = alert_dashboard_capability_manifest()
    forbidden = {
        "REWRITE_ALERT_SCORE",
        "MARK_EVIDENCE_VERIFIED",
        "MUTATE_GUARDIAN_STATE",
        "ENABLE_TRADING",
        "START_TESTNET_EXECUTION",
        "START_MAINNET_EXECUTION",
        "WRITE_CANONICAL_LEDGER",
    }

    assert manifest["ledger_access"] == "NONE"
    assert manifest["projection_access"] == "READ_ONLY"
    assert manifest["paper_read_only"] is True
    assert manifest["real_execution"] is False
    assert set(manifest["forbidden_authorities"]) == forbidden
    assert manifest["capabilities"]
    assert all(
        capability["kind"] == "RESEARCH_NAVIGATION"
        and capability["access"] == "READ"
        and capability["mutates_state"] is False
        for capability in manifest["capabilities"]
    )


def test_application_principale_monte_le_chemin_portable_de_projection(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch,
) -> None:
    tmp_path = tmp_path_factory.mktemp("ui")
    monkeypatch.delenv("HYPERSMART_ALERT_PROJECTION_PATH", raising=False)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'ui.sqlite3'}",
        logs_dir=tmp_path / "logs",
    )
    projection_path = default_alert_projection_path(settings)
    writer = _writer(projection_path.parents[1])
    assert writer.paths.projection_path == projection_path

    application = create_ui_app(settings, UiState())
    client = TestClient(application, raise_server_exceptions=False)
    response = client.get("/api/alerts/projection")

    assert response.status_code == 200
    assert response.json()["alert_count"] == 1
    source_routes = [
        source_route
        for included_route in application.routes
        for source_route in getattr(
            getattr(included_route, "original_router", None),
            "routes",
            (),
        )
    ]
    alert_routes = [
        route
        for route in source_routes
        if getattr(route, "path", "").startswith("/api/alerts/")
    ]
    assert {route.path for route in alert_routes} == {
        "/api/alerts/capabilities",
        "/api/alerts/projection",
    }
    assert all(set(route.methods or ()) <= {"GET", "HEAD"} for route in alert_routes)
