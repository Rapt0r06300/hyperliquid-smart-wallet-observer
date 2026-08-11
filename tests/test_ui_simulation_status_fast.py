"""Fast, read-only /api/simulation/status: flips the dashboard badge in <2s even
while the heavy /api/simulation/overview is still computing."""

from __future__ import annotations

import os
import json
import time
from pathlib import Path

for _k in list(os.environ):
    if "proxy" in _k.lower():
        os.environ.pop(_k, None)

import pytest

from starlette.testclient import TestClient
from hl_observer.collection.l2_snapshot_cache import clear as clear_l2_cache
from hl_observer.collection.l2_snapshot_cache import push_book
from hl_observer.cli import _settings
from hl_observer.ui.persistent_state import simulation_state_path
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.fusion_status_provider import FUSION_STATUS_LOG_FILENAME
from hl_observer.ui.status_routes import (
    _copy_position_quality_exit_reason,
    _dedupe_equity_history_timestamps,
    _ledger_closed_trade_stats,
)
from hl_observer.ui.state import UiState
from hl_observer.ui.v12_status_provider import build_v12_status_payload
from hl_observer.storage.v12_sqlite_store import V12SQLiteStore
from hl_observer.utils.time import now_ms



@pytest.fixture(autouse=True)
def _planchers_permissifs_pour_tester_la_persistance(monkeypatch):
    """ISOLATION (audit 2026-07-11).

    Ce fichier teste la PERSISTANCE du ledger / de l'etat UI (les entrees survivent-elles a un
    refresh ? le PnL est-il conserve ?). Il ne teste PAS les gates d'edge -- ceux-la ont leurs
    propres tests dedies, avec leurs vraies valeurs.

    Or les planchers d'edge ont ete DURCIS depuis (single-wallet 55 bps, degradation, liquidite).
    Resultat : la simulation REFUSAIT toutes les entrees des fixtures (SINGLE_WALLET_EDGE_TOO_LOW)
    et des tests de persistance echouaient -- alors que le code avait RAISON de refuser.
    Ces tests etaient invisibles : la suite ne tournait jamais jusqu'au bout.

    On rend donc les gates permissifs UNIQUEMENT ici, pour que le sujet du test (la persistance)
    soit reellement exerce.
    """
    for var, val in (
        ("HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS", "1"),
        ("HYPERSMART_SIMULATION_MIN_EDGE_BPS", "1"),
        ("HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE", "0.0"),
        ("HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS", "500"),
        ("HYPERSMART_SIMULATION_MIN_EXPECTED_EDGE_USDT", "0"),
        # consensus minimum : les fixtures n'ont souvent qu'1 wallet
        ("HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS", "1"),
        ("HYPERSMART_FUSION_COPY_MIN_WALLETS", "1"),
        ("HYPERSMART_DIRECT_COPY_MIN_CONSENSUS_WALLETS", "1"),
        ("HYPERSMART_DIRECT_COPY_MIN_EDGE_BPS", "1"),
        ("HYPERSMART_DIRECT_COPY_MIN_LIQUIDITY", "0.0"),
        # sans allMids en test, le prix du leader sert de mid (sinon veto CURRENT_MID_REQUIRED)
        ("HYPERSMART_LEADER_MID_FALLBACK_MAX_AGE_MS", "600000"),
    ):
        monkeypatch.setenv(var, val)


@pytest.fixture(autouse=True)
def _isolate_recorded_execution_books():
    clear_l2_cache()
    yield
    clear_l2_cache()


def _seed_recorded_execution_book(monkeypatch, *, coin: str, mid: float, observed_at_ms: int) -> None:
    """Give persistence tests the exact recorded L2 truth needed for a fill."""

    monkeypatch.setenv("HYPERSMART_V26_LIVE_BOOK_COSTS", "1")
    # These tests exercise persistence, not empirical-edge calibration. The
    # legacy proxy is therefore enabled explicitly and remains test-local.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    push_book(
        coin,
        bids=((mid - 0.01, 10_000.0),),
        asks=((mid + 0.01, 10_000.0),),
        received_ts_ms=observed_at_ms,
        exchange_ts_ms=max(1, observed_at_ms - 1),
        source="recorded_hyperliquid_l2_fixture",
    )


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


def test_status_does_not_resurrect_historical_equity_without_current_mark():
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = 3.0
    state.simulation_equity_history = [
        {"current_equity_usdt": 1004.25, "current_pnl_usdc": 4.25, "timestamp_ms": 123}
    ]
    client = TestClient(create_ui_app(_settings(), state=state), raise_server_exceptions=False)

    payload = client.get("/api/simulation/status").json()

    assert payload["equity_usdt"] == 1003.0
    assert payload["net_pnl_usdt"] == 3.0
    assert payload["realized_pnl_usdt"] == 3.0
    assert payload["status_projection_pure"] is True
    assert payload["network_reads_from_status"] is False

def test_status_exposes_normal_pnl_ledger_spike_links_without_heavy_overview():
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = 1.3
    base_ms = 1_800_000_000_000
    state.simulation_equity_history = [
        {"current_equity_usdt": 1000.0, "current_pnl_usdc": 0.0, "timestamp_ms": base_ms},
        {"current_equity_usdt": 1001.3, "current_pnl_usdc": 1.3, "timestamp_ms": base_ms + 500},
    ]
    state.simulation_ledger_events = [
        {
            "delta_key": "fast-status-ledger-close",
            "observed_at_ms": base_ms + 500,
            "coin": "HYPE",
            "paper_action_type": "CLOSE",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "estimated_net_pnl_usdc": 1.3,
            "evidence_hash": "ev:fast-status",
        }
    ]
    client = TestClient(create_ui_app(_settings(), state=state), raise_server_exceptions=False)

    payload = client.get("/api/simulation/status").json()

    ledger = payload["paper_ledger"]
    assert ledger["reconciliation"]["ok"] is True
    assert ledger["spike_links"]["spike_count"] == 1
    assert ledger["spike_links"]["unexplained_spike_count"] == 0
    assert ledger["spike_links"]["recent_spikes"][-1]["nearby_ledger_events"][0]["delta_key"] == "fast-status-ledger-close"


def test_closed_trade_stats_keep_entry_context_for_pnl_debugging():
    stats = _ledger_closed_trade_stats(
        [
            {
                "delta_key": "entry-hype-1",
                "source_delta_key": "leader-open-1",
                "paper_position_instance_id": "paper-pos-1",
                "observed_at_ms": 1_000,
                "coin": "HYPE",
                "leader_side": "LONG",
                "paper_action_type": "OPEN",
                "bot_replay_action": "PAPER_OPEN_REPLAYED",
                "entry_price": 100.0,
                "edge_remaining_bps": 52.5,
                "signal_age_ms": 1_200,
                "copy_degradation_bps": 8.0,
                "consensus_wallets": 3,
                "copied_notional_usdt": 75.0,
                "position_mode": "CONSENSUS_OPEN",
                "evidence_hash": "ev:open",
            },
            {
                "delta_key": "close-hype-1",
                "source_delta_key": "leader-open-1",
                "paper_position_instance_id": "paper-pos-1",
                "observed_at_ms": 2_000,
                "coin": "HYPE",
                "leader_side": "LONG",
                "paper_action_type": "CLOSE",
                "bot_replay_action": "PAPER_CLOSE_REPLAYED",
                "entry_price": 100.0,
                "exit_price": 101.0,
                "estimated_net_pnl_usdc": 0.55,
                "fee_cost_usdc": 0.05,
            },
        ]
    )

    closed = stats["recent_closed_trades"][-1]
    assert stats["entry_context_found"] == 1
    assert stats["entry_context_missing"] == 0
    assert closed["entry_context_found"] is True
    assert closed["entry_delta_key"] == "entry-hype-1"
    assert closed["entry_edge_remaining_bps"] == 52.5
    assert closed["entry_signal_age_ms"] == 1_200
    assert closed["entry_consensus_wallets"] == 3
    assert closed["entry_copied_notional_usdt"] == 75.0


def test_status_does_not_explain_pnl_spike_with_no_trade_context_only():
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    base_ms = 1_800_000_000_000
    state.simulation_equity_history = [
        {"current_equity_usdt": 1000.0, "current_pnl_usdc": 0.0, "timestamp_ms": base_ms},
        {"current_equity_usdt": 998.8, "current_pnl_usdc": -1.2, "timestamp_ms": base_ms + 500},
    ]
    state.simulation_ledger_events = [
        {
            "delta_key": "nearby-no-trade-context",
            "observed_at_ms": base_ms + 500,
            "coin": "HYPE",
            "paper_action_type": "NO_TRADE",
            "bot_replay_action": "NO_TRADE",
            "status": "REJECT_NO_TRADE",
            "reason": "EDGE_REMAINING_TOO_LOW",
            "evidence_hash": "ev:no-trade",
        }
    ]
    client = TestClient(create_ui_app(_settings(), state=state), raise_server_exceptions=False)

    payload = client.get("/api/simulation/status").json()

    spike = payload["paper_ledger"]["spike_links"]["recent_spikes"][-1]
    assert payload["paper_ledger"]["spike_links"]["spike_count"] == 1
    assert payload["paper_ledger"]["spike_links"]["unexplained_spike_count"] == 1
    assert spike["nearby_ledger_events_count"] == 0
    assert spike["nearby_context_events_count"] == 1
    assert spike["nearby_context_events"][0]["delta_key"] == "nearby-no-trade-context"


def test_status_explains_fast_mark_to_market_jump_without_ledger_event():
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    base_ms = 1_800_000_000_000
    state.simulation_equity_history = [
        {
            "current_equity_usdt": 1000.0,
            "current_pnl_usdc": 0.0,
            "timestamp_ms": base_ms,
            "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID",
            "open_positions": 2,
        },
        {
            "current_equity_usdt": 1001.1,
            "current_pnl_usdc": 1.1,
            "timestamp_ms": base_ms + 500,
            "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID",
            "open_positions": 2,
        },
    ]
    state.simulation_ledger_events = []
    client = TestClient(create_ui_app(_settings(), state=state), raise_server_exceptions=False)

    payload = client.get("/api/simulation/status").json()

    spike_links = payload["paper_ledger"]["spike_links"]
    spike = spike_links["recent_spikes"][-1]
    assert spike_links["spike_count"] == 1
    assert spike_links["unexplained_spike_count"] == 0
    assert spike["nearby_ledger_events_count"] == 0
    assert spike["explained_by_mark_to_market"] is True
    assert spike["explanation"] == "MARK_TO_MARKET_PRICE_MOVE_ON_OPEN_PAPER_POSITIONS"


def test_status_dedupes_same_timestamp_equity_points_before_graph_diagnostics():
    history = [
        {"timestamp_ms": 100, "current_equity_usdt": 1000.0, "source": "SESSION_START"},
        {"timestamp_ms": 200, "current_equity_usdt": 1001.5, "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID"},
        {"timestamp_ms": 200, "current_equity_usdt": 998.5, "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID"},
        {"timestamp_ms": 150, "current_equity_usdt": 999.0, "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID"},
    ]

    _dedupe_equity_history_timestamps(history)

    timestamps = [row["timestamp_ms"] for row in history]
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == len(timestamps)
    assert history[1]["current_equity_usdt"] == 998.5
    assert history[2]["timestamp_ms"] == 201


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
    assert payload["fusion_runtime"]["status"] == "NO_LIVE_FUSION_INPUT"
    assert payload["fusion_runtime"]["paper_only"] is True
    assert payload["fusion_runtime"]["real_execution"] is False


def _seed_copy_whitelist(monkeypatch, tmp_path, wallets):
    """06/08 — porte #185 (whitelist C12, deny-by-default) : les tests qui attendent une OUVERTURE
    copy doivent seeder des leaders individuellement PROUVES, comme le fait tools/ecrire_copy_whitelist
    en production. On pointe la constante du module vers un fichier temporaire (API reelle, zero mock
    de la logique)."""
    import json as _json
    import time as _time
    from hl_observer.signals import porte_copy_whitelist as _pw
    chemin = tmp_path / "copy_whitelist.json"
    chemin.write_text(_json.dumps({
        "genere_ts": _time.time(),
        "gardes": [{"adresse": str(w).lower()} for w in wallets],
    }), encoding="utf-8")
    monkeypatch.setattr(_pw, "CHEMIN_WHITELIST", chemin)


def test_fusion_status_route_runs_only_from_explicit_engine_input(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    settings = _settings()
    heartbeat_path = simulation_state_path(settings).parent / "hypersmart_engine_status.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    event_ms = int(time.time() * 1000)
    _seed_recorded_execution_book(monkeypatch, coin="HYPE", mid=70.05, observed_at_ms=event_ms)
    _seed_copy_whitelist(monkeypatch, tmp_path, ["0x" + "1" * 40, "0x" + "2" * 40])
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at_ms": event_ms,
                "phase": "live_fusion_runtime",
                "message": "Entree fusion live depuis moteur read-only.",
                "read_only": True,
                "simulation_only": True,
                "external_action": False,
                "metrics": {
                    "wallet_candidates_total": 3,
                    "fresh_entry_deltas": 3,
                    "virtual_entries_logged": 1,
                },
                "fusion_runtime_input": {
                    "session_id": "ui-live-fusion-test",
                    "leader_votes": [
                        {"wallet": "0x" + "1" * 40, "coin": "HYPE", "side": "LONG", "score": 2.0, "observed_at_ms": event_ms},
                        {"wallet": "0x" + "2" * 40, "coin": "HYPE", "side": "LONG", "score": 1.7, "observed_at_ms": event_ms},
                        {"wallet": "0x" + "3" * 40, "coin": "HYPE", "side": "SHORT", "score": 0.1, "observed_at_ms": event_ms},
                    ],
                    "price_events": [
                        {"source": "hyperliquid_ws", "coin": "HYPE", "bid": 70.0, "ask": 70.1, "event_time_ms": event_ms},
                        {"source": "hyperliquid_allMids", "coin": "HYPE", "bid": 70.2, "ask": 70.3, "event_time_ms": event_ms + 1},
                    ],
                    "distilled_signal_candidates": [
                        {
                            "wallet": "0x" + "1" * 40,
                            "coin": "HYPE",
                            "side": "LONG",
                            "action_type": "OPEN_LONG",
                            "event_time_ms": event_ms,
                            "leader_notional_usdc": 6_000.0,
                            "edge_remaining_bps": 28.0,
                            "liquidity_score": 0.8,
                            "leader_score": 82.0,
                            "copy_degradation_bps": 10.0,
                            "source_profile": "distilled_rezzecup_whale_consensus",
                        },
                        {
                            "wallet": "0x" + "2" * 40,
                            "coin": "HYPE",
                            "side": "LONG",
                            "action_type": "OPEN_LONG",
                            "event_time_ms": event_ms,
                            "leader_notional_usdc": 7_000.0,
                            "edge_remaining_bps": 30.0,
                            "liquidity_score": 0.82,
                            "leader_score": 84.0,
                            "copy_degradation_bps": 11.0,
                            "source_profile": "distilled_rezzecup_whale_consensus",
                        },
                    ],
                    "funding_rows": [{"coin": "HYPE", "rates": [0.0, 0.0, 0.001]}],
                    "triangular_edges": [
                        {"base": "USDC", "quote": "HYPE", "rate": 0.014},
                        {"base": "HYPE", "quote": "BTC", "rate": 0.001},
                        {"base": "BTC", "quote": "USDC", "rate": 72_000.0},
                    ],
                    "latencies_ms": [80, 120, 300],
                    "peak_equity": 1000.0,
                    "current_equity": 1000.0,
                    "copy_ratio": 0.05,
                },
            }
        ),
        encoding="utf-8",
    )

    client = TestClient(create_ui_app(settings), raise_server_exceptions=False)
    payload = client.get("/api/simulation/fusion-status").json()

    assert payload["status"] == "OK_LIVE_FUSION_RUNTIME"
    assert payload["paper_only"] is True
    assert payload["real_execution"] is False
    assert payload["external_action"] is False
    assert payload["conflict"]["decision"] == "FOLLOW"
    assert payload["orders_count"] >= 1
    assert payload["paper_engine_accepted"] == 1
    assert payload["input_counts"]["leader_votes"] == 3
    assert payload["input_counts"]["distilled_signal_candidates"] == 2
    assert payload["runtime"]["distilled_opportunity_report"]["evaluated_candidates"] == 2
    assert payload["runtime"]["distilled_opportunity_report"]["opportunities"][0]["coin"] == "HYPE"
    assert payload["runtime"]["distilled_opportunity_report"]["opportunities"][0]["wallet_count"] == 2

    embedded = client.get("/api/simulation/status").json()["fusion_runtime"]
    assert embedded["status"] == "OK_LIVE_FUSION_RUNTIME"
    assert embedded["paper_engine"]["paper_only"] is True

    log_path = settings.logs_dir / "logs à envoyer" / FUSION_STATUS_LOG_FILENAME
    assert log_path.exists()
    logged = json.loads(log_path.read_text(encoding="utf-8-sig"))
    assert logged["status"] == "OK_LIVE_FUSION_RUNTIME"
    assert logged["orders_count"] >= 1
    assert logged["real_execution"] is False


def test_economic_writer_persists_fusion_once_and_status_get_never_reapplies(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    event_ms = int(time.time() * 1000)
    _seed_recorded_execution_book(monkeypatch, coin="HYPE", mid=70.05, observed_at_ms=event_ms)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=event_ms, raw_json={"HYPE": "70.50"}))
        session.commit()

    heartbeat_path = simulation_state_path(settings).parent / "hypersmart_engine_status.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(json.dumps({
        "updated_at_ms": event_ms,
        "phase": "live_fusion_runtime",
        "read_only": True,
        "simulation_only": True,
        "external_action": False,
        "fusion_runtime_input": {
            "session_id": "ui-live-fusion-persist-test",
            "leader_votes": [
                {"wallet": "0x" + "1" * 40, "coin": "HYPE", "side": "LONG", "score": 2.0, "observed_at_ms": event_ms},
                {"wallet": "0x" + "2" * 40, "coin": "HYPE", "side": "LONG", "score": 1.7, "observed_at_ms": event_ms},
            ],
            "price_events": [
                {"source": "hyperliquid_allMids", "coin": "HYPE", "bid": 70.0, "ask": 70.1, "event_time_ms": event_ms}
            ],
            "funding_rows": [],
            "triangular_edges": [],
            "peak_equity": 1000.0,
            "current_equity": 1000.0,
            "copy_ratio": 0.05,
        },
    }), encoding="utf-8")
    state = UiState()
    app = create_ui_app(settings, state=state)
    writer = app.state.economic_writer

    assert writer.last_fusion_report["applied_count"] == 1
    assert state.simulation_reproduced_entries_total == 1
    assert len(state.simulation_virtual_positions) == 1
    before_ledger = json.dumps(state.simulation_ledger_events, sort_keys=True, default=str)
    before_positions = json.dumps(state.simulation_virtual_positions, sort_keys=True, default=str)

    with TestClient(app, raise_server_exceptions=False) as client:
        first = client.get("/api/simulation/status").json()
        second = client.get("/api/simulation/status").json()

    assert first["status_projection_pure"] is True
    assert second["status_projection_pure"] is True
    assert json.dumps(state.simulation_ledger_events, sort_keys=True, default=str) == before_ledger
    assert json.dumps(state.simulation_virtual_positions, sort_keys=True, default=str) == before_positions

    duplicate = writer.tick(current_ms=event_ms + 1)
    assert duplicate["fusion"]["applied_count"] == 0
    assert len(state.simulation_virtual_positions) == 1

def test_status_rejects_external_arbitrage_without_measured_execution_costs(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", "1")
    monkeypatch.setenv("HYPERSMART_AB_RESEARCH_ACK", "1")
    # 06/08 — durcissement posterieur : la materialisation directe n'est permise que dans la
    # lane du ledger EXPERIMENTAL (3e condition, en serie avec le flag + l'ACK).
    monkeypatch.setenv("HYPERSMART_LEDGER_SCOPE", "EXPERIMENTAL")
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    event_ms = int(time.time() * 1000)
    _seed_recorded_execution_book(monkeypatch, coin="HYPE", mid=72.05, observed_at_ms=event_ms)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=event_ms, raw_json={"HYPE": "70.50"}))
        session.commit()

    heartbeat_path = simulation_state_path(settings).parent / "hypersmart_engine_status.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at_ms": event_ms,
                "phase": "live_fusion_runtime",
                "read_only": True,
                "simulation_only": True,
                "external_action": False,
                "fusion_runtime_input": {
                    "session_id": "ui-live-arbitrage-persist-test",
                    "leader_votes": [
                        {"wallet": "0x" + "1" * 40, "coin": "HYPE", "side": "LONG", "score": 1.0, "observed_at_ms": event_ms},
                        {"wallet": "0x" + "2" * 40, "coin": "HYPE", "side": "SHORT", "score": 0.9, "observed_at_ms": event_ms},
                    ],
                    "price_events": [
                        {"source": "hyperliquid_allMids", "coin": "HYPE", "bid": 70.0, "ask": 70.1, "event_time_ms": event_ms},
                        {"source": "cex_reference", "coin": "HYPE", "bid": 71.0, "ask": 71.1, "event_time_ms": event_ms + 1},
                    ],
                    "funding_rows": [],
                    "triangular_edges": [],
                    "peak_equity": 1000.0,
                    "current_equity": 1000.0,
                    "copy_ratio": 0.05,
                },
            }
        ),
        encoding="utf-8",
    )
    state = UiState()
    client = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False)

    payload = client.get("/api/simulation/status").json()
    duplicate_payload = client.get("/api/simulation/status").json()

    assert payload["fusion_runtime"]["status"] == "OK_LIVE_FUSION_RUNTIME"
    assert payload["fusion_runtime"]["paper_engine_accepted"] == 0
    assert payload["fusion_persistent_adapter"]["applied_count"] == 0
    assert "DIRECT_EXECUTION_COST_UNMEASURABLE" in payload["fusion_persistent_adapter"]["reasons"]
    assert payload["open_positions"] == 0
    refusal_rows = [
        row
        for row in state.simulation_ledger_events
        if isinstance(row, dict) and row.get("reason") == "DIRECT_EXECUTION_COST_UNMEASURABLE"
    ]
    assert refusal_rows, "the unmeasurable two-leg execution cost must be auditable"
    assert all(row.get("paper_action_type") == "NO_TRADE" for row in refusal_rows)
    assert all(row.get("estimated_net_pnl_usdc") is None for row in refusal_rows)
    assert duplicate_payload["fusion_persistent_adapter"]["applied_count"] == 0
    assert len(state.simulation_virtual_positions) == 0


def test_economic_writer_closes_existing_paper_position_when_fusion_consensus_flips(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", "1")
    monkeypatch.setenv("HYPERSMART_AB_RESEARCH_ACK", "1")
    monkeypatch.setenv("HYPERSMART_LEDGER_SCOPE", "EXPERIMENTAL")
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    event_ms = int(time.time() * 1000)
    _seed_recorded_execution_book(monkeypatch, coin="HYPE", mid=72.05, observed_at_ms=event_ms)
    _seed_copy_whitelist(monkeypatch, tmp_path, ["0x" + "1" * 40, "0x" + "2" * 40])
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=event_ms, raw_json={"HYPE": "72.00"}))
        session.commit()

    heartbeat_path = simulation_state_path(settings).parent / "hypersmart_engine_status.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(json.dumps({
        "updated_at_ms": event_ms,
        "phase": "live_fusion_runtime",
        "read_only": True,
        "simulation_only": True,
        "external_action": False,
        "fusion_runtime_input": {
            "session_id": "ui-live-fusion-open-test",
            "leader_votes": [
                {"wallet": "0x" + "1" * 40, "coin": "HYPE", "side": "LONG", "score": 2.0, "observed_at_ms": event_ms},
                {"wallet": "0x" + "2" * 40, "coin": "HYPE", "side": "LONG", "score": 1.7, "observed_at_ms": event_ms},
            ],
            "price_events": [{"source": "hyperliquid_allMids", "coin": "HYPE", "bid": 72.0, "ask": 72.1, "event_time_ms": event_ms}],
            "funding_rows": [], "triangular_edges": [],
        },
    }), encoding="utf-8")
    state = UiState()
    app = create_ui_app(settings, state=state)
    writer = app.state.economic_writer
    assert state.simulation_reproduced_entries_total == 1
    assert len(state.simulation_virtual_positions) == 1

    _seed_recorded_execution_book(monkeypatch, coin="HYPE", mid=73.05, observed_at_ms=event_ms + 1)
    heartbeat_path.write_text(json.dumps({
        "updated_at_ms": event_ms + 1,
        "phase": "live_fusion_runtime",
        "read_only": True,
        "simulation_only": True,
        "external_action": False,
        "fusion_runtime_input": {
            "session_id": "ui-live-fusion-close-test",
            "leader_votes": [
                {"wallet": "0x" + "3" * 40, "coin": "HYPE", "side": "SHORT", "score": 2.1, "observed_at_ms": event_ms + 1},
                {"wallet": "0x" + "4" * 40, "coin": "HYPE", "side": "SHORT", "score": 1.8, "observed_at_ms": event_ms + 1},
            ],
            "price_events": [{"source": "hyperliquid_allMids", "coin": "HYPE", "bid": 73.0, "ask": 73.1, "event_time_ms": event_ms + 1}],
            "funding_rows": [], "triangular_edges": [],
        },
    }), encoding="utf-8")

    report = writer.tick(current_ms=event_ms + 1)
    assert report["fusion"]["applied_count"] == 1
    assert state.simulation_reproduced_exits_total == 1
    assert any(row.get("bot_replay_action") == "FUSION_DIRECT_PAPER_CLOSE" for row in state.simulation_ledger_events)
    assert state.simulation_realized_pnl_usdc > 0

    before = json.dumps(state.simulation_ledger_events, sort_keys=True, default=str)
    with TestClient(app, raise_server_exceptions=False) as client:
        payload = client.get("/api/simulation/status").json()
    assert payload["status_projection_pure"] is True
    assert json.dumps(state.simulation_ledger_events, sort_keys=True, default=str) == before

def test_fusion_status_rejects_incomplete_engine_input_without_fake_orders(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    settings = _settings()
    heartbeat_path = simulation_state_path(settings).parent / "hypersmart_engine_status.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at_ms": int(time.time() * 1000),
                "phase": "live_fusion_runtime",
                "read_only": True,
                "simulation_only": True,
                "external_action": False,
                "fusion_runtime_input": {"leader_votes": [{"wallet": "0x" + "4" * 40, "coin": "HYPE", "side": "LONG"}]},
            }
        ),
        encoding="utf-8",
    )

    payload = TestClient(create_ui_app(settings), raise_server_exceptions=False).get("/api/simulation/fusion-status").json()

    assert payload["status"] == "INVALID_LIVE_FUSION_INPUT"
    assert payload["orders_count"] == 0
    assert payload["paper_engine_accepted"] == 0
    assert payload["paper_only"] is True
    assert payload["real_execution"] is False
    assert "NO_PRICE_EVENTS" in payload["no_trade_reasons"]


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
    state.simulation_realized_pnl_usdc = 0.0
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
    # The open position carries its 0.02 entry cost until close.
    # Expected net = 1 - 0.2412 - 0.02.
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
    assert payload["positions"][0]["unrealized_pnl_usdc"] == 0.7388
    assert payload["equity_usdt"] == 1000.7388
    assert payload["net_pnl_usdt"] == 0.7388
    assert state.simulation_equity_history[-1]["source"] == "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID"


def test_status_infers_legacy_position_coin_from_position_id(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_virtual_positions = {
        "legacy-key-without-coin": {
            "position_id": "fusion-runtime:fusion-paper-engine:BTC:SHORT:1783159205332",
            "direction": "SHORT",
            "size": -0.01,
            "avg_price": 60000.0,
            "opened_at_ms": now_ms() - 1_000,
            "position_mode": "EXTERNAL_GITHUB_FUSION_PAPER",
        }
    }
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=now_ms(), raw_json={"BTC": "59900"}))
        session.commit()

    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["open_positions"] == 1
    assert payload["positions"][0]["coin"] == "BTC"
    assert payload["positions"][0]["market"] == "BTC"
    assert payload["positions"][0]["direction"] == "SHORT"
    assert payload["mark_diagnostics"]["invalid_positions_skipped"] == 0


def test_status_skips_unrecoverable_unknown_position(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    from hl_observer.storage.database import init_db

    init_db(settings.database_url)
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_virtual_positions = {
        "broken": {
            "coin": "?",
            "direction": "LONG",
            "size": 1.0,
            "avg_price": 100.0,
            "opened_at_ms": now_ms() - 1_000,
            "position_mode": "EXTERNAL_GITHUB_FUSION_PAPER",
        }
    }

    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["open_positions"] == 0
    assert payload["positions"] == []
    assert payload["mark_diagnostics"]["invalid_positions_skipped"] == 1
    assert payload["mark_to_market"]["invalid_positions_skipped"] == 1
    assert payload["position_integrity"]["status"] == "WARN"
    assert payload["position_integrity"]["raw_positions_seen"] == 1
    assert payload["position_integrity"]["valid_positions"] == 0
    assert payload["position_integrity"]["invalid_positions_skipped"] == 1
    assert payload["position_integrity"]["dashboard_should_hide_invalid_positions"] is True


def test_status_exposes_recent_orphan_position_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    from hl_observer.storage.database import init_db

    init_db(settings.database_url)
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_virtual_positions = {}
    state.simulation_ledger_events = [
        {
            "bot_replay_action": "STATE_CLEANUP",
            "reason": "ORPHAN_VIRTUAL_POSITION_DROPPED_NO_ENTRY_LEDGER",
            "coin": "HYPE",
            "leader_side": "SHORT",
            "matched_position_key": "legacy|HYPE|SHORT",
            "delta_key": "cleanup-test",
            "observed_at_ms": now_ms(),
            "estimated_net_pnl_usdc": None,
        }
    ]

    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["open_positions"] == 0
    assert payload["closed_trades"] == 0
    assert payload["position_integrity"]["status"] == "WARN"
    assert payload["position_integrity"]["orphan_cleanup_events_recent"] == 1
    assert payload["position_integrity"]["recent_orphan_cleanup_events"][0]["coin"] == "HYPE"
    assert payload["position_integrity"]["pnl_impact"] == "NONE_FOR_INVALID_ORPHAN_CLEANUP"


def test_status_quality_guard_holds_legacy_unevidenced_copy_position_when_entry_cost_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HYPERSMART_LEGACY_POSITION_MIN_AGE_MS", "0")
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_virtual_positions = {
        "ext_rezzecup_whale_mirror_primary|HYPE|SHORT": {
            "wallet_address": "ext_rezzecup_whale_mirror_primary",
            "coin": "HYPE",
            "direction": "SHORT",
            "size": -1.0,
            "avg_price": 70.0,
            "opened_at_ms": now_ms() - 120_000,
            "source_delta_key": "legacy-copy-without-edge",
            "position_mode": "EXTERNAL_GITHUB_COPY_PAPER",
            "strategy_family": "copy_follow",
            "leader_wallets_count": 1,
        }
    }
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=now_ms(), raw_json={"HYPE": "71"}))
        session.commit()

    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["quality_guard_runtime"]["closed_count"] == 0
    assert payload["quality_guard_runtime"]["skipped"][0]["reason"] == "QUALITY_CLOSE_ENTRY_COST_UNMEASURABLE"
    assert payload["open_positions"] == 1
    assert state.simulation_virtual_positions
    assert state.simulation_reproduced_exits_total == 0
    assert payload["closed_trades"] == 0
    assert payload["winning_trades"] == 0
    assert payload["losing_trades"] == 0
    assert payload["realized_pnl_usdt"] == 0.0


def test_status_quality_guard_can_close_legacy_unevidenced_copy_position_when_net_positive(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HYPERSMART_LEGACY_POSITION_MIN_AGE_MS", "0")
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_virtual_positions = {
        "ext_rezzecup_whale_mirror_primary|HYPE|SHORT": {
            "wallet_address": "ext_rezzecup_whale_mirror_primary",
            "coin": "HYPE",
            "direction": "SHORT",
            "size": -1.0,
            "avg_price": 70.0,
            "entry_costs": 0.0,
            "fee_already_embedded_in_entry_price": False,
            "opened_at_ms": now_ms() - 120_000,
            "source_delta_key": "legacy-copy-without-edge",
            "position_mode": "EXTERNAL_GITHUB_COPY_PAPER",
            "strategy_family": "copy_follow",
            "leader_wallets_count": 1,
        }
    }
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=now_ms(), raw_json={"HYPE": "69"}))
        session.commit()

    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["quality_guard_runtime"]["closed_count"] == 1
    assert payload["open_positions"] == 0
    assert state.simulation_virtual_positions == {}
    assert state.simulation_reproduced_exits_total == 1
    assert payload["paper_ledger"]["event_counts"]["CLOSE"] == 1
    assert payload["closed_trades"] == 1
    assert payload["winning_trades"] == 1
    close_event = state.simulation_ledger_events[-1]
    assert close_event["paper_action_type"] == "CLOSE"
    assert close_event["status"] == "LOCAL_REPLAY"
    assert close_event["reason"].startswith("QUALITY_GUARD_LEGACY_UNEVIDENCED_POSITION")
    assert close_event["estimated_net_pnl_usdc"] == 0.9172
    assert payload["realized_pnl_usdt"] == 0.9172
    assert payload["equity_usdt"] == 1000.9172


def test_status_counts_closed_winning_and_losing_trades_from_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = 0.8
    state.simulation_ledger_events = [
        {
            "delta_key": "paper-close-win",
            "coin": "HYPE",
            "leader_side": "LONG",
            "paper_action_type": "CLOSE",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "status": "LOCAL_REPLAY",
            "observed_at_ms": now_ms() - 2_000,
            "estimated_net_pnl_usdc": 1.2,
            "gross_pnl_usdc": 1.4,
            "fee_cost_usdc": 0.2,
            "entry_price": 70.0,
            "exit_price": 71.4,
            "reason": "SLTP_TAKE_PROFIT_LOCAL_REPLAY_NOT_AN_ORDER",
        },
        {
            "delta_key": "paper-close-loss",
            "coin": "SOL",
            "leader_side": "SHORT",
            "paper_action_type": "CLOSE",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "status": "LOCAL_REPLAY",
            "observed_at_ms": now_ms() - 1_000,
            "estimated_net_pnl_usdc": -0.4,
            "gross_pnl_usdc": -0.2,
            "fee_cost_usdc": 0.2,
            "entry_price": 75.0,
            "exit_price": 75.2,
            "reason": "SLTP_STOP_LOSS_LOCAL_REPLAY_NOT_AN_ORDER",
        },
        {
            "delta_key": "no-trade-context",
            "paper_action_type": "NO_TRADE",
            "bot_replay_action": "NO_TRADE",
            "estimated_net_pnl_usdc": 99.0,
            "reason": "REJECT_CONTEXT_ONLY",
        },
    ]

    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["closed_trades"] == 2
    assert payload["winning_trades"] == 1
    assert payload["losing_trades"] == 1
    assert payload["flat_trades"] == 0
    assert payload["winrate_pct"] == 50.0
    assert payload["winrate"] == "50%"
    assert payload["paper_ledger"]["closed_trade_stats"]["total_closed_pnl_usdc"] == 0.8
    assert len(payload["paper_ledger"]["closed_trade_stats"]["recent_closed_trades"]) == 2
    assert payload["bot_simulation"]["closed_trade_stats"]["closed_trades"] == 2


def test_status_get_never_exports_diagnostics_or_writes_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("HYPERSMART_DISABLE_ECONOMIC_WRITER", "1")
    settings = _settings()
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_ledger_events = [{
        "delta_key": "close-live-export",
        "coin": "HYPE",
        "leader_side": "LONG",
        "paper_action_type": "CLOSE",
        "bot_replay_action": "PAPER_CLOSE_REPLAYED",
        "status": "LOCAL_REPLAY",
        "observed_at_ms": now_ms() - 1_000,
        "estimated_net_pnl_usdc": 0.42,
    }]
    app = create_ui_app(settings, state=state)
    before = list((tmp_path / "logs").rglob("*")) if (tmp_path / "logs").exists() else []

    with TestClient(app, raise_server_exceptions=False) as client:
        payload = client.get("/api/simulation/status").json()

    after = list((tmp_path / "logs").rglob("*")) if (tmp_path / "logs").exists() else []
    assert payload["status_projection_pure"] is True
    assert "diagnostic_logs" not in payload
    assert after == before
    assert payload["closed_trades"] == 1

def test_closed_trade_stats_ignore_duplicate_full_closes():
    duplicated_close = {
        "delta_key": "quality-close-first-ms",
        "coin": "HYPE",
        "leader_side": "SHORT",
        "paper_action_type": "CLOSE",
        "bot_replay_action": "PAPER_CLOSE_REPLAYED",
        "status": "LOCAL_REPLAY",
        "observed_at_ms": now_ms() - 2_000,
        "estimated_net_pnl_usdc": 0.25,
        "gross_pnl_usdc": 0.3,
        "fee_cost_usdc": 0.05,
        "entry_price": 64.363,
        "exit_price": 64.15,
        "size_closed": 0.4,
        "exit_method": "QUALITY_GUARD_LEGACY_UNEVIDENCED",
        "reason": "QUALITY_GUARD_LEGACY_UNEVIDENCED_POSITION_CLOSED_LOCAL_REPLAY_NOT_AN_ORDER",
        "matched_position_key": "ext_rezzecup_whale_mirror_primary|HYPE|SHORT",
    }
    replayed_stale_close = dict(duplicated_close)
    replayed_stale_close["delta_key"] = "quality-close-second-ms"
    replayed_stale_close["observed_at_ms"] = now_ms() - 1_000
    replayed_stale_close["exit_price"] = 64.14
    replayed_stale_close["estimated_net_pnl_usdc"] = 0.26

    stats = _ledger_closed_trade_stats([duplicated_close, replayed_stale_close])

    assert stats["closed_trades"] == 1
    assert stats["winning_trades"] == 1
    assert stats["total_closed_pnl_usdc"] == 0.25
    assert stats["duplicate_full_closes_ignored"] == 1


def test_status_quality_guard_keeps_evidenced_copy_position_open(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HYPERSMART_LEGACY_POSITION_MIN_AGE_MS", "0")
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_virtual_positions = {
        "ext_rezzecup_whale_mirror_primary|HYPE|LONG": {
            "wallet_address": "ext_rezzecup_whale_mirror_primary",
            "coin": "HYPE",
            "direction": "LONG",
            "size": 1.0,
            "avg_price": 70.0,
            "opened_at_ms": now_ms() - 120_000,
            "source_delta_key": "copy-with-valid-evidence",
            "position_mode": "EXTERNAL_GITHUB_COPY_PAPER",
            "strategy_family": "copy_follow",
            "edge_remaining_bps": 42.0,
            "signal_age_ms": 900.0,
            "leader_wallets_count": 3,
            "liquidity_score": 0.8,
            "copy_degradation_bps": 12.0,
        }
    }
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=now_ms(), raw_json={"HYPE": "71"}))
        session.commit()

    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["quality_guard_runtime"]["closed_count"] == 0
    assert payload["open_positions"] == 1
    position = payload["positions"][0]
    assert position["edge_remaining_bps"] == 42.0
    assert position["signal_age_ms"] == 900.0
    assert position["leader_wallets_count"] == 3
    assert position["liquidity_score"] == 0.8
    assert position["copy_degradation_bps"] == 12.0
    assert position["quality_evidence_missing"] is False


def test_status_flags_fusion_paper_position_without_measurable_evidence():
    reason = _copy_position_quality_exit_reason(
        {
            "position_mode": "EXTERNAL_GITHUB_FUSION_PAPER",
            "opened_at_ms": now_ms() - 120_000,
            "leader_wallets_count": 1,
        },
        current_ms=now_ms(),
        min_age_ms=0,
    )

    assert "edge_remaining_bps" in reason
    assert "signal_age_ms" in reason
    assert "leader_wallets_count>=2" in reason
    assert "liquidity_score" in reason


def test_status_get_never_calls_live_all_mids_even_when_launcher_flag_is_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HYPERSMART_STATUS_LIVE_MARKS_ENABLED", "1")
    settings = _settings()
    from hl_observer.storage.database import init_db
    import hl_observer.ui.status_routes as status_routes

    init_db(settings.database_url)
    leader = "0x" + "c" * 40
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_virtual_positions = {
        f"{leader}|HYPE|SHORT": {
            "wallet_address": leader,
            "coin": "HYPE",
            "direction": "SHORT",
            "size": 3.0,
            "avg_price": 70.0,
            "entry_costs": 0.0,
            "fee_already_embedded_in_entry_price": False,
            "source_delta_key": "hash:paper-short-live",
        }
    }

    class _NetworkForbidden:
        def __init__(self, *args, **kwargs):
            raise AssertionError("status GET must never instantiate an HTTP client")

    monkeypatch.setattr(status_routes.httpx, "Client", _NetworkForbidden)
    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["status_projection_pure"] is True
    assert payload["network_reads_from_status"] is False
    assert payload["open_positions"] == 1
    assert payload["mark_to_market"]["marks_used"] == 0
    assert payload["positions"][0]["market_mark_available"] is False

def test_fast_status_tick_purges_legacy_overview_mark_to_market_points(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    leader = "0x" + "d" * 40
    state = UiState()
    state.simulation_started_at_ms = now_ms() - 10_000
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = 0.0
    state.simulation_equity_history = [
        {
            "timestamp_ms": state.simulation_started_at_ms,
            "current_pnl_usdc": 0.0,
            "current_equity_usdt": 1000.0,
            "source": "SESSION_START",
        },
        {
            "timestamp_ms": state.simulation_started_at_ms + 1_000,
            "current_pnl_usdc": 2.4,
            "current_equity_usdt": 1002.4,
            "open_exposure_usdt": 235.0,
            "source": "MARK_TO_MARKET",
        },
    ]
    state.simulation_virtual_positions = {
        f"{leader}|ETH|LONG": {
            "wallet_address": leader,
            "coin": "ETH",
            "direction": "LONG",
            "size": 0.1,
            "avg_price": 2000.0,
            "entry_costs": 0.01,
            "source_delta_key": "hash:paper-entry",
        }
    }
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=now_ms(), raw_json={"ETH": "2010"}))
        session.commit()

    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["open_positions"] == 1
    assert payload["equity_usdt"] != 1002.4
    sources = [row.get("source") for row in state.simulation_equity_history if isinstance(row, dict)]
    assert "MARK_TO_MARKET" not in sources
    assert sources[-1] == "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID"


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
    assert "function liveStatusIsUsableForGraph" in page
    assert "position_integrity" in page
    assert "Integrite positions" in page
    assert "dashboard_should_hide_invalid_positions" not in page
    assert "fast_status_tick_authoritative" in page
    assert "letting it overwrite targetEquity was the source" in page
    assert "if(liveStatusIsFresh(1200))return;" in page
    assert "function compactGraphPoints" in page
    assert "function normalizeGraphHistory" in page
    assert "GRAPH_MIN_USD_RANGE=8.0" in page
    assert "ne sont pas stockes dans equityHist" in page
    assert "source:\"visual_mark_to_market\"" not in page
    assert "server_tick_replace_same_time" in page
    assert "DETAIL_RENDER_MIN_MS=1500" in page
    assert "SCAN_RENDER_MIN_MS=1500" in page
    assert "now-lastDetailsRenderAt>=DETAIL_RENDER_MIN_MS" in page
    assert "now-lastScanRenderAt<SCAN_RENDER_MIN_MS" in page


def test_simulation_page_keeps_below_graph_layout_stable():
    page = (
        __import__("pathlib").Path("src/hl_observer/ui/static/simulation_v2.html")
        .read_text(encoding="utf-8", errors="replace")
    )

    assert ".cols{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;align-items:start;overflow-anchor:none;contain:layout paint;min-height:336px}" in page
    assert ".col h3{font-size:15px;font-weight:600;margin:0 0 10px;height:24px;line-height:24px}" in page
    assert ".dec{display:flex;gap:9px;align-items:flex-start;padding:7px 0;border-bottom:1px solid var(--line);font-size:14px;min-height:38px}" in page
    assert ".graphhead .conn{min-width:190px;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" in page


def test_simulation_page_surfaces_fusion_runtime_without_fake_orders():
    page = (
        __import__("pathlib").Path("src/hl_observer/ui/static/simulation_v2.html")
        .read_text(encoding="utf-8", errors="replace")
    )

    assert "status.fusion_runtime||{}" in page
    assert "Moteur fusion" in page
    assert "Fraicheur deltas" in page
    assert "Bus GitHub simulation" in page
    assert "external_profile_execution_summary" in page
    assert "external_profile_executions" in page
    assert "NO_LIVE_FUSION_INPUT" in page
    assert "orders_count" in page
    assert "paper_engine_accepted" in page
    assert "OK_LIVE_FUSION_RUNTIME" in page


# ---------------------------------------------------------------------------------------------
# VERROU EDGE EMPIRIQUE (2026-07-11) -- POURQUOI CES TESTS FORCENT UN FLAG.
#
# Ces tests verifient la MECANIQUE (scorer, CLI, persistance UI). Pour cela, il faut qu'une
# position s'ouvre. Or depuis le 2026-07-11, le moteur REFUSE par defaut un edge qui n'a jamais
# touche un prix : l'ancienne formule (`dominance * 45 + bonus`) fabriquait un nombre en bps sans
# regarder le marche une seule fois.
#
# On active donc `HYPERSMART_REQUIRE_EMPIRICAL_EDGE=0` : mode A/B ASSUME, PAS la production.
# Le defaut reste le REFUS -- garde par `tests/test_empirical_edge.py`.
# ---------------------------------------------------------------------------------------------
import pytest as _pytest_ab


@_pytest_ab.fixture(autouse=True)
def _mode_ab_edge_non_empirique(monkeypatch):
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
