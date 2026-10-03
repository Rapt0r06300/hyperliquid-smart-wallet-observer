"""HTX public incremental MBP adapter with an explicit network boundary.

The adapter is deliberately offline-only: it decodes the venue's optional
GZIP frames, preserves predecessor sequence evidence and never claims a live
connection without a separate network canary.
"""
from __future__ import annotations

import gzip
import json
from collections.abc import Mapping, Sequence
from typing import Any

from ._canon import (
    OFFLINE_READY,
    REQUIRES_NETWORK,
    ClientLiveBase,
    DetecteurSequence,
    niveaux,
)

VENUE = "htx"
ENDPOINTS = {"ws": "wss://api.huobi.pro/feed"}
_PUBLIC_DEPTHS = {5, 20, 150, 400}


def decode_frame(frame: bytes | str | Mapping[str, Any]) -> Mapping[str, Any]:
    """Decode JSON or GZIP JSON and reject malformed/non-object frames."""
    if isinstance(frame, Mapping):
        return frame
    raw = frame.encode("utf-8") if isinstance(frame, str) else bytes(frame)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("HTX_FRAME_NOT_OBJECT")
    return payload


def public_subscription_plan(
    instruments: Sequence[str],
    *,
    depth: int = 150,
    max_symbols: int = 4,
) -> dict[str, Any]:
    """Build a bounded Tier-A MBP plan from documented public depths."""
    selected_depth = int(depth)
    if selected_depth not in _PUBLIC_DEPTHS:
        raise ValueError("HTX_UNSUPPORTED_DEPTH")
    limit = max(1, min(20, int(max_symbols)))
    symbols = sorted(
        {str(value).strip().upper() for value in instruments if str(value).strip()}
    )[:limit]
    return {
        "channels": [
            f"market.{symbol}.depth.size_{selected_depth}.high_freq"
            for symbol in symbols
        ],
        "authenticated": False,
        "read_only": True,
    }


def normalize_mbp(message: Mapping[str, Any]) -> dict[str, Any]:
    tick = message.get("tick")
    if not isinstance(tick, Mapping):
        raise ValueError("HTX_MISSING_TICK")
    channel = str(message.get("ch") or "")
    parts = channel.split(".")
    symbol = parts[1] if len(parts) > 2 else message.get("symbol")
    return {
        "venue": VENUE,
        "symbole": symbol,
        "type_maj": str(message.get("type") or tick.get("event") or "delta").lower(),
        "ts": message.get("ts", tick.get("ts")),
        "seq": tick.get("seqNum"),
        "prev_seq": tick.get("prevSeqNum"),
        "bids": niveaux(tick.get("bids") or ()),
        "asks": niveaux(tick.get("asks") or ()),
    }


def appliquer_flux_book(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    detector = DetecteurSequence()
    resyncs: list[dict[str, Any]] = []
    applied = 0
    for message in messages:
        book = normalize_mbp(message)
        if book["seq"] is None:
            resyncs.append({"seq": None, "raison": "sequence_absente"})
            continue
        if book["type_maj"] == "snapshot":
            detector.snapshot(book["seq"])
            applied += 1
            continue
        result = detector.delta(book["seq"], book["prev_seq"])
        if result["resync"]:
            resyncs.append({"seq": book["seq"], "raison": result["raison"]})
        else:
            applied += 1
    return {"applique": applied, "resyncs": resyncs, "synchronise": detector.synchronise}


def capacites() -> dict[str, Any]:
    return {
        "venue": VENUE,
        "flux": ("book",),
        "adaptateur": OFFLINE_READY,
        "pull_live": REQUIRES_NETWORK,
    }


class LiveClientHtx(ClientLiveBase):
    statut = REQUIRES_NETWORK

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def souscrire(self, canal: str) -> None:
        self._refuser(canal)


__all__ = [
    "LiveClientHtx",
    "appliquer_flux_book",
    "capacites",
    "decode_frame",
    "normalize_mbp",
    "public_subscription_plan",
]
