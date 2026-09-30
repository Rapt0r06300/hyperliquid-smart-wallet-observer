"""🔴 LE BACKFILL D'HISTORIQUE — « data-limited » était une blessure auto-infligée (2026-07-13).

`candleSnapshot(coin, interval, **startTime**, endTime)` était DEJA ecrit, DEJA autorise, et on ne
s'en servait que pour les bougies RECENTES. **On peut telecharger des MOIS d'historique de prix,
gratuitement, depuis l'API qu'on interroge tous les jours.**

Sortie : runtime/history/candles_<intervalle>.jsonl  (+ data/reports/backfill_couverture.json)

    BACKFILL-CANDLES.cmd            (30 jours, 1m, sur les coins les plus liquides)

⚠️ CE QUE CA NE DEBLOQUE PAS : le carnet L2 et les trades avec agresseur. **Le verdict du market
making (T1b) ne change pas** -- il etait deja mesure a la borne la plus GENEREUSE.

Aucun ordre reel. Lecture publique seule. Aucune cle, aucune signature.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.candle_backfill import (  # noqa: E402
    couverture,
    dedupliquer,
    parser_bougies,
    plan_de_requetes,
)
from hl_observer.hyperliquid.rest_info_client import (  # noqa: E402
    build_candle_snapshot_payload,
)
from hl_observer.security.mainnet_guard import assert_info_endpoint_only  # noqa: E402

INFO = "https://api.hyperliquid.xyz/info"

# On reste POLI avec l'API : se faire bannir = MOINS de donnees, pas plus.
PAUSE_S = 0.25


def _post(payload: dict) -> object:
    # 🔴 LE GARDE RUNTIME (#254) : meme ici, on ne frappe QUE /info.
    assert_info_endpoint_only(INFO)
    req = urllib.request.Request(
        INFO, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:      # noqa: S310 - endpoint public
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill d'historique. Aucun ordre reel.")
    ap.add_argument("--jours", type=int, default=30)
    ap.add_argument("--intervalle", default="1m")
    ap.add_argument("--coins", default="BTC,ETH,SOL,HYPE,BNB,ARB,DOGE,LTC,AVAX,SUI,NEAR,OP")
    a = ap.parse_args()

    coins = [c.strip().upper() for c in a.coins.split(",") if c.strip()]
    fin = int(time.time() * 1000)
    debut = fin - a.jours * 24 * 3_600_000

    print("=" * 94)
    print("  BACKFILL D'HISTORIQUE -- « data-limited » etait une blessure AUTO-INFLIGEE")
    print("  `candleSnapshot(..., startTime, ...)` etait DEJA ecrit. On ne l'utilisait pas.")
    print("=" * 94)
    print("  %d coins x %d jours en %s" % (len(coins), a.jours, a.intervalle))

    sortie = RACINE / "runtime" / "history"
    sortie.mkdir(parents=True, exist_ok=True)
    fichier = sortie / ("candles_%s.jsonl" % a.intervalle)

    couvertures = []
    total = 0
    with fichier.open("w", encoding="utf-8") as f:
        for coin in coins:
            bougies = []
            fenetres = plan_de_requetes(debut_ms=debut, fin_ms=fin, intervalle=a.intervalle)
            for (d, fn) in fenetres:
                try:
                    rep = _post(build_candle_snapshot_payload(coin, a.intervalle, d, fn))
                except (urllib.error.URLError, ValueError, TimeoutError) as exc:
                    print("    %-6s fenetre KO : %s" % (coin, type(exc).__name__))
                    continue                     # trou honnete : on ne l'invente pas
                bougies.extend(parser_bougies(coin, rep))
                time.sleep(PAUSE_S)
            bougies = dedupliquer(bougies)
            cv = couverture(bougies, intervalle=a.intervalle)
            if cv is None:
                print("  %-6s : AUCUNE bougie (etat vide honnete)" % coin)
                continue
            for b in bougies:
                f.write(json.dumps(b.as_dict(), ensure_ascii=False) + "\n")
            total += len(bougies)
            couvertures.append(cv)
            print("  %-6s : %6d bougies | %7.1f h | trous : %d"
                  % (coin, cv.n_bougies, cv.heures, cv.n_trous))

    print()
    print("-" * 94)
    if couvertures:
        h = min(c.heures for c in couvertures)
        print("  TOTAL : %d bougies. Couverture MINIMALE : **%.0f h (%.1f jours)**"
              % (total, h, h / 24.0))
        print("  (avant ce backfill, on avait **18,9 h**.)")
        trous = sum(c.n_trous for c in couvertures)
        if trous:
            print("  ⚠️ %d bougies MANQUANTES au total. Un trou n'est pas un zero : on le DIT." % trous)
    else:
        print("  AUCUNE donnee. Etat vide honnete -- on n'invente rien.")
    print("-" * 94)
    print()
    print("  ✅ DEBLOQUE : #242 (cointegration), la recherche de scenarios (horizons de 8 h),")
    print("     le lead-lag, les regimes -- tout ce qui ne depend que du PRIX.")
    print("  ❌ NE DEBLOQUE PAS : le carnet L2 et les trades avec agresseur. **Le verdict du")
    print("     market making (T1b) NE CHANGE PAS** -- il etait deja mesure a la borne la plus")
    print("     GENEREUSE (100 %% de remplissage).")

    out = RACINE / "data" / "reports" / "backfill_couverture.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "jours": a.jours, "intervalle": a.intervalle, "n_bougies": total,
        "fichier": str(fichier),
        "couvertures": [c.as_dict() for c in couvertures],
        "ne_debloque_pas": ["carnet L2", "trades avec agresseur", "liquidations historiques"],
        "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % fichier)
    print("  -> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
