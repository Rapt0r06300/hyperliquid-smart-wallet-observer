"""#242 / IDEA-85 — MESURER la cointegration sur NOS donnees reelles (2026-07-13).

On a 102 907 relevés de mid sur 1 011 coins (`runtime/replay/**/marks*.jsonl`).
La question n'est pas « la cointegration existe-t-elle en theorie ? » (oui, c'est un fait connu),
mais : **une paire de perps Hyperliquid rapporte-t-elle, hors echantillon, APRES les couts des
DEUX jambes ?**

Sortie : data/reports/cointegration_242.json + cointegration.txt

Aucun ordre reel : lecture de fichiers, arithmetique, rien d'autre.
"""
from __future__ import annotations

import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.cointegration_measure import (  # noqa: E402
    MIN_POINTS_COMMUNS,
    apparier,
    evaluer_paire,
    resampler,
)
from hl_observer.collection.candle_backfill import MINUTES_PAR_INTERVALLE  # noqa: E402

PAS_S = 60.0
TOP_COINS = 14          # les paires croissent en n^2 : 14 coins = 91 paires. Assez, et honnete.


def charger_marks() -> dict[str, list[tuple[float, float]]]:
    """Les marks du LIVE : 18,9 h. C'est ce qui a fait mourir #242 « data-limited »."""
    par_coin: dict[str, list[tuple[float, float]]] = defaultdict(list)
    fichiers = list((RACINE / "runtime" / "replay").rglob("marks*.jsonl"))
    for f in fichiers:
        try:
            for ligne in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not ligne.strip():
                    continue
                try:
                    d = json.loads(ligne)
                except ValueError:
                    continue
                coin = str(d.get("coin") or "").strip()
                ts = d.get("ts")
                mid = d.get("mid")
                if not coin or ts is None or mid is None:
                    continue                      # 🚩 le bug `coin=''` du 08/07 : on JETTE.
                par_coin[coin].append((float(ts), float(mid)))
        except OSError:
            continue
    print("  MARKS live : %d fichiers, %d coins" % (len(fichiers), len(par_coin)))
    return par_coin


def charger_bougies(intervalle: str) -> dict[str, list[tuple[float, float]]]:
    """🔴 L'HISTORIQUE BACKFILLE : jusqu'a **208 JOURS** (contre 18,9 h de marks live).

    `candleSnapshot(..., startTime, ...)` etait DEJA ecrit et DEJA autorise. On ne l'utilisait
    que pour les bougies RECENTES. **« Data-limited » etait une blessure auto-infligee.**
    """
    f = RACINE / "runtime" / "history" / ("candles_%s.jsonl" % intervalle)
    par_coin: dict[str, list[tuple[float, float]]] = defaultdict(list)
    if not f.exists():
        print("  ⚠️ %s absent -- lance BACKFILL-PROFOND.cmd. (etat vide honnete)" % f.name)
        return par_coin
    for ligne in f.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not ligne.strip():
            continue
        try:
            d = json.loads(ligne)
            coin = str(d["coin"])
            ts = float(d["t_ms"]) / 1000.0
            c = float(d["c"])                     # on ferme sur le CLOSE : pas de lookahead
        except (ValueError, KeyError, TypeError):
            continue
        if not coin or c <= 0:
            continue
        par_coin[coin].append((ts, c))
    print("  BOUGIES %s : %d coins, %d points"
          % (intervalle, len(par_coin), sum(len(v) for v in par_coin.values())))
    return par_coin


def main() -> int:
    import sys as _sys

    # --source bougies:1h  -> 208 JOURS.   --source marks -> 18,9 h (l'ancien « data-limited »).
    src = "bougies:1h"
    for a in _sys.argv[1:]:
        if a.startswith("--source="):
            src = a.split("=", 1)[1]

    print("=" * 92)
    print("  #242 / IDEA-85 -- COINTEGRATION, MESUREE SUR DONNEES REELLES")
    print("  (ce n'est PAS Johansen : c'est Engle-Granger. Et le code etait MORT.)")
    print("  source : %s" % src)
    print("=" * 92)

    if src.startswith("bougies:"):
        intervalle = src.split(":", 1)[1]
        brut = charger_bougies(intervalle)
        pas = float(MINUTES_PAR_INTERVALLE[intervalle]) * 60.0
    else:
        brut = charger_marks()
        pas = PAS_S

    grilles = {c: resampler(p, pas_s=pas) for c, p in brut.items()}
    assez = {c: g for c, g in grilles.items() if len(g) >= MIN_POINTS_COMMUNS}
    print("  %d coins ont >= %d buckets de %ds" % (len(assez), MIN_POINTS_COMMUNS, int(pas)))

    if len(assez) < 2:
        print("\n  INSUFFICIENT_DATA : moins de 2 coins exploitables. On ne conclut PAS.")
        return 0

    tops = sorted(assez, key=lambda c: len(assez[c]), reverse=True)[:TOP_COINS]
    print("  coins retenus (%d) : %s" % (len(tops), ", ".join(tops)))

    resultats = []
    for a, b in itertools.combinations(tops, 2):
        xa, yb = apparier(assez[a], assez[b])
        r = evaluer_paire(a, b, xa, yb)
        resultats.append(r)

    testables = [r for r in resultats if r.motif != "INSUFFICIENT_DATA"]
    cointegres = [r for r in testables if r.cointegre]
    tradees = [r for r in cointegres if r.n_trades > 0]
    viables = [r for r in tradees if r.viable]

    print()
    print("-" * 92)
    print("  paires evaluees          : %d" % len(resultats))
    print("  assez de points communs  : %d" % len(testables))
    print("  COINTEGREES (ADF 5 %%)    : %d" % len(cointegres))
    print("  ... qui ont trade en OOS : %d" % len(tradees))
    print("  ... VIABLES apres couts  : %d" % len(viables))
    print("-" * 92)

    if tradees:
        print("\n  Les paires cointegrees qui ont trade (edge NET apres 4 executions) :")
        for r in sorted(tradees, key=lambda r: r.edge_net_bps, reverse=True)[:12]:
            print("   %-6s/%-6s  n=%-6d ADF=%-7.2f trades=%-4d brut=%+8.2f  NET=%+8.2f bps  %s"
                  % (r.a, r.b, r.n_communs, r.adf, r.n_trades, r.edge_brut_bps, r.edge_net_bps,
                     "VIABLE" if r.viable else ""))

    print()
    if not cointegres:
        print("  VERDICT : aucune paire cointegree. Le pairs trading sur ces perps serait un")
        print("            pari directionnel deguise. *Pas d'edge a chercher ici.*")
    elif not viables:
        print("  VERDICT : des paires SONT cointegrees, mais AUCUNE ne survit aux couts.")
        print("            C'est le meme mur que partout : le mecanisme existe, l'edge NET non.")
    else:
        print("  VERDICT : %d paire(s) survivent aux couts hors echantillon." % len(viables))
        print("            ⚠️ A NE PAS SUR-INTERPRETER : %d paires testees -> le hasard seul en"
              % len(testables))
        print("            fait ressortir quelques-unes. Il faudra un controle de multiplicite")
        print("            (Deflated Sharpe / White's Reality Check -- deja codes, IDEA-22/27).")

    out = RACINE / "data" / "reports" / "cointegration_242.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "pas_s": PAS_S,
        "coins_retenus": tops,
        "n_paires": len(resultats),
        "n_testables": len(testables),
        "n_cointegrees": len(cointegres),
        "n_tradees": len(tradees),
        "n_viables": len(viables),
        "paires": [r.as_dict() for r in resultats],
        "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
