"""Shared read-only Hyperliquid fake /info client for runtime tests (no network).

Not collected by pytest (no test_ prefix). Lets each test choose the l2Book so
we can prove that real l2Book-derived market features drive the decision.
"""

from __future__ import annotations

from time import time
from typing import Any

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_loop import shortlist_path
from hyper_smart_observer.copy_mode.copy_models import LeaderCandidateInput
from hyper_smart_observer.copy_mode.leaderboard_selector import (
    LeaderboardSelectionConfig,
    select_leaderboard_shortlist,
    write_shortlist_report,
)
from hyper_smart_observer.hyperliquid_client.info_client import PaginationResult

LEADER = "0x" + "1" * 40


def healthy_l2(mid: float = 50_000.0) -> dict[str, Any]:
    return {"coin": "BTC", "levels": [
        [{"px": str(mid - 5), "sz": "1"}, {"px": str(mid - 15), "sz": "2"}],
        [{"px": str(mid + 5), "sz": "1"}, {"px": str(mid + 15), "sz": "2"}],
    ]}


def thin_l2(mid: float = 50_000.0) -> dict[str, Any]:
    # total depth ~ 30 USDC << 0.5% of 10k min depth => liquidity_score < 0.5
    return {"coin": "BTC", "levels": [
        [{"px": str(mid - 5), "sz": "0.0001"}],
        [{"px": str(mid + 5), "sz": "0.0001"}],
    ]}


def wide_spread_l2(mid: float = 50_000.0) -> dict[str, Any]:
    # ~200 bps spread, deep enough that liquidity is fine: spread gate must fire
    return {"coin": "BTC", "levels": [
        [{"px": str(mid - 500), "sz": "2"}, {"px": str(mid - 600), "sz": "3"}],
        [{"px": str(mid + 500), "sz": "2"}, {"px": str(mid + 600), "sz": "3"}],
    ]}


def healthy_candles() -> list[dict[str, str]]:
    return [
        {
            "c": str(50_000 + (i % 4) * 12),
            "h": str(50_020 + i),
            "l": str(49_980 - i),
            "T": str(1_800_000_000_000 + i * 60_000),
        }
        for i in range(24)
    ]


class RuntimeFakeInfoClient:
    """Read-only fake: leader opened a BTC long; book is configurable."""

    def __init__(self, *, l2_book: dict | None = None, with_l2_method: bool = True,
                 fills: list | None = None, all_mids: dict | None = None,
                 candles: list[dict[str, str]] | None = None) -> None:
        self.calls: list[str] = []
        self.now_ms = int(time() * 1000)
        self._l2 = l2_book if l2_book is not None else healthy_l2()
        self._fills = fills
        self._all_mids = all_mids if all_mids is not None else {"BTC": "50000.0"}
        self._candles = candles if candles is not None else healthy_candles()
        if not with_l2_method:
            self.get_l2_book = None  # simulate a client without l2Book capability

    def get_all_mids(self):
        self.calls.append("allMids")
        return dict(self._all_mids)

    def get_clearinghouse_state(self, address: str):
        self.calls.append("clearinghouseState")
        return {"marginSummary": {"accountValue": "100000"},
                "assetPositions": [{"position": {"coin": "BTC", "szi": "1",
                    "entryPx": "50000", "markPx": "50010", "unrealizedPnl": "10"}}]}

    def collect_user_fills_by_time_paginated(self, address, start_time_ms, end_time_ms, *, max_pages=None):
        self.calls.append("userFillsByTime")
        fills = self._fills if self._fills is not None else [
            {"coin": "BTC", "dir": "Open Long", "px": "50000", "sz": "1", "fee": "0.5",
             "time": self.now_ms + i, "hash": f"h{i}", "tid": i, "closedPnl": "25",
             "startPosition": "0", "feeToken": "USDC"} for i in range(3)
        ]
        return PaginationResult(fills=list(fills), pages_fetched=1, stopped_reason="empty_response", warnings=[])

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

    def get_l2_book(self, coin):
        self.calls.append("l2Book")
        return self._l2

    def get_candle_snapshot(self, coin):
        self.calls.append("candleSnapshot")
        return list(self._candles)


def runtime_config(tmp_path) -> AppConfig:
    return AppConfig(
        runtime_root=tmp_path,
        database_path=tmp_path / "data" / "hs.sqlite3",
        reports_dir=tmp_path / "data" / "reports",
        dashboard_dir=tmp_path / "data" / "dashboard",
        info_min_request_interval_ms=0,
        paper_max_open_trades=5,
    )


def write_leader_shortlist(config: AppConfig, leader: str = LEADER) -> None:
    report = select_leaderboard_shortlist(
        [LeaderCandidateInput(
            wallet_address=leader, history_days=30, closed_pnl_points=50,
            total_closed_pnl=1000.0, max_single_trade_pnl=100.0, max_drawdown_pct=10.0,
            consistency_score=90.0, per_coin_stability_score=85.0,
            execution_quality_score=85.0, sample_confidence=90.0, copyability_score=90.0,
        )],
        config=LeaderboardSelectionConfig(min_score=1),
    )
    write_shortlist_report(report, shortlist_path(config))


def seed_scored_wallet(config, wallet: str = LEADER, *, final_score: float = 90.0) -> None:
    """Seed a high-quality wallet score so the RiskEngine can allow a paper intent.
    3.10/3.11 safe (uses timezone.utc, not datetime.UTC)."""
    from datetime import datetime, timezone

    from hyper_smart_observer.hyperliquid_client.models import ScoreBreakdown, Wallet, WalletScoreStatus
    from hyper_smart_observer.storage.database import get_connection, initialize_database
    from hyper_smart_observer.storage.repositories import scores_repo, wallet_repo

    initialize_database(config)
    with get_connection(config) as conn:
        wallet_repo.insert_wallet(conn, Wallet(address=wallet, source="test"))
        scores_repo.insert_score_breakdown(
            conn,
            ScoreBreakdown(
                wallet_address=wallet, calculated_at=datetime.now(timezone.utc),
                status=WalletScoreStatus.SCORED, total_fills=60, usable_fills=60, skipped_fills=0,
                net_pnl=1000.0, profit_factor=2.0, max_drawdown=0.1, sample_quality_score=90.0,
                recency_score=90.0, consistency_score=90.0, risk_score=90.0,
                confidence_score=90.0, final_score=final_score,
            ),
        )
        conn.commit()
