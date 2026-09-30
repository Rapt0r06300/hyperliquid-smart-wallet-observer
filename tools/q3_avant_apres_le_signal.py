#!/usr/bin/env python3
"""Q3 -- POURQUOI LE FILL D'UN LEADER N'A AUCUN EDGE. La cause MECANIQUE, mesuree.

Trois preuves independantes disent deja que le copy-trading ne paie pas (OOS 11/07 : -7,97 bps
meme a cout ZERO ; courbe edge/horizon PLATE ; table mesuree Q1 : 0 cellule survit). Mais aucune
ne dit **POURQUOI**. Et sans le pourquoi, on continue a esperer qu'un reglage sauve la mise.

L'hypothese mecanique : **quand le fill devient public, l'information est DEJA dans le prix.**

Elle se teste. On mesure le markout des DEUX cotes du signal :

    mid(T-300s) ... mid(T-60s) ... mid(T) ... mid(T+60s) ... mid(T+300s)
    <------- AVANT le signal ------>|<------- APRES le signal ------->

  * Si le prix a DEJA bouge dans le sens du trade AVANT T, alors le leader a bouge le marche
    (ou l'a suivi), et l'info est consommee. Le signal arrive apres la bataille.
    -> Aucune latence, aucun scoring, aucun filtre ne peut recuperer ca. C'est STRUCTUREL.

  * Si le prix est PLAT avant T et plat apres, alors le fill du leader ne porte simplement
    aucune information. Ce n'est pas qu'on arrive trop tard -- c'est qu'il n'y a rien.

Les deux verdicts ferment la meme porte, mais pour des raisons OPPOSEES. Il faut savoir laquelle,
parce qu'elles n'impliquent PAS les memes suites :
  - « trop tard »  -> chercher le flux AVANT execution (mempool, depots, liquidations annoncees).
  - « rien a voir » -> le leader n'est pas informe ; chercher un flux FORCE, pas un flux 'malin'.

Lecture seule. Aucun ordre, aucune cle, aucune signature.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.edge.measured_edge_table import markout_bps, sens_du_trade  # noqa: E402

REPLAY = RACINE / "runtime" / "replay"

# de T-300s a T+300s. Les negatifs sont le coeur de Q3.
HORIZONS_S = [-300.0, -120.0, -60.0, -30.0, -10.0, -5.0,
              5.0, 10.0, 30.0, 60.0, 120.0, 300.0]

COUT_ALLER_RETOUR_BPS = 12.0


def _lignes(f: Path):
    try:
        with f.open("r", encoding="utf-8", errors="ignore") as fh:
            for ligne in fh:
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    yield json.loads(ligne)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def charger_marks() -> dict[str, tuple[list[float], list[float]]]:
    brut: dict[str, list[tuple[float, float]]] = {}
    if not REPLAY.is_dir():
        return {}
    for f in sorted(REPLAY.rglob("marks*.jsonl")):
        for d in _lignes(f):
            coin = str(d.get("coin") or "").upper()
            ts, mid = d.get("ts"), d.get("mid")
            if not coin or ts is None or mid is None:
                continue
            try:
                brut.setdefault(coin, []).append((float(ts), float(mid)))
            except (TypeError, ValueError):
                continue
    return {c: ([p[0] for p in sorted(v)], [p[1] for p in sorted(v)]) for c, v in brut.items()}


def mid_proche(marks, coin: str, t: float, *, tolerance_s: float) -> float | None:
    """Le mark le PLUS PROCHE de `t` (avant OU apres), dans la tolerance. Jamais d'extrapolation.

    Pour les horizons NEGATIFS on cherche un prix PASSE : prendre le plus proche est correct,
    et ne peut pas creer de lookahead (on regarde le passe du signal, pas son futur).
    """
    serie = marks.get(coin.upper())
    if not serie:
        return None
    ts, mids = serie
    i = bisect.bisect_left(ts, t)
    cands = []
    if i < len(ts):
        cands.append((abs(ts[i] - t), mids[i]))
    if i > 0:
        cands.append((abs(ts[i - 1] - t), mids[i - 1]))
    if not cands:
        return None
    d, m = min(cands)
    return m if d <= tolerance_s else None


def _moy(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _ecart_type(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = _moy(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def _borne_basse(xs, z=1.96):
    n = len(xs)
    if n < 2:
        return float("-inf")
    return _moy(xs) - z * (_ecart_type(xs) / math.sqrt(n))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tolerance-s", type=float, default=30.0,
                    help="tolerance UNIFORME (le meme filtre a tous les horizons)")
    ap.parse_args()
    args = ap.parse_args()
    TOL = float(args.tolerance_s)

    marks = charger_marks()
    if not marks:
        print("Aucun marks*.jsonl. INSUFFICIENT_DATA -- c'est un fait, pas une panne.")
        return 0

    par_h: dict[float, list[float]] = {h: [] for h in HORIZONS_S}
    lus = 0
    retenus = 0
    incomplets = 0

    for f in sorted(REPLAY.rglob("candidates*.jsonl")):
        for d in _lignes(f):
            lus += 1
            coin = str(d.get("coin") or "").strip().upper()
            if not coin:
                continue                       # bug coin='' d'avant le 11/07
            direction = d.get("direction") or d.get("action_type")
            if sens_du_trade(direction) == 0:
                continue
            mid0 = d.get("current_mid") or d.get("leader_reference_price")
            ts = d.get("recorded_at")
            if not mid0 or ts is None:
                continue
            try:
                t0, m0 = float(ts), float(mid0)
            except (TypeError, ValueError):
                continue
            if m0 <= 0:
                continue

            # 🚩 PANEL STRICT. Mon 1er passage utilisait une tolerance PROPORTIONNELLE a
            # l'horizon (max(15, |h|/2)) : les horizons lointains acceptaient donc BEAUCOUP
            # plus de signaux (48 000 a +/-300 s contre 23 000 a +/-5 s). Comparer la courbe
            # entre horizons revenait alors a comparer des POPULATIONS DIFFERENTES -- et toute
            # « forme » de la courbe pouvait n'etre qu'un effet de composition.
            #
            # Ici : tolerance UNIFORME, et on ne garde un signal que si les DOUZE horizons se
            # resolvent. Les memes signaux partout. La courbe devient comparable a elle-meme.
            valeurs: dict[float, float] = {}
            complet = True
            for h in HORIZONS_S:
                m = mid_proche(marks, coin, t0 + h, tolerance_s=TOL)
                if m is None:
                    complet = False
                    break
                if h < 0:
                    # AVANT : mouvement DE T+h VERS T, dans le sens du trade.
                    mk = markout_bps(mid_entree=m, mid_futur=m0, direction=direction)
                else:
                    mk = markout_bps(mid_entree=m0, mid_futur=m, direction=direction)
                if mk is None or not math.isfinite(mk):
                    complet = False
                    break
                valeurs[h] = mk
            if not complet:
                incomplets += 1
                continue
            for h, mk in valeurs.items():
                par_h[h].append(mk)
            retenus += 1

    print("=" * 80)
    print(" Q3 -- LE PRIX AVAIT-IL DEJA BOUGE AVANT QUE LE FILL SOIT PUBLIC ?")
    print("=" * 80)
    print()
    print(f"  signaux lus              : {lus:>8}")
    print(f"  ecartes (panel incomplet): {incomplets:>8}")
    print(f"  >>> PANEL STRICT         : {retenus:>8}  (LES MEMES signaux aux 12 horizons)")
    print(f"      tolerance uniforme   : {TOL:>8.0f} s")
    print()
    print("  AVANT le signal : mouvement du prix DE T+h VERS T, dans le sens du trade.")
    print("                    Positif = le prix avait DEJA couru. L'info etait consommee.")
    print("  APRES le signal : ce qu'on aurait encaisse en entrant a T.")
    print()
    print("-" * 80)
    print(f"  {'horizon':>10} {'n':>7} {'markout moy':>13} {'borne basse':>13} {'net -12bps':>12}")
    print("-" * 80)

    for h in HORIZONS_S:
        xs = par_h[h]
        if len(xs) < 2:
            print(f"  {h:>+9.0f}s {len(xs):>7}        (trop peu)")
            continue
        m = _moy(xs)
        bb = _borne_basse(xs)
        net = m - COUT_ALLER_RETOUR_BPS
        etoile = "  <-- AVANT" if h < 0 else ""
        bb_s = "-inf" if bb == float("-inf") else f"{bb:+.2f}"
        net_s = "" if h < 0 else f"{net:+11.2f}"
        print(f"  {h:>+9.0f}s {len(xs):>7} {m:>+12.2f} {bb_s:>13} {net_s:>12}{etoile}")

    print("-" * 80)
    print()

    # ------------------------------------------------------------------ VERDICT
    avant = [h for h in HORIZONS_S if h < 0 and len(par_h[h]) >= 2]
    apres = [h for h in HORIZONS_S if h > 0 and len(par_h[h]) >= 2]
    if not avant or not apres:
        print("  INSUFFICIENT_DATA pour trancher.")
        return 0

    course_avant = _moy(par_h[min(avant)])            # l'horizon le plus lointain AVANT
    course_60 = _moy(par_h[-60.0]) if par_h.get(-60.0) else 0.0
    gain_apres = _moy(par_h[60.0]) if par_h.get(60.0) else 0.0

    print("  " + "=" * 76)
    print("   VERDICT")
    print("  " + "=" * 76)
    print()
    print(f"   Dans les 60 s AVANT le fill  : le prix a deja fait {course_60:+.2f} bps")
    print(f"                                   dans le sens du trade.")
    print(f"   Dans les 60 s APRES le fill  : il fait {gain_apres:+.2f} bps.")
    print()

    if course_60 > 2.0 and course_60 > abs(gain_apres) * 2.0:
        print("   >>> L'INFORMATION EST DEJA DANS LE PRIX QUAND LE FILL DEVIENT PUBLIC.")
        print("       Le leader a bouge le marche (ou l'a suivi) AVANT qu'on le voie. Ce qui")
        print("       reste apres est du bruit -- et il coute 12 bps a capturer.")
        print()
        print("       CONSEQUENCE DURE : aucune latence, aucun scoring, aucun filtre de wallet")
        print("       ne peut recuperer un mouvement DEJA FAIT. Ce n'est pas un probleme de")
        print("       vitesse. C'est un probleme de CAUSALITE.")
        print()
        print("       La seule porte : capter le flux AVANT son execution (depots, mempool),")
        print("       ou un flux qui n'a pas besoin d'etre devine (liquidations, funding).")
    elif abs(course_60) <= 2.0 and abs(gain_apres) <= 2.0:
        print("   >>> LE FILL DU LEADER NE PORTE AUCUNE INFORMATION -- NI AVANT, NI APRES.")
        print("       Le prix ne bouge pas autour de ses trades. Ce n'est pas qu'on arrive")
        print("       trop tard : c'est qu'il n'y avait rien a attraper.")
        print()
        print("       CONSEQUENCE : ces wallets ne sont pas 'informes'. Les suivre PLUS VITE")
        print("       ne changerait rien -- on copierait plus vite quelque chose de vide.")
        print()
        print("       La seule porte : un flux qui bouge le prix MECANIQUEMENT (liquidations")
        print("       forcees, prelevement de funding, oracle qui suit les CEX), pas un flux")
        print("       qu'on espere 'malin'.")
    else:
        print("   >>> Signal mixte. A regarder de pres avant de conclure.")
    print()

    sortie = RACINE / "data" / "reports" / "q3_avant_apres.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps({
        "panel_strict": True,
        "tolerance_uniforme_s": TOL,
        "signaux_mesures": retenus,
        "cout_aller_retour_bps": COUT_ALLER_RETOUR_BPS,
        "courbe": {
            str(h): {
                "n": len(par_h[h]),
                "markout_moyen_bps": _moy(par_h[h]),
                "borne_basse_bps": (None if _borne_basse(par_h[h]) == float("-inf")
                                    else _borne_basse(par_h[h])),
            } for h in HORIZONS_S if par_h[h]
        },
        "course_avant_60s_bps": course_60,
        "gain_apres_60s_bps": gain_apres,
    }, indent=2), encoding="utf-8")
    print(f"  rapport : {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
