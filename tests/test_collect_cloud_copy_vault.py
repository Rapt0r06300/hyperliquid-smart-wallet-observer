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
