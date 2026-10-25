from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from tools import collect_cloud_copy_vault as C


def test_snapshot_and_live_userfills_are_separate_families() -> None:
    snapshot, snapshot_fills = C.userfills_envelope(
        {
            "channel": "userFills",
            "data": {
                "user": "0x" + "1" * 40,
                "isSnapshot": True,
                "fills": [
                    {
                        "coin": "BTC",
                        "px": "100",
                        "sz": "1",
                        "side": "B",
                        "time": 1_000,
                        "dir": "Open Long",
                        "hash": "0xsnap",
                        "tid": 1,
                        "oid": 1,
                    }
                ],
            },
        },
        vault="0x" + "1" * 40,
        receive_wall_ms=1_010,
        receive_mono_ns=123,
        connection_id="copy-test",
    )
    assert snapshot is not None
    assert snapshot.channel == "copy_vault_snapshot"
    assert snapshot.event_kind.value == "SNAPSHOT"
    assert snapshot.parsed_summary["is_snapshot"] is True
    assert snapshot_fills[0]["received_at_ms"] == 1_010
    assert snapshot_fills[0]["recv_mono_ns"] == 123

    live, live_fills = C.userfills_envelope(
        {
            "channel": "userFills",
            "data": {
                "user": "0x" + "1" * 40,
                "isSnapshot": False,
                "fills": [
                    {
                        "coin": "BTC",
                        "px": "101",
                        "sz": "1",
                        "side": "A",
                        "time": 1_020,
                        "dir": "Close Long",
                        "hash": "0xlive",
                        "tid": 2,
                        "oid": 2,
                    }
                ],
            },
        },
        vault="0x" + "1" * 40,
        receive_wall_ms=1_025,
        receive_mono_ns=456,
        connection_id="copy-test",
    )
    assert live is not None
    assert live.channel == "copy_vault_fills"
    assert live.event_kind.value == "EVENT"
    assert live.exchange_ts_ms == 1_020
    assert live_fills[0]["connection_id"] == "copy-test"


def test_selection_envelope_is_observation_only_and_causal() -> None:
    address = "0x" + "2" * 40
    selection = {
        "selected_at_ms": 5_000,
        "source": "https://stats-data.hyperliquid.xyz/Mainnet/vaults",
        "filters": {"min_tvl_usd": 100000, "min_age_days": 45},
    }
    envelope = C.selection_envelope(
        {
            "address": address,
            "tvl_usd": 1_000_000,
            "age_j": 100,
            "apr_pct": 10,
        },
        selection,
    )
    record = envelope.as_record(written_ts_ms=5_010)
    assert record["instrument"] == address
    assert record["exchange_ts_ms"] is None
    assert record["provenance"]["selection_causal"] is True
    assert record["parsed_summary"]["observation_only"] is True


def test_exact_window_backfill_splits_at_2000_response_cap() -> None:
    address = "0x" + "3" * 40

    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            start = int(body["startTime"])
            end = int(body["endTime"])
            if end - start > 5_000:
                rows = [
                    {
                        "coin": "BTC",
                        "px": "100",
                        "sz": "1",
                        "side": "B",
                        "time": start + index,
                        "dir": "Open Long",
                        "hash": f"0x{index:064x}",
                        "tid": index,
                        "oid": index,
                    }
                    for index in range(C.CAP_USERFILLS)
                ]
            else:
                rows = [
                    {
                        "coin": "BTC",
                        "px": "100",
                        "sz": "1",
                        "side": "B",
                        "time": start + 1,
                        "dir": "Open Long",
                        "hash": f"0x{start:064x}",
                        "tid": start,
                        "oid": start,
                    }
                ]
            return httpx.Response(200, json=rows)

        client = httpx.AsyncClient(
            base_url="https://api.hyperliquid.xyz",
            transport=httpx.MockTransport(handler),
        )
        rows, audit = await C.exact_window_backfill(
            client,
            address,
            start_ms=10_000,
            end_ms=20_000,
        )
        await client.aclose()
        assert audit["status"] == "COMPLETE"
        assert audit["requests"] == 3
        assert audit["splits"] == 1
        assert len(rows) == 2

    asyncio.run(scenario())


def test_exact_window_backfill_fails_closed_when_request_budget_is_exhausted() -> None:
    address = "0x" + "6" * 40

    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            start = int(body["startTime"])
            rows = [
                {
                    "coin": "BTC",
                    "px": "100",
                    "sz": "1",
                    "side": "B",
                    "time": start + index,
                    "dir": "Open Long",
                    "hash": f"0x{index:064x}",
                    "tid": index,
                    "oid": index,
                }
                for index in range(C.CAP_USERFILLS)
            ]
            return httpx.Response(200, json=rows)

        client = httpx.AsyncClient(
            base_url="https://api.hyperliquid.xyz",
            transport=httpx.MockTransport(handler),
        )
        rows, audit = await C.exact_window_backfill(
            client,
            address,
            start_ms=10_000,
            end_ms=30_000,
            max_requests=2,
        )
        await client.aclose()
        assert rows == []
        assert audit["status"] == "PARTIAL"
        assert audit["requests"] == 2
        assert audit["request_budget_exhausted"] is True
        assert audit["pending_windows"] > 0

    asyncio.run(scenario())


def test_exact_window_backfill_marks_unparseable_source_rows_partial() -> None:
    address = "0x" + "a" * 40

    async def scenario() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"coin": "BTC", "px": "bad"}])

        client = httpx.AsyncClient(
            base_url="https://api.hyperliquid.xyz",
            transport=httpx.MockTransport(handler),
        )
        rows, audit = await C.exact_window_backfill(
            client, address, start_ms=10_000, end_ms=20_000,
        )
        await client.aclose()
        assert rows == []
        assert audit["status"] == "PARTIAL"
        assert audit["invalid_source_rows"] == 1

    asyncio.run(scenario())


def test_recent_history_backfill_keeps_the_latest_fill_ceiling(monkeypatch) -> None:
    address = "0x" + "b" * 40
    fills = [
        {
            "vault": address, "coin": "BTC", "px": "100", "sz": "1",
            "side": "B", "time": 10_000 + index, "dir": "Open Long",
            "hash": f"0x{index:064x}", "tid": index, "oid": index,
        }
        for index in range(5)
    ]

    async def scenario():
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=fills)

        client = httpx.AsyncClient(
            base_url="https://api.hyperliquid.xyz",
            transport=httpx.MockTransport(handler),
        )
        rows, audit = await C.recent_history_backfill(
            client, address, end_ms=20_000, target_fills=3, max_requests=8,
        )
        await client.aclose()
        assert [row["ts_ms"] for row in rows] == [10_002, 10_003, 10_004]
        assert audit["status"] == "COMPLETE"
        assert audit["visible_fill_ceiling"] is True
        assert audit["rows"] == 3

    asyncio.run(scenario())


def test_recent_history_backfill_never_calls_a_capped_window_complete():
    address = "0x" + "c" * 40

    async def scenario():
        async def handler(_request: httpx.Request) -> httpx.Response:
            rows = [
                {
                    "coin": "BTC", "px": "100", "sz": "1", "side": "B",
                    "time": 1_000 + index, "dir": "Open Long",
                    "hash": f"0x{index:064x}", "tid": index, "oid": index,
                }
                for index in range(C.CAP_USERFILLS)
            ]
            return httpx.Response(200, json=rows)

        client = httpx.AsyncClient(
            base_url="https://api.hyperliquid.xyz",
            transport=httpx.MockTransport(handler),
        )
        rows, audit = await C.recent_history_backfill(
            client, address, end_ms=20_000, target_fills=10_000,
            max_requests=1,
        )
        await client.aclose()
        assert rows == []
        assert audit["status"] == "PARTIAL"
        assert audit["request_budget_exhausted"] is True
        assert audit["pending_windows"] > 0

    asyncio.run(scenario())


def test_userfills_gate_enforces_the_campaign_weight_budget():
    async def scenario():
        gate = C.UserFillsRateGate(
            weight_budget_per_minute=900,
            campaign_weight_budget=120,
            campaign_request_budget=10,
        )
        await gate.acquire()
        await gate.record(120)
        assert gate.request_count == 1
        assert gate.weight_used == 120
        assert gate.exhausted is True
        try:
            await gate.acquire()
        except C.UserFillsBudgetExhausted:
            pass
        else:
            raise AssertionError("campaign weight budget must stop another REST request")

    asyncio.run(scenario())


def test_bundle_keeps_forward_selection_metadata(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    output = tmp_path / "bundle"
    writer = C.PartitionedTickDatasetWriter(raw, rotate_bytes=10_000_000, flush_every=1)
    address = "0x" + "4" * 40
    envelope, fills = C.userfills_envelope(
        {
            "channel": "userFills",
            "data": {
                "user": address,
                "isSnapshot": False,
                "fills": [
                    {
                        "coin": "ETH",
                        "px": "2000",
                        "sz": "1",
                        "side": "B",
                        "time": 10_000,
                        "dir": "Open Long",
                        "hash": "0xfill",
                        "tid": 1,
                        "oid": 1,
                    }
                ],
            },
        },
        vault=address,
        receive_wall_ms=10_010,
        receive_mono_ns=123,
        connection_id="copy-vault-test",
    )
    assert envelope is not None
    writer.append(envelope)
    writer.rotate_all()

    fill_id = C.canonical_fill_id(fills[0])
    index = C.build_copy_vault_bundle(
        raw,
        output,
        collector_version="a" * 40,
        reconciliation={
            address: {
                "status": "MATCHED",
                "live_count": 1,
                "reference_count": 1,
                "matched_count": 1,
                "missing_from_live": 0,
                "live_only": 0,
            }
        },
        queue_drops={},
        selection={
            "selected_at_ms": 9_000,
            "observation_only": True,
            "vaults": [{"address": address}],
        },
        collection_run_id="copy-vault-test-run",
    )
    assert fill_id
    assert index["collection_kind"] == "copy_vault_forward"
    assert index["collection_run_id"] == "copy-vault-test-run"
    manifest_paths = list((output / "manifests").glob("*.json"))
    assert len(manifest_paths) == 1
    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert manifest["family"] == "copy_vault_fills"
    assert manifest["collection_run_id"] == "copy-vault-test-run"
    assert manifest["reconciliation"]["status"] == "MATCHED"
    assert manifest["copy_vault_selection"]["forward_only"] is True
    # Before GitHub release upload the asset is intentionally not SAFE yet.
    assert manifest["quality_status"] == "PARTIAL"
    assert "REMOTE_ASSET_NOT_VERIFIED" in manifest["quality_reasons"]



def test_copy_vault_lane_respects_hyperliquid_unique_user_limit() -> None:
    allowed = ["0x" + f"{index:040x}" for index in range(10)]
    assert C.validate_user_subscription_budget(allowed) == 10

    too_many = ["0x" + f"{index:040x}" for index in range(11)]
    import pytest
    with pytest.raises(ValueError, match="10 per IP"):
        C.validate_user_subscription_budget(too_many)


def test_copy_vault_lane_counts_unique_users_only() -> None:
    address = "0x" + "1" * 40
    assert C.validate_user_subscription_budget([address, address.upper()]) == 1



def test_reconcile_requires_per_vault_subscription_start() -> None:
    address = "0x" + "5" * 40

    async def scenario() -> None:
        result = await C.reconcile_forward_window(
            [address],
            start_ms_by_vault={},
            end_ms=20_000,
            live_ids={},
        )
        report = result[address]
        assert report["status"] == "UNAVAILABLE"
        assert report["audit"]["reason"] == "NO_LIVE_SUBSCRIPTION_START"
        assert report["audit"]["requested_start_ms"] is None

    asyncio.run(scenario())


def test_reconcile_timeout_is_unavailable_not_matched(monkeypatch) -> None:
    address = "0x" + "7" * 40

    async def slow_backfill(*_args, **_kwargs):
        await asyncio.sleep(1.0)
        return [], {"status": "COMPLETE"}

    monkeypatch.setattr(C, "exact_window_backfill", slow_backfill)
    monkeypatch.setattr(C, "RECONCILIATION_PER_VAULT_TIMEOUT_S", 0.01)

    async def scenario() -> None:
        result = await C.reconcile_forward_window(
            [address],
            start_ms_by_vault={address: 10_000},
            end_ms=20_000,
            live_ids={address: set()},
        )
        report = result[address]
        assert report["status"] == "UNAVAILABLE"
        assert report["audit"]["status"] == "PARTIAL"
        assert report["audit"]["reason"] == "REFERENCE_TIMEOUT"

    asyncio.run(scenario())

def test_broad_sweep_covers_complete_universe_in_one_compact_family() -> None:
    rows = [
        {"address": "0x" + f"{index + 20:040x}", "tvl_usd": 1000 + index}
        for index in range(4)
    ]

    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            address = body["user"]
            index = int(address[-2:], 16)
            return httpx.Response(
                200,
                json={
                    "marginSummary": {
                        "accountValue": "1000",
                        "totalNtlPos": "100",
                        "totalRawUsd": "900",
                        "totalMarginUsed": "10",
                    },
                    "assetPositions": [
                        {
                            "position": {
                                "coin": "BTC",
                                "szi": str(index),
                                "positionValue": "100",
                                "entryPx": "100",
                                "unrealizedPnl": "1",
                                "leverage": {"value": 2},
                            }
                        }
                    ],
                    "time": 1_700_000_000_000 + index,
                },
            )

        client = httpx.AsyncClient(
            base_url="https://api.hyperliquid.xyz",
            transport=httpx.MockTransport(handler),
        )

        class Sink:
            def __init__(self):
                self.rows = []

            def emit(self, envelope):
                self.rows.append(envelope)

        sink = Sink()
        result = await C.collect_broad_state(
            rows,
            sink,
            phase="START",
            request_interval_s=0.0,
            http_client=client,
        )
        await client.aclose()
        assert result["requested"] == 4
        assert result["observed"] == 4
        assert result["failed"] == 0
        assert len(sink.rows) == 4
        assert {row.instrument for row in sink.rows} == {"*"}
        assert {row.channel for row in sink.rows} == {"copy_vault_broad_state"}
        assert all(
            row.parsed_summary["position_fingerprint"]
            for row in sink.rows
        )

    asyncio.run(scenario())


def test_two_speed_ws_selection_never_exceeds_user_limit_and_rotates() -> None:
    rows = [
        {
            "address": "0x" + f"{index + 100:040x}",
            "tvl_usd": float(10_000 - index),
        }
        for index in range(20)
    ]
    states = {}
    for index, row in enumerate(rows):
        address = row["address"]
        states[address] = {
            "vault": address,
            "n_positions": 1 if index < 12 else 0,
            "expo_brute_usd": float(50_000 - index * 100),
            "position_fingerprint": f"{index:064x}",
        }

    selected_a = C.select_priority_ws_vaults(
        rows,
        {"states": states},
        max_ws_vaults=10,
        rotation_seed="run-a",
    )
    selected_b = C.select_priority_ws_vaults(
        rows,
        {"states": states},
        max_ws_vaults=10,
        rotation_seed="run-b",
    )

    assert len(selected_a) == 10
    assert C.validate_user_subscription_budget(
        [row["address"] for row in selected_a]
    ) == 10
    assert sum(row["ws_selection_reason"] == "ACTIVE_PRIORITY" for row in selected_a) == 8
    assert {
        row["address"] for row in selected_a if row["ws_selection_reason"] == "AUDIT_ROTATION"
    } != {
        row["address"] for row in selected_b if row["ws_selection_reason"] == "AUDIT_ROTATION"
    }


def test_changed_broad_state_wallets_get_rest_fill_reconciliation(monkeypatch) -> None:
    address = "0x" + "8" * 40
    another = "0x" + "9" * 40
    rows = [
        {"address": address, "tvl_usd": 1000},
        {"address": another, "tvl_usd": 500},
    ]
    fill = {
        "vault": address,
        "coin": "BTC",
        "px": "100",
        "sz": "0.1",
        "side": "B",
        "ts_ms": 1500,
        "hash": "0xfill",
        "tid": 42,
        "oid": 7,
    }
    calls = []

    async def backfill(_client, vault, *, start_ms, end_ms, max_requests=None, rate_gate=None):
        calls.append((vault, start_ms, end_ms))
        return ([fill] if vault == address else []), {
            "status": "COMPLETE",
            "requests": 1,
            "rows": 1 if vault == address else 0,
        }

    monkeypatch.setattr(C, "exact_window_backfill", backfill)

    class Sink:
        def __init__(self):
            self.rows = []

        async def emit_async(self, row):
            self.rows.append(row)

    async def scenario():
        sink = Sink()
        summary = await C.collect_changed_vault_fills(
            rows,
            {address: {"position_fingerprint": "a"}, another: {"position_fingerprint": "same"}},
            {address: {"position_fingerprint": "b"}, another: {"position_fingerprint": "same"}},
            sink,
            start_ms=1000,
            end_ms=2000,
            excluded_vaults=set(),
            max_vaults=10,
        )
        assert summary["changed_wallets"] == 1
        assert summary["reconciled_wallets"] == 1
        assert summary["deferred_wallets"] == 0
        assert summary["fills_collected"] == 1
        assert summary["vault_checkpoints"][address]["last_forward_end_ms"] == 2000
        assert summary["incomplete_wallets"] == 0
        assert calls == [(address, 1000, 2000)]
        assert len(sink.rows) == 1
        envelope = sink.rows[0]
        assert envelope.channel == "copy_vault_fills"
        assert envelope.instrument == address
        assert envelope.provenance["transport"] == "https"
        assert envelope.provenance["request_type"] == "userFillsByTime"
        assert envelope.parsed_summary["event_count"] == 1
        assert envelope.parsed_summary["exact_window"] is True

    asyncio.run(scenario())


def test_checkpointed_rest_poll_advances_only_an_exact_window(monkeypatch):
    address = "0x" + "d" * 40
    fill = {
        "vault": address,
        "coin": "BTC",
        "px": "100",
        "sz": "0.1",
        "side": "B",
        "ts_ms": 1500,
        "hash": "0xcheckpoint",
        "tid": 55,
        "oid": 9,
    }
    calls = []

    async def backfill(_client, vault, *, start_ms, end_ms, rate_gate=None):
        calls.append((vault, start_ms, end_ms))
        return [fill], {"status": "COMPLETE", "rows": 1}

    monkeypatch.setattr(C, "exact_window_backfill", backfill)

    class Sink:
        def __init__(self):
            self.rows = []

        async def emit_async(self, row):
            self.rows.append(row)

    async def scenario():
        sink = Sink()
        summary = await C.collect_checkpointed_vault_fills(
            [address],
            {},
            sink,
            start_ms=1000,
            end_ms=2000,
            excluded_vaults=set(),
            rate_gate=C.UserFillsRateGate(),
        )
        assert summary["status"] == "COMPLETE"
        assert calls == [(address, 1000, 2000)]
        assert summary["vault_checkpoints"][address]["last_forward_end_ms"] == 2000
        assert summary["wallet_reports"][address]["status"] == "SOURCE_CONTINUITY_VERIFIED"
        assert sink.rows[0].provenance["window_reconciliation_complete"] is True

    asyncio.run(scenario())


def test_checkpointed_rest_poll_keeps_the_unfinished_start_without_advancing(monkeypatch):
    address = "0x" + "e" * 40

    async def partial(_client, _vault, *, start_ms, end_ms, rate_gate=None):
        return [], {
            "status": "PARTIAL",
            "requested_start_ms": start_ms,
            "requested_end_ms": end_ms,
            "request_budget_exhausted": True,
        }

    monkeypatch.setattr(C, "exact_window_backfill", partial)

    class Sink:
        async def emit_async(self, _row):
            raise AssertionError("no partial rows are admitted")

    async def scenario():
        summary = await C.collect_checkpointed_vault_fills(
            [address],
            {},
            Sink(),
            start_ms=1000,
            end_ms=2000,
            excluded_vaults=set(),
            rate_gate=C.UserFillsRateGate(),
        )
        checkpoint = summary["vault_checkpoints"][address]
        assert "last_forward_end_ms" not in checkpoint
        assert checkpoint["forward_pending_start_ms"] == 1000
        assert checkpoint["last_forward_status"] == "PARTIAL"

    asyncio.run(scenario())


def test_changed_wallet_backfill_reports_deferred_and_partial_coverage(monkeypatch) -> None:
    addresses = ["0x" + f"{index:040x}" for index in range(3)]

    async def partial(*_args, **_kwargs):
        return [], {"status": "PARTIAL", "requests": 1, "rows": 0}

    monkeypatch.setattr(C, "exact_window_backfill", partial)

    class Sink:
        async def emit_async(self, _row):
            raise AssertionError("no rows should be emitted")

    async def scenario():
        start = {a: {"position_fingerprint": "old"} for a in addresses}
        end = {a: {"position_fingerprint": "new"} for a in addresses}
        summary = await C.collect_changed_vault_fills(
            [{"address": a} for a in addresses], start, end, Sink(),
            start_ms=1000, end_ms=2000, excluded_vaults=set(), max_vaults=2,
        )
        assert summary["changed_wallets"] == 3
        assert summary["reconciled_wallets"] == 2
        assert summary["deferred_wallets"] == 1
        assert summary["incomplete_wallets"] == 2
        assert summary["status"] == "PARTIAL"

    asyncio.run(scenario())




def test_selection_snapshot_declares_receive_clock_without_exchange_clock():
    selection = {
        "selected_at_ms": 1600,
        "source": "https://api.hyperliquid.xyz/info",
        "filters": {},
    }
    envelope = C.selection_envelope({"address": "0x" + "4" * 40}, selection)
    assert envelope.exchange_ts_ms is None
    assert envelope.received_ts_ms == 1600
    assert envelope.local_monotonic_ns is not None
    assert envelope.provenance["timestamp_semantics"] == "receive_observation_time_only"



def test_copy_vault_async_sink_waits_for_writer_instead_of_dropping():
    import asyncio
    from types import SimpleNamespace

    class Writer:
        def __init__(self):
            self.rows = []

        def append_batch_records(self, batch):
            self.rows.extend(batch)
            return batch

    async def verify():
        writer = Writer()
        sink = C.AsyncTickSink(writer, max_queue=1, batch_size=1)
        a = SimpleNamespace(source_id="vault", channel="copy_vault_fills", instrument="A")
        b = SimpleNamespace(source_id="vault", channel="copy_vault_fills", instrument="B")
        await sink.emit_async(a)
        pending = asyncio.create_task(sink.emit_async(b))
        await asyncio.sleep(0)
        assert sink.backpressure_events == 1
        assert not pending.done()
        worker = asyncio.create_task(sink.run())
        await pending
        await sink.close()
        await worker
        assert sink.drops == {}
        assert sink.accepted == sink.persisted == 2
        assert writer.rows == [a, b]

    asyncio.run(verify())
