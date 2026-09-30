"""Hyperliquid capability declaration; execution remains outside this registry."""
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
