"""OPS-6 — Prévol de joignabilité réseau Hyperliquid.

Vérifie que api.hyperliquid.xyz/info est joignable avant de lancer.
Paper-only, lecture seule.
"""
from __future__ import annotations

import json
import logging
import time
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

HL_INFO_URL = "https://api.hyperliquid.xyz/info"
TIMEOUT_S = 10


def check_hl_reachable(*, timeout: float = TIMEOUT_S) -> dict:
    """Teste la joignabilité de l'API HL /info. Retourne un diagnostic."""
    start = time.monotonic()
    try:
        req = Request(
            HL_INFO_URL,
            data=json.dumps({"type": "meta"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            status = resp.status
            elapsed = time.monotonic() - start
            return {
                "reachable": status == 200,
                "status": status,
                "latency_ms": round(elapsed * 1000),
                "url": HL_INFO_URL,
            }
    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.warning("HL network check failed: %s (%.1fs)", exc, elapsed)
        return {
            "reachable": False,
            "error": str(exc)[:200],
            "latency_ms": round(elapsed * 1000),
            "url": HL_INFO_URL,
        }


def assert_hl_reachable(*, timeout: float = TIMEOUT_S) -> None:
    """Lève si l'API HL n'est pas joignable."""
    result = check_hl_reachable(timeout=timeout)
    if not result["reachable"]:
        raise ConnectionError(
            f"Hyperliquid API non joignable: {result.get('error', 'HTTP ' + str(result.get('status')))}"
        )
    logger.info("HL network OK: %dms", result["latency_ms"])


__all__ = ["check_hl_reachable", "assert_hl_reachable"]
