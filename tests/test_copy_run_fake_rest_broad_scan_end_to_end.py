"""End-to-end fake REST broad scan (no network):
allMids + clearinghouseState + userFillsByTime + openOrders => snapshots =>
deltas => decision => dashboard. Proves the chain records real scan data and the
dashboard reflects it without fabricating anything. Python 3.10/3.11 safe.
"""

from __future__ import annotations

from time import time

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run, shortlist_path
from hyper_smart_observer.copy_mode.copy_models import LeaderCandidateInput
from hyper_smart_observer.copy_mode.leaderboard_selector import (
    LeaderboardSelectionConfig,
    select_leaderboard_shortlist,
    write_shortlist_report,
)
from hyper_smart_observer.dashboard.exporter import export_dashboard
from hyper_smart_observer.hyperliquid_client.info_client import PaginationResult
from hyper_smart_observer.storage.database import get_connection

LEADER = "0x" + "1" * 40


class BroadScanFakeInfoClient:
    """A leader who just opened a BTC long; book present then realistic."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.now_ms = int(time() * 1000)

    def get_all_mids(self):
        self.calls.append("allMids")
        return {"BTC": "50000.0"}

    def get_clearinghouse_state(self, address: str):
        self.calls.append("clearinghouseState")
        return {
            "marginSummary": {"accountValue": "100000"},
            "assetPositions": [
                {"position": {"coin": "BTC", "szi": "1", "entryPx": "50000", "markPx": "50010", "unrealizedPnl": "10"}}
            ],
        }

    def collect_user_fills_by_time_paginated(self, address, start_time_ms, end_time_ms, *, max_pages=None):
        self.calls.append("userFillsByTime")
        fills = [
            {"coin": "BTC", "dir": "Open Long", "px": "50000", "sz": "1", "fee": "0.5",
             "time": self.now_ms + i, "hash": f"h{i}", "tid": i, "closedPnl": "0",
             "startPosition": "0", "feeToken": "USDC"}
            for i in range(3)
        ]
        return PaginationResult(fills=fills, pages_fetched=1, stopped_reason="empty_response", warnings=[])

    def get_user_fills(self, address, *, aggregate_by_time=False):
        self.calls.append("userFills")
        return []

    def get_open_orders(self, address):
        self.calls.append("openOrders")
        return []

    def get_frontend_open_orders(self, address):
        self.calls.append("frontendOpenOrders")
        return []

    def get_user_fees(self, address):
        self.calls.append("userFees")
        return {}

    def get_user_rate_limit(self, address):
        self.calls.append("userRateLimit")
        return {}


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        runtime_root=tmp_path,
        database_path=tmp_path / "data" / "hs.sqlite3",
        reports_dir=tmp_path / "data" / "reports",
        dashboard_dir=tmp_path / "data" / "dashboard",
        info_min_request_interval_ms=0,
        paper_max_open_trades=5,
    )


def _write_shortlist(config):
    report = select_leaderboard_shortlist(
        [LeaderCandidateInput(
            wallet_address=LEADER, history_days=30, closed_pnl_points=50,
            total_closed_pnl=1000.0, max_single_trade_pnl=100.0, max_drawdown_pct=10.0,
            consistency_score=90.0, per_coin_stability_score=85.0,
            execution_quality_score=85.0, sample_confidence=90.0, copyability_score=90.0,
        )],
        config=LeaderboardSelectionConfig(min_score=1),
    )
    write_shortlist_report(report, shortlist_path(config))


def test_fake_rest_broad_scan_records_chain_and_feeds_dashboard(tmp_path):
    config = _config(tmp_path)
    _write_shortlist(config)
    fake = BroadScanFakeInfoClient()

    run = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=fake)

    # The read-only REST endpoints were exercised.
    assert {"allMids", "clearinghouseState", "userFillsByTime", "openOrders"}.issubset(set(fake.calls))
    # The chain recorded snapshots + fills + deltas.
    with get_connection(config) as conn:
        assert conn.execute("SELECT COUNT(*) FROM leader_snapshots").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM fill_snapshots").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM leader_deltas").fetchone()[0] >= 1
    assert run.deltas_seen >= 1
    # A decision exists (signal candidate or explicit no-trade) — never silent.
    assert run.signal_candidates or run.no_trade_decisions

    # Dashboard reflects the real scan and fabricates nothing.
    html_path = export_dashboard(config)
    html = html_path.read_text(encoding="utf-8")
    low = html.lower()
    assert not any(t in low for t in ("math.random", "fakeposition", "dummyequity", "fabricated"))
    assert "btc" in low or LEADER[:10] in html or "shortlist" in low
