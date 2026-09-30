from __future__ import annotations

import json
from pathlib import Path

from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.hyperliquid_client.info_client import PaginationResult
from hyper_smart_observer.storage.database import get_connection
from hyper_smart_observer.storage.repositories import paper_trades_repo
from tests.test_hypersmart_copy_network_read import FakeInfoClient, _config, _seed_scored_wallet, _write_shortlist


class LeaderClosedFakeInfoClient(FakeInfoClient):
    def get_all_mids(self):
        self.calls.append("allMids")
        return {"BTC": "103.0"}

    def get_l2_book(self, coin: str):
        self.calls.append(f"l2Book:{coin.upper()}")
        return {
            "coin": coin.upper(),
            "levels": [
                [{"px": "102.8", "sz": "4"}, {"px": "102.4", "sz": "2"}],
                [{"px": "103.2", "sz": "3"}, {"px": "103.8", "sz": "2"}],
            ],
        }

    def get_clearinghouse_state(self, address: str):
        self.calls.append("clearinghouseState")
        return {"marginSummary": {"accountValue": "1000"}, "assetPositions": []}

    def collect_user_fills_by_time_paginated(self, address: str, start_time_ms: int, end_time_ms: int, *, max_pages=None):
        self.calls.append("userFillsByTime")
        return PaginationResult(
            fills=[
                {
                    "coin": "BTC",
                    "dir": "Close Long",
                    "px": "103.0",
                    "sz": "1",
                    "fee": "0.05",
                    "time": self.now_ms + 99,
                    "hash": "close-hash",
                    "tid": 99,
                    "closedPnl": "3.0",
                    "startPosition": "1",
                    "feeToken": "USDC",
                }
            ],
            pages_fetched=1,
            stopped_reason="empty_response",
            warnings=[],
        )


class LeaderReducedFakeInfoClient(LeaderClosedFakeInfoClient):
    def get_clearinghouse_state(self, address: str):
        self.calls.append("clearinghouseState")
        return {
            "marginSummary": {"accountValue": "1000"},
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "0.5",
                        "entryPx": "100",
                        "markPx": "103",
                        "unrealizedPnl": "1.5",
                    }
                }
            ],
        }

    def collect_user_fills_by_time_paginated(self, address: str, start_time_ms: int, end_time_ms: int, *, max_pages=None):
        self.calls.append("userFillsByTime")
        return PaginationResult(
            fills=[
                {
                    "coin": "BTC",
                    "dir": "Close Long",
                    "px": "103.0",
                    "sz": "0.5",
                    "fee": "0.03",
                    "time": self.now_ms + 199,
                    "hash": "reduce-hash",
                    "tid": 199,
                    "closedPnl": "1.5",
                    "startPosition": "1",
                    "feeToken": "USDC",
                }
            ],
            pages_fetched=1,
            stopped_reason="empty_response",
            warnings=[],
        )


def test_copy_run_follows_leader_close_into_existing_paper_trade(tmp_path):
    config = _config(tmp_path)
    _write_shortlist(config)
    _seed_scored_wallet(config)

    first = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=FakeInfoClient())
    assert any(row.get("paper_trade_id") for row in json.loads(Path(first.decision_ledger_json_path).read_text(encoding="utf-8")))
    with get_connection(config) as conn:
        opened_count = len(paper_trades_repo.list_open_paper_trades(conn))
        assert opened_count >= 1

    second = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=LeaderClosedFakeInfoClient())
    assert second.decision_ledger_json_path is not None
    rows = json.loads(Path(second.decision_ledger_json_path).read_text(encoding="utf-8"))
    exit_rows = [row for row in rows if row.get("decision_type") == "PAPER_EXIT_CLOSE"]
    assert len(exit_rows) == opened_count
    assert exit_rows[0]["paper_trade_id"]
    assert float(exit_rows[0]["realized_net_pnl"]) > 0
    assert exit_rows[0]["exit_trigger"] == "LEADER_CLOSE"
    with get_connection(config) as conn:
        assert len(paper_trades_repo.list_open_paper_trades(conn)) == 0
        closed = paper_trades_repo.list_closed_paper_trades(conn)
        assert closed and float(closed[0]["net_pnl"]) > 0


def test_copy_run_follows_leader_reduce_as_partial_paper_close(tmp_path):
    config = _config(tmp_path)
    _write_shortlist(config)
    _seed_scored_wallet(config)

    first = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=FakeInfoClient())
    assert first.decision_ledger_json_path is not None
    with get_connection(config) as conn:
        opened_count = len(paper_trades_repo.list_open_paper_trades(conn))
        assert opened_count >= 1

    second = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=LeaderReducedFakeInfoClient())
    assert second.decision_ledger_json_path is not None
    rows = json.loads(Path(second.decision_ledger_json_path).read_text(encoding="utf-8"))
    reduce_rows = [row for row in rows if row.get("decision_type") == "PAPER_EXIT_REDUCE"]
    assert reduce_rows
    assert reduce_rows[0]["paper_trade_id"]
    assert float(reduce_rows[0]["realized_net_pnl"]) > 0
    assert reduce_rows[0]["exit_trigger"] == "LEADER_REDUCE"
    with get_connection(config) as conn:
        open_rows = paper_trades_repo.list_open_paper_trades(conn)
        closed_rows = paper_trades_repo.list_closed_paper_trades(conn)
        assert open_rows
        assert len(open_rows) >= opened_count
        assert any(":partial:" in row["trade_id"] for row in closed_rows)
