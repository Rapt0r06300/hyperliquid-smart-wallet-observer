#!/usr/bin/env python3
"""MESURE le slippage reel d'un ordre au marche, et la PERSISTE.

POURQUOI. J'ai suppose 2 bps de slippage pendant toute la session, et la mesure a donne **4,36 bps
en moyenne** (3,16 median) sur 60 000 instantanes de carnet. Cette erreur d'un facteur 2 enlevait
4,7 bps par detention, soit 15 % du net. Tant qu'un chiffre reste une CONSTANTE EN DUR, il ne se
corrige jamais tout seul : cet outil le mesure et l'ecrit, pour que `mesurer_strategie.py` le lise
au lieu de le supposer.

CE QU'ELLE A APPRIS. Le slippage bouge a peine avec la taille (3,10 b a 50 USD contre 3,70 b a
500 USD) : **ce n'est donc PAS un probleme de profondeur, c'est le DEMI-SPREAD** d'un univers de
187 coins dont des alts peu liquides. C'est ce diagnostic qui a rendu l'entree passive interessante
— un ordre passif n'encaisse pas des frais moindres, il ne PAIE PAS le spread.

CE QU'ELLE REFUSE. Un carnet trop mince sur les 5 niveaux publies est **ECARTE**, jamais compte
comme un slippage nul : un carnet insuffisant n'est pas un carnet parfait, et le confondre
flatterait exactement les coins les plus dangereux.

PAPER / lecture seule.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CARNETS = Path("runtime") / "coffre_certifie" / "local" / "shards" / "book_l2"
SORTIE = Path("runtime") / "data" / "slippage_mesure.json"
NOTIONNELS = (50.0, 100.0, 200.0, 500.0)
#: Le notionnel de reference : la taille d'une jambe au dimensionnement courant.
NOTIONNEL_REFERENCE = 100.0


def cout_au_marche(niveaux, notionnel: float, mid: float) -> float | None:
    """Ecart au mid, en bps, du prix moyen pondere d'un ordre au marche.

    `None` si les niveaux publies ne portent pas la taille demandee : un carnet trop mince est une
    ABSENCE de mesure, pas un slippage nul.
    """
    reste, qte = float(notionnel), 0.0
    for n in niveaux or ():
        try:
            px, sz = float(n[0]), float(n[1])
        except (TypeError, ValueError, IndexError):
            continue
        if px <= 0 or sz <= 0:
            continue
        pris = min(reste, px * sz)
        qte += pris / px
        reste -= pris
        if reste <= 1e-9:
            break
    if reste > 1e-9 or qte <= 0 or mid <= 0:
        return None
    return abs(notionnel / qte - mid) / mid * 10_000.0


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--shards", type=int, default=8)
    p.add_argument("--max-carnets", type=int, default=60_000)
    p.add_argument("--ecrire", action="store_true", help="persister le resultat")
    args = p.parse_args(argv)
    root = Path(args.root)

    dossier = root / CARNETS
    if not dossier.is_dir():
        print(f"[slippage] carnets absents : {dossier}")
        return 2
    par_notionnel: dict[float, list[float]] = defaultdict(list)
    ecartes: dict[float, int] = defaultdict(int)
    lus = 0
    for fichier in sorted(dossier.glob("*.jsonl.gz"))[-int(args.shards):]:
        try:
            with gzip.open(fichier, "rt", encoding="utf-8", errors="replace") as flux:
                for ligne in flux:
                    if not ligne.strip().startswith("{"):
                        continue
                    try:
                        o = json.loads(ligne)
                    except ValueError:
                        continue
                    b, a = o.get("bids5"), o.get("asks5")
                    if not (isinstance(b, list) and isinstance(a, list) and b and a):
                        continue
                    try:
                        mid = (float(b[0][0]) + float(a[0][0])) / 2.0
                    except (TypeError, ValueError, IndexError):
                        continue
                    if mid <= 0:
                        continue
                    lus += 1
                    for N in NOTIONNELS:
                        for cote in (b, a):
                            c = cout_au_marche(cote, N, mid)
                            if c is None:
                                ecartes[N] += 1
                            elif c < 1000:
                                par_notionnel[N].append(c)
                    if lus >= int(args.max_carnets):
                        break
        except OSError:
            continue
        if lus >= int(args.max_carnets):
            break

    if not par_notionnel.get(NOTIONNEL_REFERENCE):
        print("[slippage] aucun cas mesurable.")
        return 1
    print(f"{lus} instantanes de carnet lus")
    print(f"{'notionnel':>10}{'n':>9}{'ecartes':>9}{'median':>10}{'moyen':>9}{'p90':>9}{'p99':>9}")
    print("-" * 66)
    resume = {}
    for N in NOTIONNELS:
        v = sorted(par_notionnel[N])
        if not v:
            continue
        q = lambda part: v[min(len(v) - 1, int(len(v) * part))]
        resume[str(N)] = {"n": len(v), "ecartes": ecartes[N],
                          "median_bps": statistics.median(v), "moyen_bps": statistics.fmean(v),
                          "p90_bps": q(0.90), "p99_bps": q(0.99)}
        print(f"{N:>9.0f}U{len(v):>9}{ecartes[N]:>9}{statistics.median(v):>9.3f}b"
              f"{statistics.fmean(v):>8.3f}b{q(0.90):>8.3f}b{q(0.99):>8.3f}b")
    ref = resume[str(NOTIONNEL_REFERENCE)]
    print()
    print(f"  retenu pour le modele de cout : **{ref['moyen_bps']:.2f} bps** "
          f"(moyenne a {NOTIONNEL_REFERENCE:.0f} USD)")
    print("  la MOYENNE, pas la mediane : c'est l'esperance qui entre dans un PnL, et la queue")
    print(f"  compte (p99 = {ref['p99_bps']:.1f} b).")
    if args.ecrire:
        chemin = root / SORTIE
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(
            {"_schema": "hypersmart.slippage_mesure.v1",
             "notionnel_reference_usd": NOTIONNEL_REFERENCE,
             "slippage_moyen_bps": ref["moyen_bps"], "slippage_median_bps": ref["median_bps"],
             "n": ref["n"], "carnets_lus": lus, "par_notionnel": resume},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  ecrit dans {SORTIE}")
    else:
        print("  (ajouter --ecrire pour persister et que mesurer_strategie.py le lise)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
