from __future__ import annotations

import asyncio
import json

import httpx
import websockets

from hl_observer.explorer.explorer_models import (
    ExplorerEndpointProbe,
    ExplorerResult,
    ExplorerSourceStatus,
    ExplorerTransaction,
)
from hl_observer.explorer.explorer_parser import parse_explorer_payload, parse_explorer_records
from hl_observer.utils.time import now_ms

EXPLORER_URL = "https://app.hyperliquid.xyz/explorer"
EXPLORER_RPC_URL = "https://rpc.hyperliquid.xyz/explorer"
EXPLORER_WS_URL = "wss://rpc.hyperliquid.xyz/ws"


async def probe_explorer_network(
    *,
    url: str = EXPLORER_URL,
    timeout_seconds: float = 15.0,
    dry_run: bool = True,
    max_events: int = 500,
) -> ExplorerResult:
    if dry_run:
        return ExplorerResult(
            method="network",
            status=ExplorerSourceStatus.IMPORT_REQUIRED,
            endpoints_found=[
                ExplorerEndpointProbe(
                    endpoint_url=url,
                    status=ExplorerSourceStatus.IMPORT_REQUIRED,
                    notes=["dry_run_no_network", "explorer_endpoint_weight_40_official_docs"],
                )
            ],
            notes=[
                "dry_run_no_network",
                "Explorer prepare; active --store/without dry-run to attempt public read-only extraction.",
            ],
        ).finish()

    result = ExplorerResult(method="network", started_at_ms=now_ms())
    try:
        transactions, truncated, block_heights = await _read_explorer_stream(
            timeout_seconds=timeout_seconds,
            max_events=max_events,
        )
        result.endpoints_found.append(
            ExplorerEndpointProbe(
                endpoint_url=EXPLORER_WS_URL,
                method="WEBSOCKET",
                status=ExplorerSourceStatus.OK,
                notes=["explorerBlock_and_explorerTxs_subscribed"],
            )
        )
        if len(transactions) < max_events and block_heights:
            extra_transactions, extra_truncated = await _read_block_details(
                block_heights[:2],
                timeout_seconds=timeout_seconds,
                max_events=max_events - len(transactions),
            )
            transactions.extend(extra_transactions)
            truncated += extra_truncated
            result.endpoints_found.append(
                ExplorerEndpointProbe(
                    endpoint_url=EXPLORER_RPC_URL,
                    method="POST",
                    status=ExplorerSourceStatus.OK,
                    notes=["blockDetails_bounded_read"],
                )
            )
    except (OSError, TimeoutError, websockets.WebSocketException, httpx.HTTPError) as exc:
        result.notes.append(f"rpc_stream_failed={exc}")
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
                response = await client.get(url, headers={"user-agent": "hl-observer-read-only/0.1"})
                result.endpoints_found.append(
                    ExplorerEndpointProbe(
                        endpoint_url=str(response.url),
                        http_status=response.status_code,
                        status=ExplorerSourceStatus.OK if response.is_success else ExplorerSourceStatus.NETWORK_FAILED,
                    )
                )
                response.raise_for_status()
                transactions, truncated = parse_explorer_payload(response.text, source_url=str(response.url))
        except httpx.HTTPError as fallback_exc:
            result.status = ExplorerSourceStatus.NETWORK_FAILED
            result.error_message = str(fallback_exc)
            result.notes.append("source_failed_visible_no_wallet_invented")
            return result.finish()

    result.transactions = _dedupe_transactions(transactions)[:max_events]
    result.events_seen = len(result.transactions)
    result.full_addresses_found = len({tx.wallet_address for tx in result.transactions if tx.wallet_address})
    result.truncated_addresses_rejected = truncated
    result.candidates_created = result.full_addresses_found
    if result.full_addresses_found:
        result.status = ExplorerSourceStatus.OK
        result.notes.append("full_addresses_extracted_from_rpc_explorer_stream")
    else:
        result.status = ExplorerSourceStatus.IMPORT_REQUIRED
        result.notes.append(
            "Explorer analyse, mais aucune adresse complete exploitable n'a ete trouvee automatiquement."
        )
    return result.finish()


async def _read_explorer_stream(
    *,
    timeout_seconds: float,
    max_events: int,
) -> tuple[list[ExplorerTransaction], int, list[int]]:
    transactions: list[ExplorerTransaction] = []
    truncated = 0
    block_heights: list[int] = []
    deadline = max(2.0, min(timeout_seconds, 8.0))
    async with websockets.connect(EXPLORER_WS_URL, ping_interval=None, close_timeout=2) as ws:
        await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "explorerBlock"}}))
        await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "explorerTxs"}}))
        loop_deadline = asyncio.get_running_loop().time() + deadline
        while asyncio.get_running_loop().time() < loop_deadline and len(transactions) < max_events:
            try:
                raw_message = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            try:
                payload = json.loads(raw_message)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("channel") == "subscriptionResponse":
                continue
            if not isinstance(payload, list):
                continue
            if payload and isinstance(payload[0], dict) and "height" in payload[0] and "numTxs" in payload[0]:
                block_heights.extend(
                    int(item["height"])
                    for item in payload
                    if isinstance(item, dict) and item.get("height") is not None
                )
                continue
            parsed, rejected = parse_explorer_records(
                [item for item in payload if isinstance(item, dict)],
                source_url=EXPLORER_WS_URL,
            )
            transactions.extend(parsed)
            truncated += rejected
    return transactions, truncated, list(dict.fromkeys(block_heights))


async def _read_block_details(
    heights: list[int],
    *,
    timeout_seconds: float,
    max_events: int,
) -> tuple[list[ExplorerTransaction], int]:
    transactions: list[ExplorerTransaction] = []
    truncated = 0
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        for height in heights:
            if len(transactions) >= max_events:
                break
            response = await client.post(
                EXPLORER_RPC_URL,
                json={"type": "blockDetails", "height": height},
                headers={
                    "content-type": "application/json",
                    "user-agent": "hl-observer-read-only/0.1",
                },
            )
            response.raise_for_status()
            parsed, rejected = parse_explorer_payload(response.json(), source_url=f"{EXPLORER_RPC_URL}#blockDetails:{height}")
            transactions.extend(parsed[: max_events - len(transactions)])
            truncated += rejected
    return transactions, truncated


def _dedupe_transactions(transactions: list[ExplorerTransaction]) -> list[ExplorerTransaction]:
    deduped: list[ExplorerTransaction] = []
    seen: set[str] = set()
    for tx in transactions:
        key = tx.tx_hash or f"{tx.wallet_address}:{tx.block}:{tx.timestamp_ms}:{tx.action_type}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tx)
    return deduped
