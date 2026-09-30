"""Binance capability declaration; native live collectors remain under collection/."""
VENUE = "binance"


def capacites() -> dict:
    return {
        "venue": VENUE,
        "flux": ("book", "bbo", "trades", "ticker", "funding", "oi", "mark", "index"),
        "adaptateur": "OFFLINE_READY",
        "pull_live": "REQUIRES_NETWORK",
        "historical_repair": ("trades", "aggTrades", "coarse_depth"),
        "replay_limitations": ("high_frequency_l2_transition_reconstruction_not_guaranteed",),
    }
