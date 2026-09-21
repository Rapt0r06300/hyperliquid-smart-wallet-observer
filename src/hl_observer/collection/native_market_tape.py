"""Normalize native public venue frames into the existing replayable tick dataset.

Raw exchange payloads are preserved without the internal transport metadata injected
by Alina. Quality promotion is deliberately separate: these envelopes are evidence,
not an automatic claim that the surrounding window is SAFE.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hl_observer.collection.tick_dataset import TickEnvelope


def native_tick_envelope(
    venue: str,
    payload: Mapping[str, Any],
) -> TickEnvelope | None:
    venue_key = str(venue or "").strip().lower()
    message = dict(payload)
    transport_raw = message.pop("_alina_transport", None)
    transport = dict(transport_raw) if isinstance(transport_raw, Mapping) else {}

    receive_ts_ms = _int(transport.get("receive_wall_ts_ms"))
    if receive_ts_ms is None:
        return None
    receive_mono_ns = _int(transport.get("receive_mono_ns"))
    connection_id = str(transport.get("connection_id") or "") or None

    if venue_key == "bybit":
        parsed = _bybit_identity(message)
    elif venue_key == "okx":
        parsed = _okx_identity(message)
    else:
        return None
    if parsed is None:
        return None

    channel, instrument, exchange_ts_ms, sequence, summary = parsed
    summary = {
        **summary,
        "transport_rtt_ms": _float(transport.get("transport_rtt_ms")),
        "clock_offset_ms": _float(transport.get("clock_offset_ms")),
        "clock_probe_rtt_ms": _float(transport.get("clock_probe_rtt_ms")),
        # Raw frames are not promoted here. Window QC + reconciliation owns SAFE.
        "data_gate_ready": False,
    }
    return TickEnvelope(
        source_id=f"{venue_key}_public_ws",
        channel=channel,
        instrument=instrument,
        event_kind="UPDATE",
        raw_payload=message,
        received_ts_ms=receive_ts_ms,
        exchange_ts_ms=exchange_ts_ms,
        local_monotonic_ns=receive_mono_ns,
        connection_id=connection_id,
        sequence=sequence,
        provenance={
            "access": "read_only",
            "network": "mainnet",
            "venue": venue_key,
            "transport": "websocket",
            "authenticated": False,
            "real_execution": False,
        },
        parsed_summary=summary,
    )


def _bybit_identity(
    payload: Mapping[str, Any],
) -> tuple[str, str, int | None, int | None, dict[str, Any]] | None:
    topic = str(payload.get("topic") or "")
    data = payload.get("data")
    rows = data if isinstance(data, list) else [data] if isinstance(data, Mapping) else []
    first = rows[0] if rows and isinstance(rows[0], Mapping) else {}
    instrument = str(first.get("s") or first.get("symbol") or _topic_symbol(topic)).upper()
    if not instrument:
        return None

    if topic.startswith("orderbook."):
        channel = "l2Book"
        exchange_ts = _int(payload.get("cts")) or _int(first.get("cts")) or _int(payload.get("ts"))
        sequence = _int(first.get("seq"))
        summary = {
            "update_id": _int(first.get("u")),
            "cross_sequence": sequence,
            "message_type": str(payload.get("type") or ""),
            "depth_topic": topic.split(".")[1] if len(topic.split(".")) > 2 else None,
        }
    elif topic.startswith("publicTrade."):
        channel = "trades"
        exchange_ts = _max_int(row.get("T") for row in rows if isinstance(row, Mapping))
        sequence = _max_int(row.get("seq") for row in rows if isinstance(row, Mapping))
        summary = {
            "event_count": len(rows),
            "system_ts_ms": _int(payload.get("ts")),
            "trade_ids_present": sum(
                1 for row in rows if isinstance(row, Mapping) and row.get("i")
            ),
        }
    elif topic.startswith("allLiquidation."):
        channel = "liquidations"
        exchange_ts = _max_int(row.get("T") for row in rows if isinstance(row, Mapping))
        sequence = None
        summary = {
            "event_count": len(rows),
            "system_ts_ms": _int(payload.get("ts")),
        }
    elif topic.startswith("tickers."):
        channel = "ticker"
        exchange_ts = _int(payload.get("ts"))
        sequence = _int(payload.get("cs"))
        summary = {"message_type": str(payload.get("type") or "")}
    else:
        return None
    return channel, instrument, exchange_ts, sequence, summary


def _okx_identity(
    payload: Mapping[str, Any],
) -> tuple[str, str, int | None, int | None, dict[str, Any]] | None:
    arg = payload.get("arg")
    if not isinstance(arg, Mapping):
        return None
    channel_raw = str(arg.get("channel") or "")
    instrument = str(arg.get("instId") or "").upper()
    data = payload.get("data")
    rows = data if isinstance(data, list) else []
    first = rows[0] if rows and isinstance(rows[0], Mapping) else {}
    instrument = str(first.get("instId") or instrument).upper()
    if not channel_raw or not instrument or not rows:
        return None

    channel_map = {
        "books": "l2Book",
        "books5": "l2Book",
        "bbo-tbt": "bbo",
        "trades": "trades",
        "tickers": "ticker",
        "funding-rate": "funding",
        "open-interest": "open_interest",
        "mark-price": "mark_price",
    }
    channel = channel_map.get(channel_raw)
    if channel is None:
        return None
    exchange_ts = _max_int(
        row.get("ts") for row in rows if isinstance(row, Mapping)
    )
    sequence = _int(first.get("seqId"))
    summary = {
        "event_count": len(rows),
        "source_channel": channel_raw,
        "action": str(payload.get("action") or ""),
        "prev_sequence": _int(first.get("prevSeqId")),
    }
    return channel, instrument, exchange_ts, sequence, summary


def _topic_symbol(topic: str) -> str:
    return topic.rsplit(".", 1)[-1] if "." in topic else ""


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _max_int(values: Any) -> int | None:
    parsed = [item for item in (_int(value) for value in values) if item is not None]
    return max(parsed) if parsed else None


__all__ = ["native_tick_envelope"]
