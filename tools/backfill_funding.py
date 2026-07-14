"""#606 -- Backfill du funding REALISE, par coin, depuis `fundingHistory` (endpoint PUBLIC).

X-04 (« le funding perp<->perp est mort », 120 paires) a ete mesure sur **18,9 h** de funding
enregistre en live. T2/T2b (le carry HYPE, le SEUL resultat positif du projet) aussi.
L'historique etait **public depuis toujours**. Meme maladie que `candleSnapshot(startTime)`.

⚠️ On MESURE la couverture obtenue, on ne la PROMET pas : `candleSnapshot` plafonnait a ~5 000
points quel que soit le startTime. `fundingHistory` peut plafonner aussi. On le constatera.

Lecture seule. Aucun ordre reel. Aucune cle. Aucune signature.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for p in (str(RACINE / "src"), str(RACINE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from hl_observer.collection.funding_backfill import (  # noqa: E402
    MS_PAR_HEURE,
    couverture,
    dedupliquer,
    funding_cumule_bps,
    parser_funding,
    plan_de_requetes,
)
from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient  # noqa: E402

COINS = ["BTC", "ETH", "SOL", "BNB", "AVAX", "ARB", "DOGE", "LTC", "SUI", "OP", "HYPE", "NEAR"]
SORTIE = RACINE / "runtime" / "history" / "funding.jsonl"


async def _un_coin(client: HyperliquidInfoClient, coin: str, jours: int) -> list:
    fin = int(time.time() * 1000)
    debut = fin - jours * 24 * MS_PAR_HEURE
    points: list = []
    for a, b in plan_de_requetes(debut_ms=debut, fin_ms=fin):
        try:
            payload = await client.funding_history(coin, start_time=a, end_time=b)
        except Exception as exc:  # noqa: BLE001
            print("    %s [%d..%d] : ECHEC (%s) -- fenetre ignoree, PAS inventee" % (coin, a, b, exc))
            continue
        points.extend(parser_funding(coin, payload))
        await asyncio.sleep(0.12)          # poli avec la source : se faire bannir = MOINS de donnees
    return dedupliquer(points)


async def _run(jours: int) -> int:
    print("=" * 92)
    print("  #606 -- BACKFILL DU FUNDING REALISE (endpoint PUBLIC `fundingHistory`)")
    print("  X-04 et T2 ont ete juges sur 18,9 h. On demande %d jours." % jours)
    print("=" * 92)

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    lignes: list[str] = []
    resume: list[dict] = []

    async with HyperliquidInfoClient() as client:
        for coin in COINS:
            pts = await _un_coin(client, coin, jours)
            c = couverture(pts, coin=coin)
            if c is None:
                print("  %-6s : AUCUNE serie exploitable -- etat vide honnete (rien invente)" % coin)
                continue
            cum = funding_cumule_bps(pts)
            print("  %-6s : %5d points | %7.1f j | %3d trous | funding cumule %+9.1f bps "
                  "(%+.2f bps/h moyen)"
                  % (coin, c.n_points, c.jours, c.n_trous, cum,
                     cum / max(1, c.n_points)))
            lignes.extend(json.dumps(p.as_dict()) for p in pts)
            resume.append(c.as_dict() | {"funding_cumule_bps": round(cum, 2)})
            total += c.n_points

    SORTIE.write_text("\n".join(lignes) + ("\n" if lignes else ""), encoding="utf-8")

    print("-" * 92)
    if not resume:
        print("  AUCUNE donnee. Etat vide honnete.")
        return 1
    jmax = max(r["jours"] for r in resume)
    jmin = min(r["jours"] for r in resume)
    trous = sum(r["n_trous"] for r in resume)
    print("  TOTAL : %d points, %d coins" % (total, len(resume)))
    print("  COUVERTURE REELLE : de %.1f a %.1f jours | %d trous au total" % (jmin, jmax, trous))
    print("  (avant : **18,9 h**. Facteur ~%.0fx)" % (jmax * 24 / 18.9))
    print("  -> %s" % SORTIE)
    print("=" * 92)
    print("  ⚠️ Refaire une mesure n'est PAS esperer un resultat. X-04 sera probablement")
    print("     CONFIRME sur des mois. Mais il sera enfin mesure sur de la vraie donnee.")
    (RACINE / "data" / "reports").mkdir(parents=True, exist_ok=True)
    (RACINE / "data" / "reports" / "funding_backfill.json").write_text(
        json.dumps({"coins": resume, "real_execution": False}, indent=2), encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jours", type=int, default=120)
    a = ap.parse_args()
    return asyncio.run(_run(max(1, a.jours)))


if __name__ == "__main__":
    raise SystemExit(main())
