"""Phase 7 (canonical): replay fills + deltas + books with delays/stale/partial."""

from __future__ import annotations

from hyper_smart_observer.backtesting.event_replay import (
    BOOK,
    DELTA,
    FILL,
    ReplayEvent,
    replay_event_stream,
)
import json

from hyper_smart_observer.backtesting.replay_engine import PaperReplayEvent, ReplayEngine, write_paper_replay_result
from hyper_smart_observer.dashboard.exporter import export_dashboard
from tests.hl_runtime_fakes import LEADER, runtime_config, seed_scored_wallet

W = "0x" + "d" * 40


def _book(coin, ts):
    return ReplayEvent(kind=BOOK, coin=coin, ts_ms=ts, best_bid=100.0, best_ask=100.1)


def test_replay_counts_fills_skips_stale_and_uses_books():
    events = [
        _book("BTC", 0),
        ReplayEvent(kind=FILL, coin="BTC", ts_ms=1_000, closed_pnl=10.0),     # fresh book -> counted
        ReplayEvent(kind=DELTA, coin="BTC", ts_ms=1_500, leader_size=2.0),    # context only
        _book("BTC", 2_000),
        ReplayEvent(kind=FILL, coin="BTC", ts_ms=3_000, closed_pnl=5.0, is_partial=True),  # counted, partial
        ReplayEvent(kind=FILL, coin="ETH", ts_ms=4_000, closed_pnl=99.0),     # no book -> skipped
    ]
    report = replay_event_stream(W, events, scenario="ws")
    assert report.simulated_trades == 2
    assert report.skipped_actions == 1  # ETH fill with no book
    assert any("SOURCE_UNAVAILABLE" in w for w in report.warnings)
    assert any("PARTIAL_FILL" in w for w in report.warnings)
    assert report.net_pnl < 15.0  # fees subtracted from 10 + 5


def test_replay_stale_book_beyond_max_age_is_skipped():
    events = [
        _book("BTC", 0),
        ReplayEvent(kind=FILL, coin="BTC", ts_ms=10_000, closed_pnl=10.0),  # book 10s old > 6s
    ]
    report = replay_event_stream(W, events, max_signal_age_ms=6_000)
    assert report.simulated_trades == 0
    assert report.skipped_actions == 1
    assert any("STALE_SIGNAL" in w for w in report.warnings)


def test_replay_copy_delay_reduces_net_pnl():
    base = [_book("BTC", 0), ReplayEvent(kind=FILL, coin="BTC", ts_ms=1_000, closed_pnl=10.0)]
    delayed = [_book("BTC", 0), ReplayEvent(kind=FILL, coin="BTC", ts_ms=1_000, closed_pnl=10.0, delay_ms=300_000)]
    r_ws = replay_event_stream(W, base, scenario="ws")
    r_5m = replay_event_stream(W, delayed, scenario="delay_5m")
    assert r_5m.net_pnl < r_ws.net_pnl  # 5-minute copy delay degrades edge


def test_replay_never_uses_future_book_snapshot_no_lookahead():
    events = [
        ReplayEvent(kind=FILL, coin="BTC", ts_ms=1_000, closed_pnl=10.0),
        _book("BTC", 2_000),  # arrives after the fill: cannot justify the older fill
    ]
    report = replay_event_stream(W, events, scenario="no_lookahead")
    assert report.simulated_trades == 0
    assert report.skipped_actions == 1
    assert any("SOURCE_UNAVAILABLE" in w for w in report.warnings)
"""Same models -> parity by construction (BacktestReport, fee/delay models)."""


def test_replay_paper_events_uses_existing_paper_engine_for_open_close(tmp_path):
    cfg = runtime_config(tmp_path)
    seed_scored_wallet(cfg, LEADER)
    result = ReplayEngine().replay_paper_events(
        cfg,
        LEADER,
        [
            PaperReplayEvent(action="OPEN_LONG", coin="BTC", price=100.0, notional=50.0, ts_ms=1),
            PaperReplayEvent(action="CLOSE_LONG", coin="BTC", price=110.0, ts_ms=2),
        ],
        run_id="paper-replay-proof",
    )
    assert result.opened == 1
    assert result.closed == 1
    assert result.open_trades == 0
    assert result.realized_pnl > 0
    assert any(entry.decision_type == "PAPER_EXIT_CLOSE" for entry in result.ledger_entries)
    assert any(entry.realized_net_pnl and entry.realized_net_pnl > 0 for entry in result.ledger_entries)


def test_replay_paper_events_close_without_position_is_no_trade(tmp_path):
    cfg = runtime_config(tmp_path)
    seed_scored_wallet(cfg, LEADER)
    result = ReplayEngine().replay_paper_events(
        cfg,
        LEADER,
        [PaperReplayEvent(action="CLOSE_LONG", coin="BTC", price=110.0, ts_ms=1)],
        run_id="paper-replay-no-match",
    )
    assert result.opened == 0
    assert result.closed == 0
    assert result.skipped == 1
    assert any(entry.decision_type == "PAPER_EXIT_NO_TRADE" for entry in result.ledger_entries)


def test_paper_replay_result_exports_json_csv_markdown_and_dashboard(tmp_path):
    cfg = runtime_config(tmp_path)
    seed_scored_wallet(cfg, LEADER)
    result = ReplayEngine().replay_paper_events(
        cfg,
        LEADER,
        [
            PaperReplayEvent(action="OPEN_LONG", coin="BTC", price=100.0, notional=50.0, ts_ms=1),
            PaperReplayEvent(action="CLOSE_LONG", coin="BTC", price=110.0, ts_ms=2),
        ],
        run_id="paper-replay-export",
    )
    export = write_paper_replay_result(result, cfg.reports_dir, run_id="paper-replay-export")
    assert export.json_path.exists()
    assert export.csv_path.exists()
    assert export.markdown_path.exists()
    payload = json.loads(export.json_path.read_text(encoding="utf-8"))
    assert payload["net_pnl"] == result.realized_pnl
    assert payload["total_usable_trades"] == result.opened + result.closed
    assert payload["ledger_entries"]
    html = export_dashboard(cfg).read_text(encoding="utf-8")
    assert "paper_replay" in html
    assert str(result.realized_pnl) in html
