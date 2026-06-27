"""Fast, read-only /api/simulation/status: flips the dashboard badge in <2s even
while the heavy /api/simulation/overview is still computing."""

from __future__ import annotations

import os
import json
import time

for _k in list(os.environ):
    if "proxy" in _k.lower():
        os.environ.pop(_k, None)

from starlette.testclient import TestClient
from hl_observer.cli import _settings
from hl_observer.ui.persistent_state import simulation_state_path
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState
from hl_observer.ui.v12_status_provider import build_v12_status_payload
from hl_observer.storage.v12_sqlite_store import V12SQLiteStore
from hl_observer.utils.time import now_ms


def test_status_is_fast_and_readonly():
    client = TestClient(create_ui_app(_settings()), raise_server_exceptions=False)
    t0 = time.time()
    r = client.get("/api/simulation/status")
    elapsed = time.time() - t0
    assert r.status_code == 200
    d = r.json()
    assert d["running"] is True
    assert d["read_only"] is True
    assert "equity_usdt" in d and "net_pnl_usdt" in d
    assert d["open_positions"] >= 0
    assert elapsed < 2.0, f"status endpoint too slow: {elapsed:.2f}s (must not hit heavy path)"


def test_status_exposes_v12_capabilities_without_fake_runtime_health():
    client = TestClient(create_ui_app(_settings()), raise_server_exceptions=False)
    payload = client.get("/api/simulation/status").json()
    v12 = payload["v12"]

    assert v12["venue_default"] == "Hyperliquid"
    assert v12["mode"] == "LOCAL_PAPER_SIMULATION_ONLY"
    assert v12["data_truth"] == "real_or_empty"
    assert v12["no_fake_data"] is True
    assert v12["external_action"] is False
    assert v12["capabilities"]["paper_engine_wrapper"] == "available"
    assert v12["capabilities"]["leader_delta"] == "available"
    assert v12["feature_schema"]["columns"] >= 70
    assert v12["feature_schema"]["feature_hash_required"] is True
    assert v12["source_health"]["available"] is False
    assert v12["capabilities"]["decision_pipeline"] == "available"
    assert v12["v12_store"]["available"] is False


def test_v12_status_reads_sqlite_artifact_counts_without_fake_rows(tmp_path):
    db_path = tmp_path / "v12.sqlite3"
    store = V12SQLiteStore(db_path)
    store.initialize()

    payload = build_v12_status_payload(
        engine_status={"metrics": {"v12_sqlite_path": str(db_path)}},
        scanner={"entry_supply": {"summary": "test"}},
    )

    assert payload["v12_store"]["available"] is True
    assert payload["v12_store"]["counts"] == {
        "wallet_scores": 0,
        "signal_clusters": 0,
        "edge_estimates": 0,
        "decision_evidence": 0,
    }


def test_simulation_page_marks_backend_offline_instead_of_fake_starting():
    page = (
        __import__("pathlib").Path("src/hl_observer/ui/static/simulation_v2.html")
        .read_text(encoding="utf-8", errors="replace")
    )

    assert "function markBackendOffline()" in page
    assert "Serveur local hors ligne" in page
    assert "SERVER_OFFLINE" in page
    assert "relance LANCER_HYPERSMART.cmd" in page


def test_simulation_page_does_not_hide_engine_status_with_generic_badge():
    page = (
        __import__("pathlib").Path("src/hl_observer/ui/static/simulation_v2.html")
        .read_text(encoding="utf-8", errors="replace")
    )

    assert "Hyperliquid · moteur actif" in page
    assert "Serveur OK · moteur a relancer" in page
    assert 'applyFastStatusTick(s);' in page
    assert 'includes("moteur")' in page
    assert 'if(s&&s.running){ $("#bStatus").textContent="Hyperliquid · lecture seule"; }' not in page


def test_simulation_routes_do_not_block_event_loop_with_sync_sqlite_work():
    routes = (
        __import__("pathlib").Path("src/hl_observer/ui/routes.py")
        .read_text(encoding="utf-8", errors="replace")
    )
    status_routes = (
        __import__("pathlib").Path("src/hl_observer/ui/status_routes.py")
        .read_text(encoding="utf-8", errors="replace")
    )

    assert "def simulation_status() -> dict[str, Any]:" in status_routes
    assert "def simulation_overview(limit: int = 500) -> dict[str, Any]:" in routes
    assert "async def simulation_status" not in status_routes
    assert "async def simulation_overview" not in routes


def test_status_uses_latest_persisted_equity_point_without_heavy_overview():
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = 3.0
    state.simulation_equity_history = [
        {"current_equity_usdt": 1004.25, "current_pnl_usdc": 4.25, "timestamp_ms": 123}
    ]
    client = TestClient(create_ui_app(_settings(), state=state), raise_server_exceptions=False)

    payload = client.get("/api/simulation/status").json()

    assert payload["equity_usdt"] == 1004.25
    assert payload["net_pnl_usdt"] == 4.25
    assert payload["realized_pnl_usdt"] == 3.0


def test_status_exposes_engine_heartbeat_without_heavy_overview(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    heartbeat_path = simulation_state_path(settings).parent / "hypersmart_engine_status.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at_ms": int(time.time() * 1000),
                "phase": "live_user_fills_scan",
                "message": "Lecture WebSocket userFills read-only sur shortlist bornee.",
                "poll_index": 7,
                "max_runs": 5760,
                "pool": 50,
                "leaders_per_poll": 10,
                "read_only": True,
                "simulation_only": True,
                "external_action": False,
                "metrics": {
                    "wallet_candidates_total": "924718",
                    "leaders_selected": "18334",
                    "fresh_leaders_selected": "50",
                    "fresh_entry_deltas": "1194",
                    "virtual_entries_logged": "3",
                    "virtual_refusals_logged": "14",
                },
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_ui_app(settings), raise_server_exceptions=False)

    payload = client.get("/api/simulation/status").json()

    assert payload["engine_running"] is True
    assert payload["engine_status"]["phase"] == "live_user_fills_scan"
    assert payload["scanner"]["fresh_leaders_selected"] == 50
    assert payload["scanner"]["wallet_candidates_total"] == 924718
    assert payload["scanner"]["fresh_entry_deltas"] == 1194
    assert payload["scanner"]["virtual_entries_logged"] == 3
    assert payload["scanner"]["external_action"] is False
    assert payload["scanner"]["entry_supply_bottleneck"] == "OK"
    assert payload["scanner"]["entry_supply"]["summary"]


def test_status_entry_supply_reports_no_data_when_engine_has_no_context(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    heartbeat_path = simulation_state_path(settings).parent / "hypersmart_engine_status.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at_ms": int(time.time() * 1000),
                "phase": "startup",
                "message": "Demarrage du moteur.",
                "read_only": True,
                "simulation_only": True,
                "external_action": False,
                "metrics": {},
            }
        ),
        encoding="utf-8",
    )
    payload = TestClient(create_ui_app(settings), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["scanner"]["entry_supply_bottleneck"] == "NO_DATA"
    assert payload["scanner"]["entry_supply"]["severity"] == "error"
    assert "collecte" in payload["scanner"]["entry_supply_next_action"].lower()


def test_status_entry_supply_reports_supply_when_context_exists_but_no_fresh_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    heartbeat_path = simulation_state_path(settings).parent / "hypersmart_engine_status.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at_ms": int(time.time() * 1000),
                "phase": "live_public_scan",
                "message": "Flux public lu, aucun delta entry frais.",
                "read_only": True,
                "simulation_only": True,
                "external_action": False,
                "metrics": {
                    "wallet_candidates_total": 250,
                    "public_trade_events": 900,
                    "position_deltas_total": 34,
                    "fresh_entry_deltas": 0,
                    "virtual_entries_logged": 0,
                    "virtual_refusals_logged": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    payload = TestClient(create_ui_app(settings), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["scanner"]["entry_supply_bottleneck"] == "SUPPLY"
    assert payload["scanner"]["entry_supply"]["observed_context"] == 1184
    assert "fraiches" in payload["scanner"]["entry_supply_summary"]


def test_status_entry_supply_reports_gates_when_fresh_entries_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    heartbeat_path = simulation_state_path(settings).parent / "hypersmart_engine_status.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at_ms": int(time.time() * 1000),
                "phase": "live_user_fills_scan",
                "message": "Entrees fraiches vues mais refusees.",
                "read_only": True,
                "simulation_only": True,
                "external_action": False,
                "metrics": {
                    "wallet_candidates_total": 50,
                    "position_deltas_total": 12,
                    "fresh_entry_deltas": 6,
                    "virtual_entries_logged": 0,
                    "virtual_refusals_logged": 6,
                },
            }
        ),
        encoding="utf-8",
    )
    payload = TestClient(create_ui_app(settings), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["scanner"]["entry_supply_bottleneck"] == "GATES"
    assert payload["scanner"]["entry_supply"]["fresh_entry_deltas"] == 6
    assert "edge" in payload["scanner"]["entry_supply_next_action"].lower()


def test_status_does_not_report_finished_poller_as_running(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    heartbeat_path = simulation_state_path(settings).parent / "hypersmart_engine_status.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at_ms": int(time.time() * 1000),
                "phase": "finished",
                "message": "Poller simulation termine.",
                "read_only": True,
                "simulation_only": True,
                "external_action": False,
                "metrics": {},
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_ui_app(settings), raise_server_exceptions=False)

    payload = client.get("/api/simulation/status").json()

    assert payload["server_running"] is True
    assert payload["engine_running"] is False
    assert payload["scanner"]["phase"] == "finished"


def test_status_marks_existing_paper_position_with_latest_hyperliquid_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    leader = "0x" + "a" * 40
    state = UiState()
    state.simulation_started_at_ms = now_ms() - 2_000
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = -0.02
    state.simulation_virtual_positions = {
        f"{leader}|ETH|LONG": {
            "wallet_address": leader,
            "coin": "ETH",
            "direction": "LONG",
            "size": 0.1,
            "avg_price": 2000.0,
            "entry_costs": 0.02,
            "opened_at_ms": state.simulation_started_at_ms,
            "last_update_at_ms": state.simulation_started_at_ms,
            "source_delta_key": "hash:paper-entry",
            "position_mode": "SINGLE_LEADER",
            "leader_wallets_csv": leader,
        }
    }
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=now_ms(), raw_json={"ETH": "2010"}))
        session.commit()

    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    # LONG 0.1 ETH from 2000 to 2010 = +1.00 gross.
    # Fast status uses the same conservative exit-cost model: 201 USDT * 12 bps = 0.2412.
    # Realized entry cost already paid in state: -0.02. Expected net = 1 - 0.2412 - 0.02.
    assert payload["open_positions"] == 1
    assert payload["mark_to_market"]["source"] == "LIVE_HYPERLIQUID_ALLMIDS_OR_LOCAL_SNAPSHOTS"
    assert payload["mark_to_market"]["marks_used"] == 1
    assert payload["mark_to_market"]["no_fallback_position_created"] is True
    assert payload["positions"][0]["market_mark_available"] is True
    assert payload["positions"][0]["mark_price"] == 2010.0
    assert payload["positions"][0]["gross_unrealized_pnl_usdc"] == 1.0
    assert payload["positions"][0]["mark_age_ms"] is not None
    assert payload["mark_diagnostics"]["graph_should_move"] is True
    assert payload["mark_diagnostics"]["marks_used"] == 1
    assert payload["mark_diagnostics"]["positions"][0]["reason"] == "OK_REAL_MARK"
    assert payload["positions"][0]["unrealized_pnl_usdc"] == 0.7588
    assert payload["equity_usdt"] == 1000.7388
    assert payload["net_pnl_usdt"] == 0.7388
    assert state.simulation_equity_history[-1]["source"] == "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID"


def test_status_can_mark_open_position_from_live_all_mids_when_launcher_enables_it(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HYPERSMART_STATUS_LIVE_MARKS_ENABLED", "1")
    settings = _settings()
    from hl_observer.storage.database import init_db
    import hl_observer.ui.status_routes as status_routes

    init_db(settings.database_url)
    leader = "0x" + "c" * 40
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = 0.0
    state.simulation_virtual_positions = {
        f"{leader}|HYPE|SHORT": {
            "wallet_address": leader,
            "coin": "HYPE",
            "direction": "SHORT",
            "size": 3.0,
            "avg_price": 70.0,
            "source_delta_key": "hash:paper-short-live",
        }
    }

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"HYPE": "69.5", "BTC": "65000"}

    class _Client:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, json):
            assert url.endswith("/info")
            assert json == {"type": "allMids"}
            return _Response()

    monkeypatch.setattr(status_routes.httpx, "Client", _Client)

    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["open_positions"] == 1
    assert payload["mark_to_market"]["read_status"] == "OK_LIVE_ALLMIDS"
    assert payload["mark_to_market"]["endpoint"] == "/info"
    assert payload["mark_to_market"]["request_type"] == "allMids"
    assert payload["positions"][0]["mark_source"] == "liveAllMidsStatus"
    assert payload["positions"][0]["mark_price"] == 69.5
    assert payload["net_pnl_usdt"] > 1.0


def test_status_never_creates_fallback_position_without_signal(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=now_ms(), raw_json={"BTC": "65000"}))
        session.commit()

    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["open_positions"] == 0
    assert payload["positions"] == []
    assert payload["equity_usdt"] == 1000.0
    assert payload["net_pnl_usdt"] == 0.0
    assert payload["mark_to_market"]["read_status"] == "NO_OPEN_POSITION"
    assert payload["mark_to_market"]["no_fallback_position_created"] is True


def test_status_does_not_fake_market_movement_when_mark_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    leader = "0x" + "b" * 40
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = -0.03
    state.simulation_virtual_positions = {
        f"{leader}|ETH|SHORT": {
            "wallet_address": leader,
            "coin": "ETH",
            "direction": "SHORT",
            "size": 0.2,
            "avg_price": 2000.0,
            "source_delta_key": "hash:paper-short",
        }
    }
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=now_ms(), raw_json={"BTC": "65000"}))
        session.commit()

    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["open_positions"] == 1
    assert payload["mark_to_market"]["marks_used"] == 0
    assert payload["mark_to_market"]["marks_missing"] == 1
    assert payload["positions"][0]["market_mark_available"] is False
    assert payload["positions"][0]["unrealized_pnl_usdc"] == 0.0
    assert payload["mark_diagnostics"]["graph_should_move"] is False
    assert payload["mark_diagnostics"]["flat_graph_reason"] == "NO_REAL_MARK_FOR_OPEN_POSITION"
    assert payload["mark_diagnostics"]["positions"][0]["reason"] == "MISSING_REAL_MARK"
    assert payload["net_pnl_usdt"] == -0.03


def test_simulation_page_uses_stable_single_writer_panels():
    page = (
        __import__("pathlib").Path("src/hl_observer/ui/static/simulation_v2.html")
        .read_text(encoding="utf-8", errors="replace")
    )

    assert "overflow-anchor:none" in page
    assert "html{min-height:100%;overflow-y:scroll;overflow-x:hidden;scrollbar-gutter:stable both-edges;overflow-anchor:none}" in page
    assert "scrollbar-gutter:stable" in page
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in page
    assert "min-height:238px" in page
    assert "function setStablePanelHtml" in page
    assert "function stableReasonEntries" in page
    assert "function writeHtmlStableViewport" in page
    assert "function restorePageScroll" in page
    assert "lastUserScrollAt" in page
    assert "suppressScrollEventUntil" in page
    assert 'window.addEventListener("scroll"' in page
    assert "Date.now()-lastUserScrollAt<180" in page
    assert "const beforeHeight=document.documentElement.scrollHeight" in page
    assert "const afterHeight=document.documentElement.scrollHeight" in page
    assert "if(Math.abs(afterHeight-beforeHeight)>1)" in page
    assert "requestAnimationFrame(()=>restorePageScroll(page))" in page
    assert "lastPositionsHtml=setStablePanelHtml" in page
    assert "lastDecisionHtml=setStablePanelHtml" in page
    assert "stableReasonEntries(status.no_trade_reasons,8)" in page
    assert "function renderOverviewScanPanel" in page
    assert "renderOverviewScanPanel(statusPayload,statusPayload.wallets||[])" in page
    assert "Diagnostic opportunites" in page
    assert "scanner.entry_supply_summary" in page
    assert "const mergedLive=mergeStatusWithFreshTick(status,positions)" in page
    assert "if(liveStatusIsFresh(1200))return;" in page


def test_simulation_page_keeps_below_graph_layout_stable():
    page = (
        __import__("pathlib").Path("src/hl_observer/ui/static/simulation_v2.html")
        .read_text(encoding="utf-8", errors="replace")
    )

    assert ".cols{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;align-items:start;overflow-anchor:none;contain:layout paint;min-height:336px}" in page
    assert ".col h3{font-size:15px;font-weight:600;margin:0 0 10px;height:24px;line-height:24px}" in page
    assert ".dec{display:flex;gap:9px;align-items:flex-start;padding:7px 0;border-bottom:1px solid var(--line);font-size:14px;min-height:38px}" in page
    assert ".graphhead .conn{min-width:190px;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" in page
