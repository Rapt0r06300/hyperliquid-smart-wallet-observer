from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

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


def test_exact_window_backfill_keeps_original_fill_for_safe_history_storage() -> None:
    address = "0x" + "7" * 40
    source_fill = {
        "coin": "BTC", "px": "100", "sz": "1", "side": "B",
        "time": 10_001, "dir": "Open Long", "fee": "0.12",
        "feeToken": "USDC", "closedPnl": "0", "hash": "0xoriginal",
    }

    async def scenario() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[source_fill])

        client = httpx.AsyncClient(
            base_url="https://api.hyperliquid.xyz",
            transport=httpx.MockTransport(handler),
        )
        rows, audit = await C.exact_window_backfill(
            client, address, start_ms=10_000, end_ms=20_000,
        )
        await client.aclose()

        assert audit["status"] == "COMPLETE"
        assert rows[0]["raw_fill"] == source_fill

    asyncio.run(scenario())


def test_rest_backfill_envelope_is_historical_and_not_forward_evidence() -> None:
    address = "0x" + "8" * 40
    raw_fill = {
        "coin": "ETH", "px": "2000", "sz": "0.5", "side": "A",
        "time": 9_000, "dir": "Close Long", "fee": "0.04",
        "feeToken": "USDC", "hash": "0xhistorical",
    }
    audit = {
        "status": "COMPLETE", "requested_start_ms": 1_000,
        "requested_end_ms": 8_999, "requests": 1, "rows": 1,
    }

    envelopes = C.rest_backfill_envelopes(
        [{"raw_fill": raw_fill}], vault=address, audit=audit,
        receive_wall_ms=10_000, receive_mono_ns=123,
    )

    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope.channel == "copy_vault_snapshot"
    assert envelope.source_id == "hyperliquid_public_userfills_backfill"
    assert envelope.provenance["transport"] == "https"
    assert envelope.provenance["forward_evidence_allowed"] is False
    assert envelope.raw_payload["data"]["isSnapshot"] is True
    assert envelope.raw_payload["data"]["fills"] == [raw_fill]
    assert envelope.raw_payload["backfill_audit"] == audit


def test_rest_weight_pacer_leaves_headroom_under_ip_limit() -> None:
    import asyncio

    now = [0.0]
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        now[0] += delay

    async def scenario() -> None:
        pacer = C.RestWeightPacer(
            budget_weight_per_minute=600,
            monotonic_fn=lambda: now[0],
            sleep_fn=fake_sleep,
        )
        await pacer.before_request()
        now[0] += 0.1
        await pacer.before_request()

    asyncio.run(scenario())
    assert sleeps == [pytest.approx(11.9)]


def test_historical_backfill_resumes_durable_cursor_and_keeps_known_gaps(monkeypatch) -> None:
    assert C.DEFAULT_HISTORY_LOOKBACK_HOURS == 72.0
    vault = "0x" + "2" * 40
    selection_ms = 2_000_000_000_000
    checkpoint_ms = selection_ms - 60 * 60 * 1000
    observed: dict[str, int] = {}

    async def fake_backfill(client, address, *, start_ms, end_ms, **kwargs):
        observed["start_ms"] = start_ms
        observed["end_ms"] = end_ms
        return [], {
            "status": "COMPLETE",
            "requested_start_ms": start_ms,
            "requested_end_ms": end_ms,
            "rows": 0,
            "requests": 1,
            "pending_windows": 0,
            "request_budget_exhausted": False,
            "invalid_fill_count": 0,
            "failed_windows": [],
            "cap_blocked_windows": [],
            "retention_cap_reached": False,
        }

    monkeypatch.setattr(C, "exact_window_backfill", fake_backfill)
    known_gap = {"start_ms": checkpoint_ms - 100, "end_ms": checkpoint_ms - 1, "reason": "KNOWN"}
    reports, envelopes = asyncio.run(
        C.collect_historical_backfills(
            [vault],
            selection_ts_ms=selection_ms,
            lookback_hours=6,
            history_checkpoints={vault: {
                "last_complete_end_ms": checkpoint_ms,
                "unresolved_gaps": [known_gap],
            }},
        )
    )

    report = reports[vault]
    assert observed["start_ms"] == checkpoint_ms
    assert observed["end_ms"] == selection_ms - 1
    assert report["status"] == "PARTIAL"
    assert report["request_audit_status"] == "COMPLETE"
    assert report["checkpoint_advance_allowed"] is True
    assert report["unresolved_gaps"] == [known_gap]
    assert report["forward_evidence_allowed"] is False
    assert envelopes == []


def test_historical_backfill_advances_past_public_retention_cap_with_gap(monkeypatch) -> None:
    vault = "0x" + "3" * 40
    selection_ms = 2_000_000_000_000
    old_checkpoint_ms = selection_ms - 100 * 60 * 60 * 1000
    observed: dict[str, int] = {}

    async def fake_backfill(client, address, *, start_ms, end_ms, **kwargs):
        observed["start_ms"] = start_ms
        return [], {
            "status": "PARTIAL",
            "requested_start_ms": start_ms,
            "requested_end_ms": end_ms,
            "rows": 10_000,
            "requests": 12,
            "pending_windows": 0,
            "request_budget_exhausted": False,
            "invalid_fill_count": 0,
            "failed_windows": [],
            "cap_blocked_windows": [],
            "retention_cap_reached": True,
            "oldest_fill_ts_ms": start_ms + 3_600_000,
        }

    monkeypatch.setattr(C, "exact_window_backfill", fake_backfill)
    reports, _envelopes = asyncio.run(
        C.collect_historical_backfills(
            [vault],
            selection_ts_ms=selection_ms,
            lookback_hours=72,
            history_checkpoints={vault: {
                "last_reconciled_end_ms": old_checkpoint_ms,
                "unresolved_gaps": [],
            }},
        )
    )

    report = reports[vault]
    assert observed["start_ms"] == selection_ms - 1 - 72 * 60 * 60 * 1000
    assert report["status"] == "PARTIAL"
    assert report["request_audit_status"] == "PARTIAL"
    assert report["checkpoint_advance_allowed"] is True
    assert report["unresolved_gaps"] == [
        {
            "start_ms": old_checkpoint_ms,
            "end_ms": observed["start_ms"] - 1,
            "reason": "HISTORY_LOOKBACK_LIMIT_72H",
        },
        {
            "start_ms": observed["start_ms"],
            "end_ms": observed["start_ms"] + 3_600_000 - 1,
            "reason": "PUBLIC_10000_FILL_RETENTION_LIMIT",
        },
    ]


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


def test_bundle_labels_rest_backfill_historical_and_not_forward(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    output = tmp_path / "bundle"
    writer = C.PartitionedTickDatasetWriter(raw, rotate_bytes=10_000_000, flush_every=1)
    address = "0x55"
    envelope = C.rest_backfill_envelopes(
        [{"raw_fill": {
            "coin": "BTC", "px": "100", "sz": "1", "side": "B",
            "time": 9_000, "dir": "Open Long", "hash": "0xhistorical",
        }}],
        vault=address,
        audit={"status": "COMPLETE", "requested_start_ms": 1_000, "requested_end_ms": 9_001},
        receive_wall_ms=10_000,
        receive_mono_ns=123,
    )[0]
    writer.append(envelope)
    writer.rotate_all()

    report = {
        address: {
            "status": "COMPLETE", "rows": 1,
            "window_kind": "PRE_SELECTION_HISTORICAL_RESEARCH_ONLY",
            "forward_evidence_allowed": False,
        }
    }
    index = C.build_copy_vault_bundle(
        raw,
        output,
        collector_version="a" * 40,
        reconciliation={},
        queue_drops={},
        selection={"selected_at_ms": 10_000},
        collection_run_id="copy-vault-history-test",
        historical_backfill=report,
    )

    [manifest_path] = (output / "manifests").glob("*.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert index["collection_kind"] == "copy_vault_forward_plus_historical_research"
    assert manifest["copy_vault_selection"]["forward_only"] is False
    assert manifest["copy_vault_selection"]["historical_only"] is True
    assert manifest["copy_vault_history"]["status"] == "COMPLETE"
    assert manifest["reconciliation"]["forward_evidence_allowed"] is False
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
