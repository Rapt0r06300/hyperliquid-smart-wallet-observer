"""Reference-only Bitget trade gaps must never silently become WS or SAFE."""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json

import httpx
import pytest

from hl_observer.collection.trade_reconciliation import reconcile_bitget_trade_shard


def _fixture(tmp_path, *, live_count=53, extra_reference=6, corrupt_symbol=False,
             reference_outside_live_window=False):
    base = 1791682957977
    ids = [str(100000 + i) for i in range(live_count + extra_reference)]
    def row(trade_id, i):
        return {
            "tradeId": trade_id,
            "ts": str(base + (i if reference_outside_live_window else min(i, live_count - 1))),
            "symbol": "BTCUSDT" if corrupt_symbol and i == live_count else "UMAUSDT",
            "price": "1.25", "size": "0.30", "side": "buy",
        }
    references = [row(v, i) for i, v in enumerate(ids)]
    # The missing REST rows must be WITHIN the captured WS time window.
    # Keep the last reference trade in the live tape so the comparison
    # cannot legitimately clip all six gaps out of its end boundary.
    missing_start = live_count - 1
    observed = references[:missing_start] + references[missing_start + extra_reference:]
    live = [
        {"raw_payload": {"data": [reference]},
         "source_id": "bitget_public_ws", "channel": "trades"}
        for reference in observed
    ]
    path = tmp_path / "original-live.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as out:
        for record in live:
            out.write(json.dumps(record, sort_keys=True) + "\n")
    requests = []
    def responder(request):
        requests.append(request)
        assert request.url.path == "/api/v2/mix/market/fills-history"
        assert request.url.params["symbol"] == "UMAUSDT"
        assert request.url.params["productType"] == "USDT-FUTURES"
        return httpx.Response(200, json={"code": "00000", "data": references})
    return path, httpx.AsyncClient(
        transport=httpx.MockTransport(responder), base_url="https://api.bitget.com"
    ), requests, references


def _compare(path, client, **options):
    return asyncio.run(reconcile_bitget_trade_shard(
        path, symbol="UMAUSDT", start_ms=1791682957977,
        end_ms=1791682982437, client=client, **options,
    ))


def test_missing_six_real_reference_rows_are_distinct_sha_bound_and_not_merged(tmp_path):
    path, client, requests, reference = _fixture(tmp_path)
    original = path.read_bytes()
    result = _compare(path, client, missing_reference_rows_limit=8)
    assert result["status"] == "PARTIAL"
    assert result["live_count"] == 53
    assert result["reference_count"] == 59
    assert result["missing_from_live"] == 6
    assert result["live_only"] == 0
    evidence = result["missing_reference_evidence"]
    assert evidence["status"] == "REFERENCE_ONLY_NOT_MERGED_OR_REPLAY_CERTIFIED"
    assert evidence["missing_trade_count"] == 6
    assert [x["trade_id"] for x in evidence["rows"]] == [
        str(100000 + i) for i in range(52, 58)
    ]
    for item in evidence["rows"]:
        assert item["source"] == "BITGET_PUBLIC_REST_REFERENCE_ONLY"
        assert item["raw_rest_row"]["tradeId"] == item["trade_id"]
    payload = json.dumps(evidence["rows"], sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert evidence["rows_sha256"] == hashlib.sha256(payload).hexdigest()
    assert evidence["validation_allowed"] is False
    assert evidence["replay_certified"] is False
    assert evidence["reclassified_safe"] is False
    assert path.read_bytes() == original
    assert len(requests) == 1


def test_default_live_reconciliation_has_unchanged_output_contract(tmp_path):
    path, client, _requests, _reference = _fixture(tmp_path)
    result = _compare(path, client)
    assert result["status"] == "PARTIAL"
    assert result["missing_from_live"] == 6
    assert "missing_reference_evidence" not in result


def test_maximum_missing_export_limit_fails_closed(tmp_path):
    path, client, _requests, _reference = _fixture(tmp_path)
    result = _compare(path, client, missing_reference_rows_limit=5)
    assert result["status"] == "PARTIAL"
    assert result["missing_reference_evidence"]["status"] == "REFERENCE_GAP_EXCEEDS_BOUND_NOT_EXPORTED"
    assert "rows" not in result["missing_reference_evidence"]


def test_foreign_symbol_prevents_reference_row_promotion(tmp_path):
    path, client, _requests, _reference = _fixture(tmp_path, corrupt_symbol=True)
    result = _compare(path, client, missing_reference_rows_limit=8)
    assert result["missing_reference_evidence"]["status"] == "REFERENCE_GAP_INVALID_SOURCE_FIELDS_NOT_EXPORTED"
    assert "rows" not in result["missing_reference_evidence"]


def test_invalid_export_limit_rejected_before_network(tmp_path):
    path, client, requests, _reference = _fixture(tmp_path)
    for value in (-1, 129, True):
        with pytest.raises(ValueError, match="BITGET_MISSING_REFERENCE_INVALID_LIMIT"):
            _compare(path, client, missing_reference_rows_limit=value)
    assert not requests


def test_official_reference_after_last_websocket_event_is_not_a_false_gap(tmp_path):
    path, client, _requests, reference = _fixture(
        tmp_path, reference_outside_live_window=True
    )
    # The six reference-only rows have timestamps strictly after the last
    # observed WS event; the bounded public REST reconciler must not treat
    # them as missing *within* the captured interval.
    result = _compare(path, client, missing_reference_rows_limit=8)
    assert result["status"] == "MATCHED"
    assert result["reference_count"] == 53
    assert result["missing_from_live"] == 0
    assert result["missing_reference_evidence"]["missing_trade_count"] == 0
    assert result["missing_reference_evidence"]["rows"] == []
    assert len(reference) == 59
