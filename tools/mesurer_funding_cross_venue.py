"""#365 / H-137 -- MESURER l'ecart de funding entre venues, sur le MEME coin.

Un seul appel : {"type": "predictedFundings"} -- public, /info, sans wallet, sans signature.

⚠️ CE QUE CET OUTIL NE FAIT PAS : trader. **Nous ne pouvons pas trader sur Binance ni Bybit.**
Il MESURE si l'ecart existe et s'il paie 4 executions. *Mesurer un edge n'est pas le capturer.*

Aucun ordre reel. Aucune cle. Aucune signature.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for p in (str(RACINE / "src"), str(RACINE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from hl_observer.funding.funding_cross_venue import (  # noqa: E402
    COUT_4_EXECUTIONS_BPS,
    HEURES_MAX,
    evaluer_coin,
    parser_predicted_fundings,
    resume,
)
from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient  # noqa: E402

SORTIE = RACINE / "data" / "reports" / "funding_cross_venue.json"


async def _recuperer() -> object:
    async with HyperliquidInfoClient() as client:
        return await client.predicted_fundings()


def main() -> int:
    print("=" * 92)
    print("  #365 / H-137 -- FUNDING CROSS-VENUE, SUR LE **MEME COIN**")
    print("  (X-04 a tue le perp<->perp entre coins DIFFERENTS. Ici c'est le MEME actif.)")
    print("=" * 92)

    try:
        payload = asyncio.run(_recuperer())
    except Exception as exc:  # noqa: BLE001
        print("\n  ECHEC de l'appel predictedFundings : %s" % exc)
        print("  -> AUCUN chiffre invente. Etat vide honnete.")
        return 1

    par_coin = parser_predicted_fundings(payload)
    if not par_coin:
        print("\n  Reponse vide ou illisible. AUCUN chiffre invente.")
        return 1

    ecarts = [evaluer_coin(c, t) for c, t in sorted(par_coin.items())]
    ecarts.sort(key=lambda e: e.ecart_bps_h, reverse=True)
    expl = [e for e in ecarts if e.exploitable]

    venues = sorted({t.venue for ts in par_coin.values() for t in ts})
    print("\n  coins cotes            : %d" % len(par_coin))
    print("  venues vues            : %s" % ", ".join(venues))
    print("  couts modelises        : %.0f bps (4 executions, 2 venues, aucun rebate)"
          % COUT_4_EXECUTIONS_BPS)
    print("  horizon max            : %.0f h (au-dela, l'ecart d'aujourd'hui ne dit plus rien)"
          % HEURES_MAX)
    print("-" * 92)
    print("  ECARTS EXPLOITABLES    : %d / %d" % (len(expl), len(ecarts)))
    print("-" * 92)

    entete = "  %-10s %-10s %-10s %10s %10s %8s" % (
        "coin", "SHORT", "LONG", "ecart/h", "/CAPITAL", "amorti")
    print(entete)
    for e in ecarts[:25]:
        print("  %-10s %-10s %-10s %+9.4f %+9.4f %7s %s" % (
            e.coin, e.venue_qui_encaisse, e.venue_qui_paie,
            e.ecart_bps_h, e.ecart_sur_capital_bps_h,
            ("%.0fh" % e.heures_pour_amortir) if e.heures_pour_amortir else "  -",
            "EXPLOITABLE" if e.exploitable else "",
        ))

    print("\n" + "=" * 92)
    if not expl:
        print("  VERDICT : AUCUN ecart ne paie 4 executions. La piste H-137 est FERMEE aussi.")
    else:
        m = expl[0]
        apr = m.ecart_sur_capital_bps_h * 24 * 365 / 100.0
        print("  VERDICT : %d coin(s) montrent un ecart qui paierait les couts." % len(expl))
        print("            Meilleur : %s -> %+.4f bps/h sur le CAPITAL (~%.1f %% APR brut)."
              % (m.coin, m.ecart_sur_capital_bps_h, apr))
        print("")
        print("  🚨 CE QUE CE CHIFFRE N'EST PAS :")
        print("     - **NOUS NE POUVONS PAS TRADER SUR BINANCE NI BYBIT.** Aucune integration,")
        print("       et le systeme est paper-only. Mesurer un edge n'est PAS le capturer.")
        print("     - `predictedFundings` est PREDIT, pas realise. C'est une anticipation.")
        print("     - la base inter-venue n'est PAS modelisee (les deux perps peuvent diverger).")
        print("     - c'est un trade CONNU des professionnels : sa persistance MESURE son cout.")
    print("=" * 92)

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({
        "resume": resume(ecarts),
        "venues": venues,
        "ecarts": [e.as_dict() for e in ecarts],
        "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % SORTIE)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("HYPERSMART_READ_ONLY", "1")
    raise SystemExit(main())
