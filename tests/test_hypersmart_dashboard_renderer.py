from datetime import UTC, datetime, timedelta

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_models import DeltaAction, LeaderDelta
from hyper_smart_observer.copy_mode.repository import insert_leader_delta
from hyper_smart_observer.dashboard.exporter import export_dashboard
from hyper_smart_observer.storage.database import get_connection, initialize_database


def test_dashboard_export_creates_readonly_html(tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite3", dashboard_dir=tmp_path / "dashboard", runtime_root=tmp_path)

    path = export_dashboard(config)

    text = path.read_text(encoding="utf-8")
    assert "HyperSmart Observer" in text
    assert "READ ONLY" in text
    assert "Wallet Discovery" in text
    assert "Simulation" in text
    assert "No mock USDC wallet" in text
    assert "Consensus Positions" in text


def test_dashboard_simulation_tab_reads_latest_report(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "multi_wallet_follow_simulation_20260526_120000.json").write_text(
        """
        {
          "generated_at": "2026-05-26T12:00:00+00:00",
          "scenario": "multi_wallet_follow_closed_pnl",
          "requested_wallets": 5,
          "simulated_wallets": 4,
          "total_usable_trades": 42,
          "gross_pnl": 12.5,
          "total_costs": 3.0,
          "net_pnl": 9.5,
          "max_drawdown": 2.0
        }
        """,
        encoding="utf-8",
    )
    config = AppConfig(
        database_path=tmp_path / "db.sqlite3",
        dashboard_dir=tmp_path / "dashboard",
        reports_dir=reports_dir,
        runtime_root=tmp_path,
    )

    text = export_dashboard(config).read_text(encoding="utf-8")

    assert 'href="#simulation"' in text
    assert "multi_wallet_follow_closed_pnl" in text
    assert "9.5" in text
    assert "4/5" in text


def test_dashboard_consensus_section_reads_leader_deltas(tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite3", dashboard_dir=tmp_path / "dashboard", runtime_root=tmp_path)
    initialize_database(config)
    base = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
    with get_connection(config) as conn:
        insert_leader_delta(
            conn,
            LeaderDelta(
                delta_id="delta-1",
                leader_wallet="0x0000000000000000000000000000000000000001",
                coin="BTC",
                action_type=DeltaAction.OPEN_LONG,
                observed_at=base,
                previous_size=0.0,
                current_size=1.0,
            ),
        )
        insert_leader_delta(
            conn,
            LeaderDelta(
                delta_id="delta-2",
                leader_wallet="0x0000000000000000000000000000000000000002",
                coin="BTC",
                action_type=DeltaAction.INCREASE,
                observed_at=base + timedelta(seconds=45),
                previous_size=1.0,
                current_size=2.0,
            ),
        )

    text = export_dashboard(config).read_text(encoding="utf-8")

    assert 'href="#consensus"' in text
    assert "Consensus Positions" in text
    assert "BTC" in text
    assert "LONG" in text
    assert "2: 0x0000000000000000000000000000000000000001" in text
    assert "never guaranteed profit" in text
