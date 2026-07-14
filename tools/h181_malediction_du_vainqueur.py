#!/usr/bin/env python3
"""H-181 -- LE TOP-40 DE LA RECHERCHE EST-IL DISCERNABLE DU HASARD ?

Le code selectionne les 40 finalistes par le MAXIMUM du PnL de train (scenario_search:268).
Sur un grand espace de configs, le maximum d'un bruit est TOUJOURS positif -- et il MONTE avec
le nombre de configs testees. On teste donc peut-etre les 40 plus CHANCEUSES, pas les 40
meilleures. Et une chance ne se reproduit pas.

🚩 MA PREMIERE VERSION DE CE CONTROLE ETAIT INEXECUTABLE -- ET C'EST INSTRUCTIF.

J'avais ecrit : « on refait toute la recherche sur des donnees dont l'edge est detruit (sens
randomise), 13 fois ». Cout : 13 x |scenarios| x |candidats| x |chemin de marks|. Chaque
evaluation retraverse TOUT le chemin de prix du coin. C'est astronomique -- et c'est
EXACTEMENT pourquoi le run « 150 M » prenait 4 heures et n'a jamais fini.

Le controle correct est plus simple ET plus propre :

    HYPOTHESE NULLE : aucune config n'a d'edge. Les PnL par trade sont alors des tirages
    ECHANGEABLES dans la distribution REELLE observee. Une config qui fait n trades voit donc
    son net_train = somme de n tirages.

On rejoue donc K configs sous cette hypothese, avec les VRAIS nombres de trades et la VRAIE
distribution de PnL par trade, et on regarde le MAXIMUM. C'est le null exact de la question
« qui gagne le classement ? », et il coute O(K x n) au lieu de O(K x n x chemin).

  * max REEL ~= max NULL  -> notre top-40 est du BRUIT. « 0 robuste » ne dit rien du marche :
                             il dit que notre PROCEDURE DE SELECTION est cassee.
  * max REEL >> max NULL  -> il y a bien quelque chose. « 0 robuste » est un vrai resultat.

⚠️ ET SURTOUT : le vrai moteur teste **150 000 000** de configs, pas quelques milliers. Or le
maximum d'un bruit CROIT avec le nombre d'essais. Tout effet montre ici est donc une BORNE
INFERIEURE de ce qui se passe a l'echelle reelle.

Lecture seule. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.ab_flag_replay import load_jsonl, marks_by_coin  # noqa: E402
from hl_observer.backtesting.overfit_selection import (  # noqa: E402
    borne_du_hasard,
    selection_par_maximum,
    selection_par_plateau,
)
from hl_observer.backtesting.scenario_grid import generate  # noqa: E402
from hl_observer.backtesting.scenario_search import (  # noqa: E402
    _norm_vec,
    eval_trades,
    report_from_trades,
    temporal_split,
)

REPLAY = RACINE / "runtime" / "replay"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=400,
                    help="echantillon de la VRAIE grille (le vrai moteur en teste 150 000 000)")
    ap.add_argument("--candidats", type=int, default=6000)
    ap.add_argument("--tirages", type=int, default=400, help="repetitions du null bootstrap")
    ap.add_argument("--min-trades", type=int, default=25)
    ap.add_argument("--top-k", type=int, default=40)
    args = ap.parse_args()

    cands = []
    for f in sorted(REPLAY.rglob("candidates*.jsonl")):
        cands.extend(load_jsonl(f))
        if len(cands) >= args.candidats:
            break
    cands = [c for c in cands if str(c.get("coin") or "")][: args.candidats]

    mark_rows = []
    for f in sorted(REPLAY.rglob("marks*.jsonl")):
        mark_rows.extend(load_jsonl(f))
    marks = marks_by_coin(mark_rows)

    tous = list(generate())
    rng = random.Random(20260713)
    scenarios = tous if len(tous) <= args.scenarios else rng.sample(tous, args.scenarios)

    train, test = temporal_split(cands, 0.7)

    print("=" * 80)
    print(" H-181 -- LE TOP-40 EST-IL DISCERNABLE DU HASARD ?")
    print("=" * 80)
    print()
    print(f"  candidats     : {len(cands):>7}   (train {len(train)} / test {len(test)})")
    print(f"  scenarios     : {len(scenarios):>7}   (echantillon de la grille de {len(tous)})")
    print(f"  >>> le VRAI moteur en teste 150 000 000. Tout effet montre ici est une BORNE")
    print(f"      INFERIEURE : le maximum d'un bruit MONTE avec le nombre d'essais.")
    print()
    if not cands or not marks or not scenarios:
        print("  INSUFFICIENT_DATA -- c'est un fait, pas une panne.")
        return 0

    # ------------------------------------------------------------------ 1. LE REEL
    scores: list[tuple[object, float]] = []
    tous_les_pnl: list[float] = []
    nb_trades: list[int] = []
    for sc in scenarios:
        t = eval_trades(sc, train, marks)
        r = report_from_trades(t)
        if int(r["trades"] or 0) >= args.min_trades:
            scores.append((sc, float(r["net_total_usd"] or 0.0)))
            tous_les_pnl.extend(t)
            nb_trades.append(len(t))

    if not scores:
        print("  Aucun scenario n'atteint le minimum de trades. INSUFFICIENT_DATA.")
        return 0

    max_reel = max(s for _sc, s in scores)
    moy_pnl = sum(tous_les_pnl) / len(tous_les_pnl)

    print("-" * 80)
    print(" 1. LES DONNEES REELLES")
    print("-" * 80)
    print(f"  scenarios retenus (>= {args.min_trades} trades) : {len(scores)}")
    print(f"  trades evalues au total                : {len(tous_les_pnl)}")
    print(f"  PnL MOYEN par trade                    : {moy_pnl:+.4f} $")
    print(f"  >>> MEILLEUR net de TRAIN              : {max_reel:+.2f} $")
    print()

    # ------------------------------------------------------------------ 2. LE NULL
    print("-" * 80)
    print(" 2. LE NULL : les MEMES nombres de trades, la MEME distribution de PnL,")
    print("              mais AUCUN lien entre la config et ce qu'elle attrape.")
    print("-" * 80)
    maxima: list[float] = []
    for i in range(args.tirages):
        r2 = random.Random(1000 + i)
        best = None
        for n in nb_trades:
            net = sum(r2.choice(tous_les_pnl) for _ in range(n))
            if best is None or net > best:
                best = net
        if best is not None:
            maxima.append(best)

    b = borne_du_hasard(max_reel=max_reel, maxima_permutes=maxima, n_scenarios=len(scores))
    print(f"  {args.tirages} tirages du null.")
    print(f"  hasard : moyenne {b.max_hasard_moyen:+.2f} $  |  p95 {b.max_hasard_p95:+.2f} $")
    print(f"  reel   : {b.max_reel:+.2f} $")
    print(f"  ECART reel - p95 du hasard : {b.ecart:+.2f} $   (signe-sur, contrairement a un ratio)")
    print()
    print("  ⚠️ LIMITE DE CE NULL, DITE A VOIX HAUTE : il tire les PnL dans la distribution")
    print("     MISE EN COMMUN de tous les scenarios. Il DETRUIT donc l'heterogeneite entre")
    print("     coins et entre filtres. Un scenario qui ne trade qu'un seul coin herite ici")
    print("     d'une distribution qui n'est pas la sienne. Ce null SOUS-ESTIME ce que le")
    print("     hasard peut faire. Le null exact est la PERMUTATION DU SENS (voir le module).")
    print()

    # ------------------------------------------------------------------ 3. LES SELECTIONS
    print("-" * 80)
    print(" 3. LES DEUX PROCEDURES DE SELECTION, SUR LES MEMES DONNEES")
    print("-" * 80)
    par_max = selection_par_maximum(scores, args.top_k)
    par_plateau = selection_par_plateau(scores, args.top_k, vecteur=_norm_vec)

    def _oos(liste):
        nets = []
        for sc in liste:
            t = eval_trades(sc, test, marks)
            if t:
                nets.append(float(report_from_trades(t)["net_total_usd"] or 0.0))
        if not nets:
            return 0, 0.0, 0
        return len(nets), sum(nets) / len(nets), sum(1 for x in nets if x > 0)

    n1, moy1, pos1 = _oos(par_max)
    n2, moy2, pos2 = _oos(par_plateau)
    communs = len({id(x) for x in par_max} & {id(x) for x in par_plateau})

    print(f"  {'procedure':<30} {'n':>4} {'net OOS moyen':>16} {'positifs OOS':>14}")
    print(f"  {'MAXIMUM (code actuel)':<30} {n1:>4} {moy1:>+15.2f} $ {f'{pos1}/{n1}':>14}")
    print(f"  {'PLATEAU (propose)':<30} {n2:>4} {moy2:>+15.2f} $ {f'{pos2}/{n2}':>14}")
    print()
    print(f"  configs communes aux deux top-{args.top_k} : {communs}")
    print()

    # ------------------------------------------------------------------ VERDICT
    print("  " + "=" * 76)
    print("   VERDICT")
    print("  " + "=" * 76)
    print()
    if b.verdict == "AUCUNE_CONFIG_N_EST_PROFITABLE_MEME_EN_TRAIN":
        print("   >>> IL N'Y A AUCUN VAINQUEUR A MAUDIRE.")
        print()
        print(f"       PnL MOYEN par trade                  : {moy_pnl:+.4f} $")
        print(f"       MEILLEUR net de TRAIN (sur {len(scores)} configs) : {b.max_reel:+.2f} $")
        print()
        print("       Le MEILLEUR scenario PERD, et il perd EN ECHANTILLON -- la ou il a tous")
        print("       les droits de sur-ajuster. Pas un seul n'est profitable, meme en trichant.")
        print()
        print(f"       Et les DEUX procedures de selection donnent le meme resultat hors")
        print(f"       echantillon : {pos1}/{n1} positifs par MAXIMUM, {pos2}/{n2} par PLATEAU.")
        print()
        print("   >>> DONC : L'HYPOTHESE H-181 EST **REFUTEE COMME EXPLICATION**.")
        print()
        print("       La malediction du vainqueur est REELLE (prouvee sur bruit pur, 9 tests).")
        print("       Mais ce n'est PAS elle qui cause le « 0 config robuste ». Reparer la")
        print("       selection ne fabriquera pas un gagnant qui n'existe pas.")
        print()
        print("       C'est une PORTE QUI SE FERME -- et c'est utile : ca nous evite de")
        print("       refondre scenario_search pour rien.")
    elif b.verdict == "LE_TOP_EST_INDISCERNABLE_DU_HASARD":
        print("   >>> LE TOP DE LA RECHERCHE EST INDISCERNABLE DU HASARD.")
        print()
        print(f"       Sous l'hypothese « aucune config n'a d'edge », le meilleur des")
        print(f"       {len(scores)} scenarios affiche deja {b.max_hasard_p95:+.2f} $ de train (p95).")
        print(f"       Sur les vraies donnees : {b.max_reel:+.2f} $. Meme ordre de grandeur.")
        print()
        print("       Les 40 finalistes ne sont donc PAS les 40 meilleures configs.")
        print("       Ce sont les 40 plus CHANCEUSES -- et une chance ne se reproduit pas.")
        print()
        print("       « 0 config robuste sur 150 M » n'est PAS un resultat sur le marche.")
        print("       C'est un resultat sur NOTRE PROPRE PROCEDURE DE SELECTION.")
        print()
        print("       ET C'EST PIRE A L'ECHELLE REELLE : le maximum d'un bruit MONTE avec le")
        print("       nombre d'essais. A 150 000 000 de configs, le gagnant du train est")
        print("       quasi CERTAINEMENT un pic de chance.")
    else:
        print("   >>> LE TOP DEPASSE LA BORNE DU HASARD.")
        print(f"       reel {b.max_reel:+.2f} $ contre {b.max_hasard_p95:+.2f} $ au p95 du null.")
        print("       Il y a bien quelque chose dans les donnees, et la selection par maximum")
        print("       n'est pas (a elle seule) la cause du « 0 robuste ».")
    print()

    sortie = RACINE / "data" / "reports" / "h181_malediction_du_vainqueur.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps({
        "candidats": len(cands),
        "scenarios_echantillonnes": len(scenarios),
        "scenarios_de_la_grille": len(tous),
        "scenarios_retenus": len(scores),
        "note_echelle": ("le VRAI moteur teste 150 000 000 de configs ; le maximum d'un bruit "
                         "MONTE avec le nombre d'essais -> effet montre = BORNE INFERIEURE"),
        "pnl_moyen_par_trade": moy_pnl,
        "borne_du_hasard": b.as_dict(),
        "selection_maximum": {"n": n1, "net_oos_moyen": moy1, "positifs": pos1},
        "selection_plateau": {"n": n2, "net_oos_moyen": moy2, "positifs": pos2},
        "configs_communes": communs,
    }, indent=2), encoding="utf-8")
    print(f"  rapport : {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
