"""Bitget capability declaration; live market data lives in collection.bitget_market_data."""
VENUE = "bitget"
def capacites() -> dict:
    return {"venue": VENUE, "flux": ("book", "trades", "ticker", "funding", "oi", "mark", "index"), "adaptateur": "OFFLINE_READY", "pull_live": "REQUIRES_NETWORK"}
