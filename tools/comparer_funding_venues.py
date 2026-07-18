"""Compare le funding Hyperliquid vs Binance (LECTURE SEULE) sur les coins carry, reconcilie, et
liste les carries cross-venue candidats. Tourne SOUS WINDOWS (reseau). 0 cle, 0 ordre.

  python tools/comparer_funding_venues.py [--coins HYPE,PURR,BTC] [--cout-bps 11]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hl_observer.market.venue_adapter import fetch_binance_funding  # noqa: E402
from hl_observer.market.funding_reconciliation import reconcilier  # noqa: E402
from hl_observer.market.multi_venue_funding import classer_carries_multi_venue  # noqa: E402


def _funding_hl(coin: str):
    """Funding HL en bps/h (metaAndAssetCtxs). None si indisponible. Reseau -> Windows."""
    try:
        import urllib.request
        req = urllib.request.Request("https://api.hyperliquid.xyz/info",
                                     data=json.dumps({"type": "metaAndAssetCtxs"}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8.0) as r:  # noqa: S310
            meta, ctxs = json.loads(r.read().decode("utf-8"))
        for a, c in zip(meta.get("universe", []), ctxs):
            if str(a.get("name", "")).upper() == coin.upper():
                f = c.get("funding")
                return float(f) * 10_000.0 if f is not None else None
    except Exception:
        return None
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="HYPE,PURR,BTC,ETH,SOL")
    ap.add_argument("--cout-bps", type=float, default=11.0)
    a = ap.parse_args(argv)
    coins = [c.strip().upper() for c in a.coins.split(",") if c.strip()]
    total_opps = 0
    for coin in coins:
        fundings = {"HL": _funding_hl(coin), "Binance": fetch_binance_funding(coin).funding_bps_h}
        rec = reconcilier(fundings)
        opps = classer_carries_multi_venue(coin, rec["ok"], cout_entree_bps=a.cout_bps)
        total_opps += len(opps)
        print("== %-6s == HL=%s Binance=%s | ok=%s ecartes=%s"
              % (coin, fundings["HL"], fundings["Binance"], rec["ok"], rec["ecartes"]))
        for o in opps:
            print("     ARB : long %s / short %s | capture %.3f bps/h | net %.1f bps | BE %.0f h"
                  % (o["long_venue"], o["short_venue"], o["capture_bps_h"], o["gain_net_bps"], o["break_even_h"]))
    print("\n%d opportunite(s) cross-venue au total (lecture seule, aucun ordre)." % total_opps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
