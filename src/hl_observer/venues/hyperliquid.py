"""Hyperliquid capability declaration; execution remains outside this registry."""
from __future__ import annotations

from collections.abc import Mapping

VENUE = "hyperliquid"


def capacites() -> dict:
    return {
        "venue": VENUE,
        "flux": ("book", "bbo", "trades", "user_fills", "funding", "oi", "mark", "index"),
        "adaptateur": "OFFLINE_READY",
        "pull_live": "REQUIRES_NETWORK",
        "historical_repair": ("live_reconnect_snapshot",),
        "replay_limitations": ("requester_pays_l2_archive_not_zero_cost",),
        "execution_surface": "READ_ONLY_ONLY",
    }


def venue_capability_safety_receipt(result: object) -> dict[str, object]:
    """Validate the native venue declaration without enabling network execution."""
    required_flux = {"book", "bbo", "trades", "user_fills", "funding", "oi", "mark", "index"}
    valid = (
        isinstance(result, Mapping)
        and result.get("venue") == VENUE
        and required_flux.issubset(set(result.get("flux", ())))
        and result.get("adaptateur") == "OFFLINE_READY"
        and result.get("pull_live") == "REQUIRES_NETWORK"
        and result.get("execution_surface") == "READ_ONLY_ONLY"
        and "orders" not in set(result.get("flux", ()))
    )
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "verdict": "HYPERLIQUID_CAPABILITY_SAFE" if valid else "HYPERLIQUID_CAPABILITY_UNSAFE",
        "paper_read_only": True,
        "real_execution": False,
        "network_execution": False,
        "execution_surface": "READ_ONLY_ONLY",
        "fail_closed": not valid,
    }
