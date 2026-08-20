from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from hl_observer.collection.userfills_live import parser_message_userfills
from hl_observer.realtime.durable_dedup import (
    DurableDedupCorruption,
    DurableEventDedup,
)
from hl_observer.realtime.event_identity import canonicalize_frame
from hl_observer.realtime.feed_quality import (
    FeedMode,
    FeedQualityConfig,
    FeedQualityGate,
)
from hl_observer.realtime.global_ws_budget import GlobalWsBudget
from hl_observer.realtime_monitor.ws_supervisor import WsSupervisor
from hl_observer.sources.collection_recorder import CollectionRecorder
from hl_observer.sources.models import SourceStatus
from hl_observer.storage.raw_store import RawStore
from hl_observer.storage.run_context import RunContext
from hl_observer.wallets.user_fills_multiplex import plan_multiplex_chunks


def _wallet(index: int) -> str:
    return "0x" + f"{index:040x}"


def test_trade_batch_same_frame_keeps_unique_event_ids():
    events = canonicalize_frame(
        [
            {"coin": "BTC", "time": 1000, "tid": 1, "px": "10"},
            {"coin": "BTC", "time": 1000, "tid": 2, "px": "10"},
        ],
        source="HL_WS",
        channel="trades",
        received_at_ms=1010,
        frame_sequence=7,
    )

    assert [event.frame_sequence for event in events] == [7, 7]
    assert [event.event_index_in_frame for event in events] == [0, 1]
    assert len({event.stable_event_id for event in events}) == 2


def test_trade_batch_same_frame_does_not_false_flag_sequence():
    gate = FeedQualityGate(
        source_id="hl",
        channel="trades",
        instrument="BTC",
        mode=FeedMode.EVENT_STREAM,
        config=FeedQualityConfig(min_coherent_events=1),
    )
    gate.mark_heartbeat(received_ts_ms=1010)

    snapshots = gate.ingest_event_batch(
        payloads=[
            {"coin": "BTC", "time": 1000, "tid": 1},
            {"coin": "BTC", "time": 1000, "tid": 2},
        ],
        received_ts_ms=1010,
        frame_sequence=42,
    )

    assert len(snapshots) == 2
    assert gate.accepted_events == 2
    assert gate.non_monotonic == 0
    assert "NON_MONOTONIC_SEQUENCE" not in snapshots[-1].reasons


def test_userfills_parser_exposes_frame_coordinates_and_stable_ids():
    parsed = parser_message_userfills(
        {
            "channel": "userFills",
            "sequence": 9,
            "data": {
                "isSnapshot": False,
                "fills": [
                    {
                        "coin": "BTC",
                        "px": "100",
                        "sz": "1",
                        "time": 1000,
                        "tid": 1,
                        "side": "B",
                    },
                    {
                        "coin": "BTC",
                        "px": "100",
                        "sz": "1",
                        "time": 1000,
                        "tid": 2,
                        "side": "B",
                    },
                ],
            },
        }
    )

    assert [row["frame_sequence"] for row in parsed] == [9, 9]
    assert [row["event_index_in_frame"] for row in parsed] == [0, 1]
    assert len({row["stable_event_id"] for row in parsed}) == 2


def test_canonical_dedup_survives_restart(tmp_path: Path):
    first = DurableEventDedup(tmp_path)
    assert not first.check_and_mark("event-1", seen_at_ms=1).duplicate

    restarted = DurableEventDedup(tmp_path)
    assert restarted.check_and_mark("event-1", seen_at_ms=2).duplicate
    assert restarted.count() == 1


def test_dedup_archives_never_overwrite_previous_archive(tmp_path: Path):
    store = DurableEventDedup(tmp_path, max_entries=1, compact_every=1)
    for index in range(5):
        store.check_and_mark(f"event-{index}", seen_at_ms=index)

    archives = sorted((tmp_path / "archives").glob("dedup_*.jsonl"))
    assert len(archives) == 4
    assert len({path.name for path in archives}) == 4
    archived_ids = {
        json.loads(line)["event_id"]
        for path in archives
        for line in path.read_text(encoding="utf-8").splitlines()
    }
    assert archived_ids == {"event-0", "event-1", "event-2", "event-3"}


def test_corrupted_dedup_blocks_strict_reuse(tmp_path: Path):
    path = tmp_path / "dedup.sqlite3"
    path.write_bytes(b"not-a-sqlite-database")

    with pytest.raises(DurableDedupCorruption):
        DurableEventDedup(tmp_path)


def test_snapshot_reconnect_is_idempotent(tmp_path: Path):
    message = {
        "channel": "userFills",
        "data": {
            "isSnapshot": True,
            "fills": [{"hash": "0x1", "coin": "BTC", "time": 1000}],
        },
    }
    first = WsSupervisor(durable_dedup=DurableEventDedup(tmp_path))
    assert first.accept_message(message, received_at_ms=1100).accepted

    restarted = WsSupervisor(durable_dedup=DurableEventDedup(tmp_path))
    replay = restarted.accept_message(message, received_at_ms=1200)
    assert not replay.accepted
    assert replay.reason == "DUPLICATE_WS_SNAPSHOT"


def test_global_ws_budget_max_10_connections(tmp_path: Path):
    budget = GlobalWsBudget(tmp_path / "budget.json")
    for index in range(10):
        decision = budget.reserve_connection(
            connection_id=f"c{index}",
            now_ms=1,
        )
        assert decision.allowed
    denied = budget.reserve_connection(connection_id="c10", now_ms=1)
    assert not denied.allowed
    assert "WS_CONNECTION_CAP_EXCEEDED" in denied.reasons


def test_global_ws_budget_max_10_unique_user_subscriptions(tmp_path: Path):
    budget = GlobalWsBudget(tmp_path / "budget.json")
    accepted = budget.reserve_connection(
        connection_id="first",
        users=[_wallet(index) for index in range(10)],
        subscriptions=10,
        now_ms=1,
    )
    denied = budget.reserve_connection(
        connection_id="second",
        users=[_wallet(11)],
        subscriptions=1,
        now_ms=1,
    )
    assert accepted.allowed
    assert not denied.allowed
    assert "WS_UNIQUE_USER_CAP_EXCEEDED" in denied.reasons


def test_global_ws_budget_max_30_new_connections_per_minute(tmp_path: Path):
    budget = GlobalWsBudget(tmp_path / "budget.json")
    for index in range(30):
        connection_id = f"c{index}"
        assert budget.reserve_connection(
            connection_id=connection_id,
            now_ms=1,
        ).allowed
        budget.release(connection_id, now_ms=1)
    denied = budget.reserve_connection(connection_id="c30", now_ms=1)
    assert not denied.allowed
    assert "WS_NEW_CONNECTIONS_PER_MINUTE_CAP_EXCEEDED" in denied.reasons


def test_global_ws_budget_max_1000_subscriptions(tmp_path: Path):
    budget = GlobalWsBudget(tmp_path / "budget.json")
    assert budget.reserve_connection(
        connection_id="first",
        subscriptions=1000,
        now_ms=1,
    ).allowed
    denied = budget.reserve_connection(
        connection_id="second",
        subscriptions=1,
        now_ms=1,
    )
    assert not denied.allowed
    assert "WS_SUBSCRIPTION_CAP_EXCEEDED" in denied.reasons


def test_global_ws_budget_max_2000_messages_per_minute(tmp_path: Path):
    budget = GlobalWsBudget(tmp_path / "budget.json")
    assert budget.reserve_messages(2000, now_ms=1).allowed
    denied = budget.reserve_messages(1, now_ms=1)
    assert not denied.allowed
    assert "WS_MESSAGES_PER_MINUTE_CAP_EXCEEDED" in denied.reasons


def test_multiplex_never_plans_more_than_10_unique_users():
    chunks = plan_multiplex_chunks(
        [_wallet(index) for index in range(50)],
        wallets_per_connection=3,
        max_connections=10,
    )
    assert sum(len(chunk) for chunk in chunks) == 10
    assert len({wallet for chunk in chunks for wallet in chunk}) == 10


def test_feed_quality_exposes_latency_jitter_gap_and_rates():
    gate = FeedQualityGate(
        source_id="hl",
        channel="trades",
        instrument="BTC",
        mode=FeedMode.EVENT_STREAM,
        config=FeedQualityConfig(min_coherent_events=1, max_gap_ms=50),
    )
    gate.mark_heartbeat(received_ts_ms=1000)
    gate.ingest_event(
        payload={"tid": 1},
        exchange_ts_ms=900,
        received_ts_ms=1000,
    )
    snapshot = gate.ingest_event(
        payload={"tid": 2},
        exchange_ts_ms=1080,
        received_ts_ms=1100,
    )

    assert snapshot.latency_p99_ms is not None
    assert snapshot.jitter_ema_ms is not None
    # A sparse independent trade stream is not a websocket transport gap.
    assert snapshot.gap_duration_ms == 0
    assert snapshot.gaps == 0
    assert snapshot.stale_rate == 0
    assert snapshot.duplicate_rate == 0
    assert snapshot.out_of_order_rate == 0


class _FailingRawStore(RawStore):
    def put(self, event):  # noqa: ANN001
        raise OSError("disk full")


def test_ingestion_exception_is_not_quiet_market():
    recorder = CollectionRecorder(
        raw_store=_FailingRawStore(),
        context=RunContext.LIVE,
        run_id="run-real",
        config_hash="cfg",
        code_hash="code",
        git_head="head",
    )
    health = recorder.record_rest(
        request_type="allMids",
        response={"BTC": "100"},
        now_ms=1000,
    )

    assert health is not None
    assert health.status in (SourceStatus.DEGRADED, SourceStatus.DOWN)
    assert recorder.recorder_failures == 1
    assert recorder.summary(now_ms=1000)["last_recorder_error"]


def test_critical_fetch_provenance_has_explicit_origin_and_clocks():
    recorder = CollectionRecorder(
        context=RunContext.LIVE,
        run_id="run-real",
        config_hash="cfg",
        code_hash="code",
        git_head="head",
    )
    recorder.record_ws(
        channel="trades",
        message={"data": [{"coin": "BTC"}]},
        now_ms=1000,
    )
    event = recorder.raw_store.recent(context=RunContext.LIVE)[0]

    assert event.origin == "LIVE_REAL"
    assert event.received_at_ms == 1000
    assert event.written_at_ms == 1000
    assert event.run_id == "run-real"
    assert event.config_hash == "cfg"
    assert event.code_hash == "code"
    assert event.git_head == "head"


def test_operational_journal_reads_active_and_all_archives(tmp_path: Path):
    tools = Path(__file__).resolve().parents[1] / "tools"
    sys.path.insert(0, str(tools))
    from journal_operationnel import JournalOperationnel

    journal = JournalOperationnel(tmp_path, max_octets=1)
    journal.enregistrer("WS_DISCONNECT", ts_ms=1)
    journal.enregistrer("PARTIAL_FILL", ts_ms=2)
    summary = journal.resume()

    assert summary["n_incidents"] == 2
    assert summary["par_type"]["WS_DISCONNECT"] == 1
    assert summary["par_type"]["PARTIAL_FILL"] == 1
