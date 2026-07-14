"""FALSIFIER CASHCAT (2026-07-12) -- les deux mesures qui peuvent tuer le seul candidat.

CASHCAT sort a net +7,7 bps [+6,1 ; +10,0], plafond 373 $/h. C'est le PREMIER resultat positif
du projet. Raison de plus pour essayer de le detruire avant d'y croire.

Deux attaques, toutes deux calculables sur la donnee DEJA captee :

  ATTAQUE 1 -- LA FILE EST-ELLE ATTEIGNABLE ?
    La borne DERRIERE dit "les 25 % de trades les plus gros nous atteignent". C'est un PROXY,
    pas de la physique. La physique dit : un maker au fond de la file au meilleur prix n'est
    rempli QUE si un trade balaye toute la profondeur posee devant lui.
    CASHCAT : profondeur au touch ~2 300 $. Seuil du top-25 % : ~174 $.
    Si presque aucun trade n'atteint 2 300 $, alors un retail au fond de la file **n'est
    JAMAIS rempli** -- et les 373 $/h sont un plafond sur un evenement qui n'arrive pas.

  ATTAQUE 2 -- LE MARKOUT A 30 s EST-IL LE BON HORIZON ?
    Un maker ne se debarrasse pas de son inventaire en 30 s : il le porte jusqu'au fill oppose.
    Si l'adverse enfle avec l'horizon, la capture de 17,8 bps se fait manger. On mesure donc a
    10 s / 30 s / 60 s / 120 s / 300 s / 600 s. La forme de la courbe repond, pas moi.

Lecture seule. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting.market_making_flow import (  # noqa: E402
    COUT_ALLER_RETOUR_BPS,
    _pertes_maker,
    ic_bootstrap_mediane,
    selection_par_rang,
)

HORIZONS_MS = (10_000, 30_000, 60_000, 120_000, 300_000, 600_000)


def _trades(coin: str) -> list[dict]:
    out = []
    for f in sorted(ROOT.glob("runtime/replay/trades*.jsonl")):
        with open(f, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    t = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if t.get("coin") == coin and not t.get("snapshot"):
                    out.append(t)
    return out


def _carnet(coin: str) -> list[dict]:
    out = []
    for f in sorted(ROOT.glob("runtime/replay/l2_book*.jsonl")):
        with open(f, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("coin") == coin and r.get("spread_bps") is not None:
                    out.append(r)
    return out


def attaque_1_file_atteignable(coin: str, trades: list[dict], carnet: list[dict]) -> None:
    print("=" * 78)
    print(" ATTAQUE 1 -- LA FILE EST-ELLE PHYSIQUEMENT ATTEIGNABLE ?")
    print("=" * 78)
    if not carnet:
        print("  pas de carnet pour %s -> INSUFFICIENT_DATA, on ne tranche pas." % coin)
        return

    bid = statistics.median([float(r.get("bid_depth_usd") or 0.0) for r in carnet])
    ask = statistics.median([float(r.get("ask_depth_usd") or 0.0) for r in carnet])
    print("  profondeur mediane au meilleur prix : bid %.0f $ | ask %.0f $  (%d releves)"
          % (bid, ask, len(carnet)))

    notionnels = sorted(float(t.get("notional_usd") or 0.0) for t in trades)
    if not notionnels:
        print("  aucun trade -> rien a dire.")
        return
    n = len(notionnels)
    print("  trades : %d | median %.0f $ | p75 %.0f $ | p95 %.0f $ | p99 %.0f $ | max %.0f $"
          % (n, notionnels[n // 2], notionnels[int(n * .75)], notionnels[int(n * .95)],
             notionnels[int(n * .99)], notionnels[-1]))

    print()
    print("  QUELLE FRACTION DU FLUX BALAYE LA FILE JUSQU'A NOUS ?")
    for nom, file_usd in (("fond de file (100 % de la profondeur devant nous)", (bid + ask) / 2),
                          ("milieu de file (50 %)", (bid + ask) / 4),
                          ("tete de file (10 %)", (bid + ask) / 20)):
        atteignent = [x for x in notionnels if x >= file_usd]
        part = 100.0 * len(atteignent) / n
        vol = sum(atteignent)
        print("    %-46s file %8.0f $ -> %5d trades (%5.2f %%), %9.0f $ de flux"
              % (nom, file_usd, len(atteignent), part, vol))

    fond = (bid + ask) / 2
    atteignent = [x for x in notionnels if x >= fond]
    print()
    if not atteignent:
        print("  >>> VERDICT : AUCUN trade ne balaye la file. Un maker au fond du carnet")
        print("      n'aurait ete rempli AUCUNE fois. Le plafond de 373 $/h porte sur un")
        print("      evenement qui N'ARRIVE PAS. Le candidat est MORT a cette place.")
    elif 100.0 * len(atteignent) / n < 1.0:
        print("  >>> VERDICT : %.2f %% des trades seulement balayent la file. Le PLAFOND"
              % (100.0 * len(atteignent) / n))
        print("      realiste s'effondre. A verifier en dollars ci-dessus.")
    else:
        print("  >>> VERDICT : la file est atteignable pour une part non triviale du flux.")


def attaque_2_courbe_horizon(coin: str, trades: list[dict], spread_bps: float) -> None:
    print()
    print("=" * 78)
    print(" ATTAQUE 2 -- L'ADVERSE ENFLE-T-IL AVEC L'HORIZON ?")
    print("=" * 78)
    capture = spread_bps * 0.5
    print("  capture (demi-spread) %.2f bps | frais aller-retour %.1f bps" % (capture, COUT_ALLER_RETOUR_BPS))
    print()
    print("  %-9s %7s  %9s  %-20s %9s" % ("horizon", "n_fills", "adverse", "IC 90 % adverse", "net"))
    for h in HORIZONS_MS:
        pertes = _pertes_maker(trades, horizon_ms=h)
        if len(pertes) < 30:
            print("  %-9s %7d  %9s  %-20s %9s"
                  % ("%.0f s" % (h / 1000), len(pertes), "--", "NON MESURABLE", "--"))
            continue
        retenus, _ = selection_par_rang(pertes, 0.75)          # borne REALISTE
        if len(retenus) < 30:
            print("  %-9s %7d  %9s  %-20s %9s"
                  % ("%.0f s" % (h / 1000), len(retenus), "--", "ECHANTILLON TROP MINCE", "--"))
            continue
        adv, bas, haut = ic_bootstrap_mediane([p for p, _ in retenus])
        net = capture - COUT_ALLER_RETOUR_BPS - adv
        print("  %-9s %7d  %+8.2f  [%+6.2f ; %+6.2f]   %+8.2f"
              % ("%.0f s" % (h / 1000), len(retenus), adv, bas, haut, net))

    print()
    print("  LECTURE : si l'adverse GRANDIT avec l'horizon et depasse %.1f bps" % (capture - COUT_ALLER_RETOUR_BPS))
    print("  (= capture - frais), alors un maker qui porte son inventaire plus de 30 s PERD.")
    print("  L'edge a 30 s serait alors un artefact d'horizon, pas un edge.")


def main() -> None:
    coin = (sys.argv[1] if len(sys.argv) > 1 else "CASHCAT").upper()
    trades = _trades(coin)
    carnet = _carnet(coin)
    print()
    print("FALSIFICATION DE %s -- %d trades LIVE, %d releves de carnet" % (coin, len(trades), len(carnet)))
    print()
    if len(trades) < 100:
        print("  moins de 100 trades : INSUFFICIENT_DATA. On ne tranche pas.")
        return

    attaque_1_file_atteignable(coin, trades, carnet)

    spread = statistics.median([float(r["spread_bps"]) for r in carnet]) if carnet else float("nan")
    if spread != spread:                                        # NaN
        print("\n  pas de spread mesure -> ATTAQUE 2 impossible.")
        return
    attaque_2_courbe_horizon(coin, trades, spread)


if __name__ == "__main__":
    main()
