"""Socle bas niveau du compagnon de checkpoints Copy-Vault.

POURQUOI CE MODULE EST À PART (17/11/2026). Ces primitives vivaient dans
``copy_vault_checkpoint_tail.py``. Les réparations du 16/11 (fenêtres de trous, liaison du carnet
pré-signal) l'avaient porté de 739 à 968 lignes pour un plafond de 800, et l'invariant
``test_pas_de_nouveau_fichier_geant`` rougissait à juste titre. Plutôt que de relever le plafond,
ce qui ne dépend d'AUCUN état du compagnon est extrait ici : lecture stricte d'entiers et
d'horodatages, écriture d'une ligne durable, identité de fichier, et le carnet L2 public
(requête + validation).

Rien ne change de comportement : le compagnon réimporte chaque nom tel quel. Aucun ordre, aucune
signature, aucune clé : la seule destination réseau est l'endpoint public ``/info``.
"""
from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.instrument_identity import preserve_native_instrument_symbol
from hl_observer.normalization.l2_book import normalize_l2_levels

INFO_URL = "https://api.hyperliquid.xyz/info"
MAX_TARGET_LAG_MS = 30_000


def _strict_int(value: Any, field: str) -> int:
    if type(value) is bool or value is None:
        raise ValueError(f"{field} missing or boolean")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field} must be integral")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field} invalid") from None


def _exact_positive_timestamp(value: Any, field: str) -> int:
    """Require an observed positive integer timestamp with no coercion."""
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def fetch_hyperliquid_l2_book(coin: str, *, timeout_s: float = 2.0) -> dict[str, Any] | None:
    """Fetch one public read-only Hyperliquid L2 book.

    The only network destination is the official ``/info`` endpoint.  No
    credential, signature or write payload exists in this module.
    """

    body = json.dumps({"type": "l2Book", "coin": preserve_native_instrument_symbol(coin)}).encode("utf-8")
    request = urllib.request.Request(
        INFO_URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "HyperSmart/read-only"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(0.2, float(timeout_s))) as response:
            if int(response.status) != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _file_identity(stat: os.stat_result) -> list[int]:
    """Stable identity for replacement detection; size/mtime change on append."""

    return [int(stat.st_dev), int(stat.st_ino)]


def _parse_book(raw: Mapping[str, Any], *, received_at_ms: int) -> dict[str, Any] | None:
    try:
        exchange_ts_ms = _exact_positive_timestamp(raw["time"], "time")
        received_at_ms = _exact_positive_timestamp(received_at_ms, "received_at_ms")
        raw_bids, raw_asks = raw["levels"][0], raw["levels"][1]
        bids = normalize_l2_levels(
            [[row["px"], row["sz"]] for row in raw_bids], side="bid"
        )
        asks = normalize_l2_levels(
            [[row["px"], row["sz"]] for row in raw_asks], side="ask"
        )
        if bids is not None:
            bids = bids[:5]
        if asks is not None:
            asks = asks[:5]
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        return None
    if (
        exchange_ts_ms <= 0
        or received_at_ms < exchange_ts_ms
        or received_at_ms - exchange_ts_ms > MAX_TARGET_LAG_MS
        or not bids
        or not asks
        or any(px <= 0 or size <= 0 for px, size in bids + asks)
        or bids[0][0] >= asks[0][0]
    ):
        return None
    capacity_usd = min(
        sum(px * size for px, size in bids),
        sum(px * size for px, size in asks),
    )
    if capacity_usd <= 0:
        return None
    return {
        "exchange_ts_ms": exchange_ts_ms,
        "bid": bids[0][0],
        "ask": asks[0][0],
        "bids5": bids,
        "asks5": asks,
        "capacity_usd": capacity_usd,
    }


__all__ = [
    "INFO_URL", "MAX_TARGET_LAG_MS", "fetch_hyperliquid_l2_book",
    "_append_jsonl", "_exact_positive_timestamp", "_file_identity", "_parse_book", "_strict_int",
]
