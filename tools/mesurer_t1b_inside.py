"""#587 / T1b — MESURER : coter DANS le spread change-t-il le verdict de T1 ? (2026-07-13)

Donnees REELLES en main : 7 216 snapshots de carnet L2 + 4 382 trades avec leur agresseur.

Sortie : data/reports/t1b_inside_spread.json

Aucun ordre reel : lecture de fichiers, arithmetique.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.quoting_inside_spread import (  # noqa: E402
    COUT_ALLER_RETOUR_BPS,
    MIN_SNAPSHOTS,
    MOTIF_PAS_DE_PLACE,
    Snapshot,
    Trade,
    evaluer_quoting_inside,
)

REPLAY = RACINE / "runtime" / "replay"


def charger():
    snaps: dict[str, list[Snapshot]] = defaultdict(list)
    for f in REPLAY.rglob("l2_book*.jsonl"):
        for ligne in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not ligne.strip():
                continue
            try:
                d = json.loads(ligne)
                coin = str(d.get("coin") or "")
                bid, ask, mid = float(d["bid"]), float(d["ask"]), float(d["mid"])
            except (ValueError, KeyError, TypeError):
                continue
            if not coin or not (ask > bid > 0) or mid <= 0:
                continue
            snaps[coin].append(Snapshot(ts=float(d.get("ts") or 0), coin=coin,
                                        bid=bid, ask=ask, mid=mid))

    trades: dict[str, list[Trade]] = defaultdict(list)
    for f in REPLAY.rglob("trades*.jsonl"):
        for ligne in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not ligne.strip():
                continue
            try:
                d = json.loads(ligne)
                coin = str(d.get("coin") or "")
                px = float(d["px"])
            except (ValueError, KeyError, TypeError):
                continue
            if not coin or px <= 0:
                continue
            trades[coin].append(Trade(
                ts=float(d.get("ts") or 0), coin=coin, px=px,
                notional_usd=float(d.get("notional_usd") or 0.0),
                aggressor=str(d.get("aggressor") or ""),
            ))
    return snaps, trades


def main() -> int:
    print("=" * 94)
    print("  #587 / T1b -- CO TER **DANS** LE SPREAD : la derniere porte ouverte du MM")
    print("  T1 : « aucun marche ne paie a notre place » (on est DERRIERE 2 577 $ de file).")
    print("  T1b : et si on se mettait DEVANT, en ameliorant le prix d'un tick ?")
    print("=" * 94)

    snaps, trades = charger()
    print("  carnet L2 : %d coins / %d snapshots" % (len(snaps), sum(len(v) for v in snaps.values())))
    print("  trades    : %d coins / %d trades" % (len(trades), sum(len(v) for v in trades.values())))

    exploitables = [c for c in snaps if len(snaps[c]) >= MIN_SNAPSHOTS]
    print("  coins avec >= %d snapshots : %d" % (MIN_SNAPSHOTS, len(exploitables)))
    print()

    verdicts = [evaluer_quoting_inside(c, snaps[c], trades.get(c, [])) for c in exploitables]
    verdicts.sort(key=lambda v: v.net_bps, reverse=True)

    sans_place = [v for v in verdicts if v.motif == MOTIF_PAS_DE_PLACE]
    viables = [v for v in verdicts if v.viable]

    print("-" * 94)
    print("  🔴 AUCUN INTERIEUR (spread = 1 tick) : %d / %d coins" % (len(sans_place), len(verdicts)))
    print("     -> sur ces marches, coter « dans » le spread est **arithmetiquement impossible**.")
    print("  VIABLES apres frais + selection adverse : %d" % len(viables))
    print("-" * 94)
    print()

    print("  %-9s %-6s %-8s %-8s %-8s %-9s %-8s  %s" % (
        "coin", "snaps", "spread", "capture", "adverse", "INVENT.", "NET", "motif"))
    for v in verdicts[:24]:
        print("  %-9s %-6d %-8.2f %-8.2f %-8.2f %-9.2f %-+8.2f  %s" % (
            v.coin, v.n_snapshots, v.spread_median_bps, v.capture_inside_bps,
            v.adverse_bps, v.vol_detention_bps, v.net_bps, v.motif[:30]))
    print()
    print("  INVENT. = le prix bouge de combien pendant qu'on PORTE la position (5 min).")
    print("           *Un MM ne gagne pas le spread : il gagne le spread MOINS ce mouvement.*")

    print()
    if not viables:
        print("  ═══════════════════════════════════════════════════════════════════════════")
        print("  VERDICT T1b : coter DANS le spread ne change PAS le verdict de T1.")
        print("  La porte que T1 avait laissee ouverte est FERMEE -- par la mesure, pas par")
        print("  prejuge. Le market making retail sur Hyperliquid est mort, tete de file")
        print("  comprise.")
        print("  ═══════════════════════════════════════════════════════════════════════════")
    else:
        print("  ⚠️ %d coin(s) survivent. A NE PAS SUR-INTERPRETER : %d coins testes -> le hasard"
              % (len(viables), len(verdicts)))
        print("     seul en fait ressortir quelques-uns. Controle de multiplicite exige avant")
        print("     toute conclusion (Deflated Sharpe / White's Reality Check, IDEA-22/27).")
        for v in viables:
            print("     %s : %s" % (v.coin, v.note))

    out = RACINE / "data" / "reports" / "t1b_inside_spread.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "cout_aller_retour_bps": COUT_ALLER_RETOUR_BPS,
        "n_coins": len(verdicts),
        "n_sans_interieur": len(sans_place),
        "n_viables": len(viables),
        "hypothese_remplissage": "100 % des agresseurs (la plus GENEREUSE possible)",
        "verdicts": [v.as_dict() for v in verdicts],
        "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
