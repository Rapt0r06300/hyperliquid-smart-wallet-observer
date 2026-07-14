"""DIAGNOSTIC JETABLE (2026-07-12) -- pourquoi DEVANT et DERRIERE rendent le MEME chiffre ?

Ce script n'est pas un module de production : il imprime les entrailles de la mesure sur un
flux synthetique. Il repond a UNE question : la borne DERRIERE selectionne-t-elle vraiment
les gros trades, et la selection adverse mesuree correspond-elle a l'impact injecte ?

Lecture seule. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import random
import statistics

from hl_observer.backtesting.market_making_flow import (
    BORNES_FILE,
    HORIZON_ADVERSE_MS,
    _pertes_maker,
    _quantile,
    serie_de_mids,
)

T0 = 1_800_000_000.0


def flux(n=1600, derive=0.3, toxiques=True, spread=20.0, graine=7, espacement=60.0):
    rng = random.Random(graine)
    mid = 100.0
    demi = spread / 2 / 1e4
    out = []
    for i in range(n):
        ag = "BUY" if rng.random() < 0.5 else "SELL"
        gros = (i % 4 == 0)
        notion = 5000.0 if gros else 200.0
        d = derive * (3.0 if (toxiques and gros) else 1.0)
        s = 1.0 if ag == "BUY" else -1.0
        out.append({"coin": "T", "ts": T0 + i * espacement, "px": mid * (1 + s * demi),
                    "sz": 1.0, "aggressor": ag, "notional_usd": notion, "snapshot": False})
        mid *= (1 + s * d / 1e4)
    return out


def main() -> None:
    tr = flux()
    print("horizon adverse : %d ms | espacement des trades : 60 s" % HORIZON_ADVERSE_MS)
    print("trades %d | mids estimes %d" % (len(tr), len(serie_de_mids(tr))))

    p = _pertes_maker(tr)
    print("pertes mesurees : %d" % len(p))

    notionnels = [n for _, _, n in p]
    gros = sum(1 for n in notionnels if n > 1000)
    print("  dont gros (5000$) : %d | petits (200$) : %d" % (gros, len(notionnels) - gros))

    print("\n--- les 3 bornes ---")
    for nom, q, _ in BORNES_FILE:
        seuil = _quantile(notionnels, q)
        ret = [x for x, _, n in p if n >= seuil]
        med = statistics.median(ret) if ret else float("nan")
        distinct = sorted({round(v, 4) for v in ret})
        print("%-9s q=%.2f seuil=%8.1f$  n=%4d  adverse_median=%+.4f bps  valeurs distinctes=%d"
              % (nom, q, seuil, len(ret), med, len(distinct)))
        print("            5 plus frequentes : %s" % (
            sorted(((ret.count(v), v) for v in distinct[:40]), reverse=True)[:5],))

    print("\n--- ce qu'on INJECTE ---")
    print("  impact d'un PETIT trade : 0.30 bps   -> un maker devrait perdre 0.30")
    print("  impact d'un GROS trade  : 0.90 bps   -> un maker devrait perdre 0.90")
    print("  si la mesure rend la MOITIE, l'estimateur de mid dilue l'impact.")


if __name__ == "__main__":
    main()
