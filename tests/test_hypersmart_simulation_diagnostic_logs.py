from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import MarketSnapshot, PositionDeltaModel, TopWallet
from hl_observer.ui.app import create_ui_app
from hl_observer.ui import simulation_log_export
from hl_observer.ui.simulation_log_export import export_simulation_diagnostics
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms


def test_simulation_overview_writes_logs_to_send_folder(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS", "1")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MIN_EDGE_BPS", "5")
    monkeypatch.setenv("HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS", "5")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE", "0.1")
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    settings.logs_dir = tmp_path / "logs"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    wallet = "0x" + "1" * 40
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms, raw_json={"BTC": "50000"}))
        session.add(TopWallet(wallet_address=wallet, rank=1, source="leaderboard", score=95, selected_at_ms=base_ms, status="selected"))
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="BTC",
                previous_side="FLAT",
                new_side="LONG",
                previous_size=0.0,
                current_size=0.1,
                new_size=0.1,
                delta_size=0.1,
                delta_notional_usdc=5_000.0,
                action="OPEN",
                exchange_ts=base_ms,
                detected_at_ms=base_ms,
                source="hyperliquid_ws:userFills",
                side="B",
                price=50_000.0,
                fill_size=0.1,
                delta_type="open_long",
                confidence_score=0.95,
                is_paper_eligible=True,
                delta_hash="diagnostic-log-open",
                raw_json={"coin": "BTC", "dir": "Open Long"},
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=10").json()

    logs_dir = settings.logs_dir / "logs à envoyer"
    assert logs_dir.exists()
    assert payload["diagnostic_logs"]["directory"] == str(logs_dir)
    summary = logs_dir / "simulation_resume_pour_chatgpt.md"
    decisions = logs_dir / "simulation_decisions_latest.jsonl"
    pnl_ledger = logs_dir / "simulation_pnl_ledger_latest.jsonl"
    append_only = logs_dir / "simulation_decisions_append_only.jsonl"
    snapshot = logs_dir / "simulation_snapshot_latest.json"
    assert summary.exists()
    assert decisions.exists()
    assert pnl_ledger.exists()
    assert append_only.exists()
    assert snapshot.exists()
    assert not list(logs_dir.glob("*.sqlite3"))

    summary_text = summary.read_text(encoding="utf-8")
    assert "aucun /exchange" in summary_text
    assert "Controle comptable debutant" in summary_text
    assert "Diagnostic OFFRE vs GATES" in summary_text
    assert "Diagnostic pertes / reglages" in summary_text
    assert "Signaux ignores avant ledger" in summary_text
    assert "Diagnostic V9 evidence/risk" in summary_text
    assert "Dernieres decisions detaillees" in summary_text
    assert "PAPER_" in summary_text
    snapshot_payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert snapshot_payload["pnl_consistency"]["ok"] is True
    assert snapshot_payload["scanner"]["entry_supply"]["bottleneck"] in {"OK", "GATES", "SUPPLY", "NO_DATA"}
    assert snapshot_payload["scanner"]["entry_supply"]["execution"] == "forbidden"
    assert snapshot_payload["decision_log_pnl"]["read_only"] is True
    assert snapshot_payload["equity"]["decision_log_events"] >= 0
    assert snapshot_payload["loss_diagnostics"]["execution"] == "forbidden"
    assert snapshot_payload["bot_simulation"]["snapshot_compacted"] is True
    assert snapshot_payload["bot_simulation"]["snapshot_event_limit"] == 500

    decision_lines = [line for line in decisions.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert decision_lines
    first = json.loads(decision_lines[0])
    assert first["execution"] == "forbidden"
    assert first["research_only"] is True
    assert first["evidence_hash"].startswith("ev:")
    assert first["v9_evidence_hash"].startswith("ev:")
    assert first["v9_decision"]
    assert first["v9_accepted"] is False
    assert first["v9_data_gap"] is True
    assert first["v9_reasons"]
    assert "plain_english" in first
    assert first["pnl_impact"] in {"GAIN", "LOSS", "NEUTRAL", "NO_PNL"}
    assert first["loss_bucket"]


def test_simulation_append_only_log_rotates_when_oversized(tmp_path: Path, monkeypatch) -> None:
    settings = load_settings()
    settings.logs_dir = tmp_path / "logs"
    log_dir = simulation_log_export.logs_to_send_dir(settings)
    append_only = log_dir / "simulation_decisions_append_only.jsonl"
    append_only.write_text("old\n" * 200, encoding="utf-8")
    monkeypatch.setenv("HYPERSMART_APPEND_ONLY_ROTATE_MB", "0.0001")

    export_simulation_diagnostics(
        settings,
        {
            "mode": "LOCAL_PAPER_SIMULATION_REAL_HYPERLIQUID_DATA",
            "bot_simulation": {
                "ledger_events": [
                    {
                        "observed_at_ms": now_ms(),
                        "wallet_address": "0x" + "1" * 40,
                        "coin": "BTC",
                        "leader_action": "OPEN_LONG",
                        "bot_replay_action": "PAPER_OPEN",
                        "status": "LOCAL_REPLAY",
                        "estimated_net_pnl_usdc": 0.0,
                    }
                ]
            },
        },
    )

    archives = list((log_dir / "_archives").glob("oversized_append_only_*/*simulation_decisions_append_only.jsonl"))
    assert archives
    assert append_only.exists()
    assert "PAPER_OPEN" in append_only.read_text(encoding="utf-8")


def test_simulation_export_uses_fallback_when_logs_to_send_is_unwritable(tmp_path: Path, monkeypatch) -> None:
    settings = load_settings()
    settings.logs_dir = tmp_path / "logs"
    fallback_dir = tmp_path / "hypersmart_logs_a_envoyer"

    def fake_probe(path: Path):
        if path == settings.logs_dir / "logs à envoyer":
            return "PermissionError: locked"
        if path == fallback_dir:
            path.mkdir(parents=True, exist_ok=True)
            return None
        return None

    monkeypatch.setattr(simulation_log_export, "_probe_log_dir", fake_probe)
    monkeypatch.setattr(simulation_log_export, "gettempdir", lambda: str(tmp_path))

    result = export_simulation_diagnostics(
        settings,
        {
            "equity": {"starting_equity_usdt": 1000.0, "current_equity_usdt": 1000.0, "current_pnl_usdc": 0.0},
            "bot_simulation": {"ledger_events": []},
            "counts": {},
        },
    )

    assert result["directory_status"] == "FALLBACK_USED"
    assert "primary_log_dir_unavailable" in result["write_warnings"]
    assert Path(result["snapshot_json"]).exists()


def test_simulation_export_includes_paper_ledger_audit(tmp_path: Path) -> None:
    settings = load_settings()
    settings.logs_dir = tmp_path / "logs"

    result = export_simulation_diagnostics(
        settings,
        {
            "equity": {"starting_equity_usdt": 1000.0, "current_equity_usdt": 1001.0, "current_pnl_usdc": 1.0},
            "paper_ledger": {
                "source": "UI_STATE_LEDGER_PROJECTION",
                "formula": "equity = starting_balance + realized_pnl + unrealized_pnl",
                "event_count": 3,
                "open_positions_count": 1,
                "reconciliation": {"ok": True, "diff_usdc": 0.0},
                "spike_diagnostics": {"spike_count": 1, "interpretation": "CHECK_LEDGER_EVENTS_AROUND_SPIKES"},
                "spike_links": {"spike_count": 1, "unexplained_spike_count": 0, "status": "OK"},
                "cost_accounting": "costs embedded",
            },
            "bot_simulation": {"ledger_events": []},
            "counts": {},
        },
    )

    summary = Path(result["chatgpt_markdown"]).read_text(encoding="utf-8")
    snapshot_payload = json.loads(Path(result["snapshot_json"]).read_text(encoding="utf-8"))
    assert "Audit ledger paper" in summary
    assert "UI_STATE_LEDGER_PROJECTION" in summary
    assert "CHECK_LEDGER_EVENTS_AROUND_SPIKES" in summary
    assert "Pics sans evenement ledger proche: 0" in summary
    assert "Statut liaison graphe/ledger: OK" in summary
    assert snapshot_payload["paper_ledger"]["event_count"] == 3


def test_simulation_export_writes_pnl_ledger_extract(tmp_path: Path) -> None:
    settings = load_settings()
    settings.logs_dir = tmp_path / "logs"

    result = export_simulation_diagnostics(
        settings,
        {
            "equity": {"starting_equity_usdt": 1000.0, "current_equity_usdt": 1001.0, "current_pnl_usdc": 1.0},
            "paper_ledger": {
                "closed_trade_stats": {
                    "recent_closed_trades": [
                        {
                            "observed_at_ms": 10,
                            "coin": "BTC",
                            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
                            "paper_action_type": "CLOSE",
                            "status": "LOCAL_REPLAY",
                            "estimated_net_pnl_usdc": 1.2,
                            "gross_pnl_usdc": 1.25,
                            "fee_cost_usdc": 0.05,
                            "dedupe_identity": "btc-close",
                        }
                    ]
                }
            },
            "bot_simulation": {
                "ledger_events": [
                    {
                        "observed_at_ms": 11,
                        "coin": "RESEARCH_PROFILE",
                        "bot_replay_action": "EXTERNAL_GITHUB_PROFILE_EVALUATED",
                        "paper_action_type": "ENGINE_EVALUATION",
                        "status": "SIMULATION_ENGINE_EVENT",
                        "estimated_net_pnl_usdc": None,
                        "fee_cost_usdc": 0.0,
                    }
                ]
            },
            "counts": {},
        },
    )

    pnl_path = Path(result["pnl_ledger_jsonl"])
    rows = [json.loads(line) for line in pnl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["coin"] == "BTC"
    assert rows[0]["bot_replay_action"] == "PAPER_CLOSE_REPLAYED"
    assert rows[0]["estimated_net_pnl_usdc"] == 1.2
    assert rows[0]["execution"] == "forbidden"


def test_simulation_export_redirects_default_logs_under_pytest(tmp_path: Path, monkeypatch) -> None:
    settings = load_settings()
    real_runtime_logs = tmp_path / "Projet invest" / "logs"
    settings.logs_dir = real_runtime_logs
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_ui_copy_dashboard.py::test_fixture_pollution_guard (call)")
    monkeypatch.setattr(simulation_log_export, "gettempdir", lambda: str(tmp_path / "tmp"))

    result = export_simulation_diagnostics(
        settings,
        {
            "equity": {"starting_equity_usdt": 1000.0, "current_equity_usdt": 1000.0, "current_pnl_usdc": 0.0},
            "bot_simulation": {
                "ledger_events": [
                    {
                        "observed_at_ms": 1,
                        "wallet_address": "0x" + "1" * 40,
                        "coin": "BTC",
                        "bot_replay_action": "PAPER_FIXTURE_SHOULD_NOT_TOUCH_REAL_LOGS",
                        "status": "LOCAL_REPLAY",
                        "estimated_net_pnl_usdc": 0.0,
                    }
                ]
            },
            "counts": {},
        },
    )

    assert str(tmp_path / "tmp" / "hypersmart_pytest_logs_a_envoyer") in result["directory"]
    assert not (real_runtime_logs / "logs à envoyer" / "simulation_decisions_latest.jsonl").exists()
    assert Path(result["decisions_jsonl"]).exists()
