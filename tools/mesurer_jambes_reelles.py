"""Q2 -- MESURE SUR LES VRAIS CARNETS ENREGISTRES.

🚩 CE QUE J'AI DECOUVERT EN OUVRANT LE FICHIER (au lieu de le supposer)

`runtime/replay/l2_book*.jsonl` ne contient PAS les niveaux du carnet. Il contient un RESUME :

    {"ts":..., "coin":"BTC", "bid":63906.0, "ask":63907.0, "mid":..., "micro_price":...,
     "spread_bps":0.156, "bid_depth_usd":1764977.7, "ask_depth_usd":543801.9,
     "imbalance":0.53, "bid_size":13.6, "ask_size":7.4}

Le walk-the-book EST fait en direct (`parse_l2book()` recoit bien les niveaux du WS), mais
**l'enregistrement ne les garde pas**. Consequence : on ne pourra JAMAIS ré-auditer apres coup
le slippage d'une entree passee, ni rejouer une decision de carnet. C'est un trou de collecte
-- il est note dans le rapport, il n'est pas comble ici.

Ce qu'on PEUT mesurer avec ce qui est reellement enregistre, et qui suffit pour Q2 :

  1. LE MENSONGE DU MID  = `spread_bps / 2`, par jambe. Exact, pas estime.
  2. LA PROFONDEUR       = `ask_depth_usd` : le carnet peut-il absorber 500 $ ?
                            (c'est exactement le cas ou l'ancien code EXTRAPOLAIT)
  3. LE COUT DU TOP      = `ask_size * ask` : le premier niveau suffit-il a lui seul ?
                            Si oui, le slippage est NUL et le repli constant (6 bps) est
                            PESSIMISTE -- ce qui est le bon sens de l'erreur.

Lecture seule. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))


def _mediane(xs: list[float]) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    n = len(ys)
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2.0


def _pctl(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    i = min(len(ys) - 1, max(0, int(round(p / 100.0 * (len(ys) - 1)))))
    return ys[i]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notional", type=float, default=500.0)
    args = ap.parse_args()
    N = float(args.notional)

    fichiers = sorted(RACINE.glob("runtime/replay/l2_book*.jsonl"))
    fichiers += sorted(RACINE.glob("runtime/replay/_archive/**/l2_book*.jsonl"))
    if not fichiers:
        print("Aucun l2_book*.jsonl. INSUFFICIENT_DATA -- c'est un fait, pas une panne.")
        return 0

    total = 0
    illisibles = 0
    a_des_niveaux = 0
    demi_spreads: list[float] = []
    par_coin: dict[str, dict] = {}
    trop_minces = 0            # ask_depth_usd < N  -> l'ancien code EXTRAPOLAIT
    top_suffit = 0             # ask_size * ask >= N -> slippage NUL, un seul niveau suffit

    for f in fichiers:
        try:
            with f.open("r", encoding="utf-8", errors="replace") as fh:
                for ligne in fh:
                    ligne = ligne.strip()
                    if not ligne:
                        continue
                    try:
                        o = json.loads(ligne)
                    except Exception:
                        illisibles += 1
                        continue
                    if isinstance(o.get("levels"), list) or isinstance(o.get("bids"), list):
                        a_des_niveaux += 1

                    coin = str(o.get("coin") or "").strip().upper()
                    try:
                        bid = float(o.get("bid") or 0.0)
                        ask = float(o.get("ask") or 0.0)
                        spr = float(o.get("spread_bps") or 0.0)
                        prof_ask = float(o.get("ask_depth_usd") or 0.0)
                        taille_ask = float(o.get("ask_size") or 0.0)
                    except (TypeError, ValueError):
                        illisibles += 1
                        continue
                    if not coin or bid <= 0 or ask <= 0 or ask < bid:
                        illisibles += 1
                        continue

                    total += 1
                    demi = spr / 2.0
                    demi_spreads.append(demi)

                    c = par_coin.setdefault(coin, {"n": 0, "minces": 0, "demi": [], "prof": []})
                    c["n"] += 1
                    c["demi"].append(demi)
                    c["prof"].append(prof_ask)

                    if prof_ask < N:
                        trop_minces += 1
                        c["minces"] += 1
                    if taille_ask * ask >= N:
                        top_suffit += 1
        except OSError:
            continue

    if total == 0:
        print("Carnets illisibles. INSUFFICIENT_DATA.")
        return 0

    print("=" * 78)
    print(f" Q2 -- LES JAMBES REELLES  (notionnel {N:.0f} $, {len(fichiers)} fichier(s))")
    print("=" * 78)
    print()
    print(f"  snapshots lus            : {total:>8}")
    print(f"  illisibles               : {illisibles:>8}")
    print(f"  snapshots AVEC niveaux   : {a_des_niveaux:>8}   <-- 0 = le trou de collecte")
    print()

    print("-" * 78)
    print(" 1. DE COMBIEN LE MID MENT-IL ?  (= demi-spread, PAR JAMBE. Exact, pas estime.)")
    print("-" * 78)
    med = _mediane(demi_spreads)
    print(f"  demi-spread median : {med:>8.3f} bps")
    print(f"  demi-spread p75    : {_pctl(demi_spreads, 75):>8.3f} bps")
    print(f"  demi-spread p95    : {_pctl(demi_spreads, 95):>8.3f} bps")
    print(f"  demi-spread p99    : {_pctl(demi_spreads, 99):>8.3f} bps")
    print()
    print("  Un arbitrage cross-venue a DEUX jambes -> le mid surestime l'edge de la SOMME des")
    print(f"  deux demi-spreads : ~{2*med:.2f} bps au median, ~{2*_pctl(demi_spreads,95):.2f} bps au p95.")
    print("  A comparer au seuil du detecteur : min_spread_bps = 20 bps (defaut).")
    if 2 * _pctl(demi_spreads, 95) < 20.0:
        print()
        print("  >>> Sur des marches LIQUIDES, le mensonge du mid reste sous le seuil : le vieux")
        print("      detecteur ne fabriquait donc pas d'opportunites en masse ICI. Mais le meme")
        print("      code, sur un marche a 60 bps de spread (il en existe : voir tableau 3),")
        print("      aurait invente 60 bps d'edge a partir de rien.")
    print()

    print("-" * 78)
    print(f" 2. LA PROFONDEUR : le carnet peut-il absorber {N:.0f} $ a l'achat ?")
    print("-" * 78)
    pct = 100.0 * trop_minces / total
    print(f"  carnets TROP MINCES        : {trop_minces:>7}  ({pct:.2f} %)")
    print(f"  top-of-book suffit a lui seul : {top_suffit:>7}  ({100.0*top_suffit/total:.2f} %)")
    print()
    if trop_minces == 0:
        print("  >>> ZERO. A 500 $, nos carnets sont toujours assez profonds. Le bug")
        print("      d'extrapolation EXISTAIT, mais il ne se declenchait pas a ce notionnel.")
        print("      Le correctif est donc une PROTECTION (marche neuf, illiquide, ou taille")
        print("      plus grande), pas une correction de chiffres deja produits.")
        print("      C'est la reponse HONNETE : le bug etait reel, son impact passe est nul.")
    else:
        print(f"  >>> {trop_minces} cas ou l'ancien code rendait un cout EXTRAPOLE -- donc faux,")
        print("      et faux dans le sens optimiste. Ces entrees-la etaient validees a tort.")
    if top_suffit == total:
        print()
        print("  Le premier niveau suffit TOUJOURS -> le slippage reel a 500 $ est NUL.")
        print("  Le repli par constante (HYPERSMART_FUSION_COPY_SLIPPAGE_BPS = 6 bps) est donc")
        print("  PLUS PESSIMISTE que la realite. C'est le bon sens de l'erreur : un repli doit")
        print("  couter, jamais offrir.")
    print()

    print("-" * 78)
    print(" 3. LES MARCHES OU LE MID MENTIRAIT LE PLUS (demi-spread median le plus large)")
    print("-" * 78)
    lignes = [(_mediane(c["demi"]), coin, c["n"], _mediane(c["prof"]), c["minces"])
              for coin, c in par_coin.items() if c["n"] >= 3]
    lignes.sort(reverse=True)
    print(f"  {'marche':<12} {'n':>5} {'demi-spr':>10} {'mid ment de':>13} {'prof.med $':>13} {'minces':>7}")
    for demi, coin, n, prof, minces in lignes[:12]:
        print(f"  {coin:<12} {n:>5} {demi:>9.2f}b {2*demi:>12.2f}b {prof:>13,.0f} {minces:>7}")
    print()
    print(f"  ({len(par_coin)} marches vus au total)")
    print()

    rapport = RACINE / "data" / "reports" / "q2_jambes_reelles.json"
    rapport.parent.mkdir(parents=True, exist_ok=True)
    rapport.write_text(json.dumps({
        "notional_usd": N,
        "snapshots": total,
        "snapshots_avec_niveaux": a_des_niveaux,
        "TROU_DE_COLLECTE": "l2_book.jsonl n'enregistre PAS les niveaux : slippage non re-auditable",
        "demi_spread_median_bps": med,
        "demi_spread_p95_bps": _pctl(demi_spreads, 95),
        "surestimation_du_mid_2_jambes_median_bps": 2 * med,
        "surestimation_du_mid_2_jambes_p95_bps": 2 * _pctl(demi_spreads, 95),
        "carnets_trop_minces": trop_minces,
        "pct_trop_minces": pct,
        "top_of_book_suffit_pct": 100.0 * top_suffit / total,
        "marches": len(par_coin),
    }, indent=2), encoding="utf-8")
    print(f"  rapport : {rapport}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
