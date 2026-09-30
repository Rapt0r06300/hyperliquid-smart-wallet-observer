"""Gate.io capability declaration; live market data lives in collection.gate_market_data."""
VENUE = "gate"
def capacites() -> dict:
    return {"venue": VENUE, "flux": ("book", "trades", "ticker", "funding", "oi", "mark", "index"), "adaptateur": "OFFLINE_READY", "pull_live": "REQUIRES_NETWORK"}
