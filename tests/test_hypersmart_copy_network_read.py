from __future__ import annotations

import json
from pathlib import Path
from time import time

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run, shortlist_path
from hyper_smart_observer.copy_mode.copy_models import LeaderCandidateInput, NoTradeReason
from hyper_smart_observer.copy_mode.leaderboard_selector import LeaderboardSelectionConfig, select_leaderboard_shortlist, write_shortlist_report
from hyper_smart_observer.hyperliquid_client.info_client import PaginationResult
from hyper_smart_observer.hyperliquid_client.models import ScoreBreakdown, Wallet, WalletScoreStatus
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories import paper_trades_repo, scores_repo, wallet_repo


GOOD_ADDRESS = "0x" + "c" * 40


class FakeInfoClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.now_ms = int(time() * 1000)

    def get_all_mids(self):
        self.calls.append("allMids")
        return {"BTC": "100.2"}

    def get_l2_book(self, coin: str):
        self.calls.append(f"l2Book:{coin.upper()}")
        return {
            "coin": coin.upper(),
            "levels": [
                [{"px": "100.18", "sz": "20"}, {"px": "100.16", "sz": "12"}],
                [{"px": "100.20", "sz": "18"}, {"px": "100.22", "sz": "10"}],
            ],
        }

    def get_clearinghouse_state(self, address: str):
        self.calls.append("clearinghouseState")
        return {
            "marginSummary": {"accountValue": "1000"},
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "1",
                        "entryPx": "100",
                        "markPx": "102",
                        "unrealizedPnl": "2",
                    }
                }
            ]
        }

    def collect_user_fills_by_time_paginated(self, address: str, start_time_ms: int, end_time_ms: int, *, max_pages=None):
        self.calls.append("userFillsByTime")
        fills = [
            {
                "coin": "BTC",
                "dir": "Open Long",
                "px": "100",
                "sz": "1",
                "fee": "0.05",
                "time": self.now_ms + index,
                "hash": f"hash-{index}",
                "tid": index,
                "closedPnl": "2.0",
                "startPosition": "0",
                "feeToken": "USDC",
            }
            for index in range(3)
        ]
        return PaginationResult(fills=fills, pages_fetched=1, stopped_reason="empty_response", warnings=[])

    def get_user_fills(self, address: str, *, aggregate_by_time: bool = False):
        self.calls.append("userFills")
        return []

    def get_open_orders(self, address: str):
        self.calls.append("openOrders")
        return [{"coin": "BTC", "oid": 123, "side": "B", "sz": "1"}]

    def get_frontend_open_orders(self, address: str):
        self.calls.append("frontendOpenOrders")
        return []

    def get_user_fees(self, address: str):
        self.calls.append("userFees")
        return {}

    def get_user_rate_limit(self, address: str):
        self.calls.append("userRateLimit")
        return {}


class MissingEquityFakeInfoClient(FakeInfoClient):
    def get_clearinghouse_state(self, address: str):
        payload = super().get_clearinghouse_state(address)
        payload.pop("marginSummary", None)
        return payload


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        runtime_root=tmp_path,
        database_path=tmp_path / "data" / "hypersmart.sqlite3",
        reports_dir=tmp_path / "data" / "reports",
        dashboard_dir=tmp_path / "data" / "dashboard",
        info_min_request_interval_ms=0,
        paper_max_open_trades=5,
    )


def _write_shortlist(config: AppConfig) -> None:
    report = select_leaderboard_shortlist(
        [
            LeaderCandidateInput(
                wallet_address=GOOD_ADDRESS,
                history_days=30,
                closed_pnl_points=50,
                total_closed_pnl=1000.0,
                max_single_trade_pnl=100.0,
                max_drawdown_pct=10.0,
                consistency_score=90.0,
                per_coin_stability_score=85.0,
                execution_quality_score=85.0,
                sample_confidence=90.0,
                copyability_score=90.0,
            )
        ],
        config=LeaderboardSelectionConfig(min_score=1),
    )
    write_shortlist_report(report, shortlist_path(config))


def _seed_scored_wallet(config: AppConfig) -> None:
    initialize_database(config)
    with get_connection(config) as conn:
        wallet_repo.insert_wallet(conn, Wallet(address=GOOD_ADDRESS, source="test"))
        scores_repo.insert_score_breakdown(
            conn,
            ScoreBreakdown(
                wallet_address=GOOD_ADDRESS,
                calculated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                status=WalletScoreStatus.SCORED,
                total_fills=60,
                usable_fills=60,
                skipped_fills=0,
                net_pnl=1000.0,
                profit_factor=2.0,
                max_drawdown=0.1,
                sample_quality_score=90.0,
                recency_score=90.0,
                consistency_score=90.0,
                risk_score=90.0,
                confidence_score=90.0,
                final_score=90.0,
            ),
        )
        conn.commit()


def test_copy_run_network_read_collects_snapshots_deltas_signals_and_paper(tmp_path):
    config = _config(tmp_path)
    _write_shortlist(config)
    _seed_scored_wallet(config)
    fake = FakeInfoClient()

    report = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=fake)

    assert {
        "allMids",
        "clearinghouseState",
        "userFillsByTime",
        "userFills",
        "openOrders",
        "frontendOpenOrders",
        "userFees",
        "userRateLimit",
    }.issubset(set(fake.calls))
    assert "l2Book:BTC" in fake.calls
    assert report.scan_features_rows >= 1
    assert report.scan_features_json_path is not None
    assert report.scan_features_csv_path is not None
    assert report.decision_ledger_entries >= 1
    assert report.decision_ledger_json_path is not None
    scan_rows = json.loads(Path(report.scan_features_json_path).read_text(encoding="utf-8"))
    ledger_rows = json.loads(Path(report.decision_ledger_json_path).read_text(encoding="utf-8"))
    assert scan_rows
    assert scan_rows[0]["symbol"] == "BTC"
    assert scan_rows[0]["l2_levels_per_side"] == 2
    assert Path(report.scan_features_csv_path).exists()
    assert any(row.get("paper_intent_id") and row.get("paper_trade_id") for row in ledger_rows)
    assert report.deltas_seen >= 1
    assert report.signal_candidates
    assert all(signal.edge_remaining_bps is not None for signal in report.signal_candidates)
    with get_connection(config) as conn:
        assert conn.execute("SELECT COUNT(*) FROM leader_snapshots").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM position_snapshots").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM fill_snapshots").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM leader_deltas").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM copy_signal_candidates").fetchone()[0] >= 1
        assert paper_trades_repo.list_open_paper_trades(conn)


def test_copy_run_without_network_read_records_no_trade(tmp_path):
    config = _config(tmp_path)
    _write_shortlist(config)

    report = run_copy_dry_run(config, interval_seconds=300, network_read=False)

    assert any(decision.reason == NoTradeReason.NETWORK_READ_DISABLED for decision in report.no_trade_decisions)


def test_copy_run_ws_without_duration_records_fallback_no_trade(tmp_path):
    config = _config(tmp_path)
    _write_shortlist(config)

    report = run_copy_dry_run(config, interval_seconds=300, network_read=False, ws=True, duration_seconds=None)

    assert any(decision.reason == NoTradeReason.WEBSOCKET_LIMIT_GUARD for decision in report.no_trade_decisions)
    assert any(str(item).startswith("ws_fallback:") for item in report.source_failures)


def test_copy_run_refuses_paper_sizing_when_leader_equity_missing(tmp_path):
    config = _config(tmp_path)
    _write_shortlist(config)
    _seed_scored_wallet(config)
    fake = MissingEquityFakeInfoClient()

    report = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=fake)

    assert report.signal_candidates
    assert any(decision.reason == NoTradeReason.LEADER_EQUITY_MISSING for decision in report.no_trade_decisions)
    with get_connection(config) as conn:
        assert not paper_trades_repo.list_open_paper_trades(conn)
