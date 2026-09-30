from __future__ import annotations

from time import time

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.app.main import main
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run, shortlist_path
from hyper_smart_observer.copy_mode.copy_models import LeaderCandidateInput, NoTradeReason
from hyper_smart_observer.copy_mode.leaderboard_selector import LeaderboardSelectionConfig, select_leaderboard_shortlist, write_shortlist_report
from hyper_smart_observer.copy_mode.preflight import run_copy_preflight, write_copy_preflight_report
from hyper_smart_observer.hyperliquid_client.info_client import PaginationResult


def _candidate(index: int) -> LeaderCandidateInput:
    return LeaderCandidateInput(
        wallet_address="0x" + f"{index:040x}"[-40:],
        history_days=30,
        closed_pnl_points=40,
        total_closed_pnl=1000.0,
        max_single_trade_pnl=100.0,
        max_drawdown_pct=10.0,
        consistency_score=90.0,
        per_coin_stability_score=90.0,
        execution_quality_score=90.0,
        sample_confidence=90.0,
        copyability_score=90.0,
    )


class EmptyFakeInfoClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.now_ms = int(time() * 1000)

    def get_all_mids(self):
        self.calls.append("allMids")
        return {"BTC": "100"}

    def get_clearinghouse_state(self, address: str):
        self.calls.append(f"clearinghouseState:{address}")
        return {"assetPositions": []}

    def collect_user_fills_by_time_paginated(self, address: str, start_time_ms: int, end_time_ms: int, *, max_pages=None):
        self.calls.append(f"userFillsByTime:{address}")
        return PaginationResult(fills=[], pages_fetched=1, stopped_reason="empty_response", warnings=[])

    def get_user_fills(self, address: str, *, aggregate_by_time: bool = False):
        self.calls.append(f"userFills:{address}")
        return []

    def get_open_orders(self, address: str):
        self.calls.append(f"openOrders:{address}")
        return []

    def get_frontend_open_orders(self, address: str):
        self.calls.append(f"frontendOpenOrders:{address}")
        return []

    def get_user_fees(self, address: str):
        self.calls.append(f"userFees:{address}")
        return {}

    def get_user_rate_limit(self, address: str):
        self.calls.append(f"userRateLimit:{address}")
        return {}


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        runtime_root=tmp_path,
        database_path=tmp_path / "data" / "hypersmart.sqlite3",
        reports_dir=tmp_path / "data" / "reports",
        copy_max_leaders_per_run=3,
        info_min_request_interval_ms=0,
    )


def _write_shortlist(config: AppConfig, count: int) -> None:
    report = select_leaderboard_shortlist(
        [_candidate(index) for index in range(1, count + 1)],
        config=LeaderboardSelectionConfig(target_count=count, min_score=1),
    )
    write_shortlist_report(report, shortlist_path(config))


def test_copy_preflight_reports_missing_shortlist(tmp_path):
    report = run_copy_preflight(_config(tmp_path), network_read=True)

    assert report.ready_for_bounded_read is False
    assert any(issue.code == "SOURCE_UNAVAILABLE" for issue in report.issues)


def test_copy_preflight_limits_shortlist_to_three(tmp_path):
    config = _config(tmp_path)
    _write_shortlist(config, 4)

    report = run_copy_preflight(config, network_read=True)
    json_path, md_path = write_copy_preflight_report(report, config.reports_dir)

    assert report.ready_for_bounded_read is True
    assert report.leaders_planned == 3
    assert any(issue.code == "SHORTLIST_LIMIT_APPLIED" for issue in report.issues)
    assert json_path.exists()
    assert "leaders planned: 3/3" in md_path.read_text(encoding="utf-8")


def test_copy_run_limits_network_reads_to_max_leaders(tmp_path):
    config = _config(tmp_path)
    _write_shortlist(config, 4)
    fake = EmptyFakeInfoClient()

    report = run_copy_dry_run(config, network_read=True, info_client=fake, max_leaders=2)

    clearinghouse_calls = [call for call in fake.calls if call.startswith("clearinghouseState:")]
    assert len(clearinghouse_calls) == 2
    assert report.leaders_seen == 2
    assert any(decision.reason == NoTradeReason.RATE_LIMIT_GUARD for decision in report.no_trade_decisions)


def test_cli_writes_shortlist_template(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "leaderboard_template.csv"

    code = main(["--write-shortlist-template", str(output)])

    assert code == 0
    text = output.read_text(encoding="utf-8")
    assert "wallet_address" in text
    assert "closed_pnl_points" in text
