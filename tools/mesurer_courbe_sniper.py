#!/usr/bin/env python3
"""LA COURBE EDGE/HORIZON, SUR LES VRAIES DONNEES -- lecture seule (2026-07-11).

Ce script prend les signaux REELLEMENT enregistres (`runtime/replay/candidates*.jsonl`), les
chemins de prix REELS (`marks*.jsonl`), et il mesure ce que le marche a fait APRES chaque signal,
dans le sens du leader.

CE QU'IL NE FAIT PAS :
  * il n'extrapole aucun horizon que la donnee ne couvre pas -> SOURCE_RESOLUTION_INSUFFICIENT ;
  * il ne soustrait AUCUNE moyenne calculee sur la periode testee (ce serait du lookahead --
    je me suis deja fait prendre a ce piege) ;
  * il ne regarde QUE les prix POSTERIEURS au signal. Jamais un seul prix d'avant.

Il ne promet aucun PnL. Il rend une courbe. Si elle est plate, on saura.

    python tools/mesurer_courbe_sniper.py
    python tools/mesurer_courbe_sniper.py runtime/replay/_archive/run_20260709_152414

LECTURE SEULE. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import bisect
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting.sniper_horizon_curve import (  # noqa: E402
    HORIZONS_MS,
    construire_courbe,
    verdict,
)
from hl_observer.strategies.engine_economics import cout_aller_retour_bps  # noqa: E402


def _lire(motif: str) -> list[dict]:
    out: list[dict] = []
    for f in sorted(glob.glob(str(ROOT / motif))):
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue      # ligne tronquee (fichier en cours d'ecriture) : on saute
        except OSError:
            continue
    return out


def _ms(v):
    """Normalise un horodatage en MILLISECONDES (les deux unites cohabitent dans les fichiers)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x <= 0:
        return None
    return x * 1000.0 if x < 1e11 else x        # < 1e11 => secondes


def main() -> int:
    dossier = sys.argv[1] if len(sys.argv) > 1 else "runtime/replay"
    print("\n  source : %s" % dossier)
    marks = _lire("%s/marks*.jsonl" % dossier)
    cands = _lire("%s/candidates*.jsonl" % dossier)
    print("  %d prix releves - %d signaux enregistres" % (len(marks), len(cands)))

    # chemins de prix par coin, tries (on ne regardera QUE l'aval de chaque signal)
    chemins = defaultdict(list)
    for m in marks:
        t = _ms(m.get("ts"))
        coin = str(m.get("coin") or "")
        if t is None or not coin:
            continue
        try:
            p = float(m.get("mid"))
        except (TypeError, ValueError):
            continue
        if p > 0:
            chemins[coin].append((t, p))
    for coin in chemins:
        chemins[coin].sort()
    print("  %d marches avec un chemin de prix" % len(chemins))

    horizon_max = max(HORIZONS_MS)
    signaux = []
    sans_prix = 0

    for c in cands:
        coin = str(c.get("coin") or "")
        side = str(c.get("direction") or c.get("side") or "")
        t0 = _ms(c.get("recorded_at"))
        try:
            prix0 = float(c.get("current_mid") or 0.0)
        except (TypeError, ValueError):
            prix0 = 0.0
        if not coin or not side or t0 is None or prix0 <= 0 or coin not in chemins:
            sans_prix += 1
            continue

        serie = chemins[coin]
        i = bisect.bisect_left(serie, (t0, float("-inf")))    # UNIQUEMENT l'aval : zero lookahead
        chemin = []
        for t, p in serie[i:]:
            d = t - t0
            if d > horizon_max:
                break
            if d >= 0:
                chemin.append((int(d), p))
        if not chemin:
            sans_prix += 1
            continue
        signaux.append({"prix_signal": prix0, "side": side, "chemin_prix": chemin})

    print("  %d signaux exploitables - %d sans chemin de prix aval\n" % (len(signaux), sans_prix))
    if not signaux:
        print("  AUCUN signal exploitable. Ce n'est PAS une preuve d'absence d'edge :")
        print("  c'est une absence de donnee. Laisse le bot collecter plus longtemps.\n")
        return 2

    courbe = construire_courbe(signaux)
    cout = cout_aller_retour_bps(spread_bps=2.0, slippage_bps=2.0)
    v = verdict(courbe, cout_aller_retour_bps=cout)

    print("  %9s %7s %10s %11s %10s  %s" % ("horizon", "n", "edge med", "ecart-type", "sig/bruit", "statut"))
    print("  %9s %7s %10s %11s %10s  %s" % ("-" * 9, "-" * 7, "-" * 10, "-" * 11, "-" * 10, "-" * 30))
    for h in sorted(courbe):
        p = courbe[h]
        med = "--" if p.edge_median_bps is None else "%+.2f" % p.edge_median_bps
        sd = "--" if p.ecart_type_bps is None else "%.2f" % p.ecart_type_bps
        rsb = "--" if p.ratio_signal_bruit is None else "%.3f" % p.ratio_signal_bruit
        etoile = " <<<" if p.exploitable else ""
        lib = ("%.2fs" % (h / 1000.0)) if h >= 1000 else ("%dms" % h)
        print("  %9s %7d %10s %11s %10s  %s%s" % (lib, p.n, med, sd, rsb, p.statut, etoile))

    print("\n  Cout aller-retour retenu : %.1f bps" % cout)
    print("  Horizons au-dessus du bruit    : %s" % (v["horizons_exploitables"] or "AUCUN"))
    print("  Horizons rentables apres couts : %s" % (v["horizons_rentables_apres_couts"] or "AUCUN"))
    print("\n  VERDICT : %s\n" % v["conclusion"])

    sortie = ROOT / "data" / "reports" / "sniper_horizon_curve.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    v["source"] = dossier
    v["n_signaux"] = len(signaux)
    sortie.write_text(json.dumps(v, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  rapport ecrit : %s\n" % sortie.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
