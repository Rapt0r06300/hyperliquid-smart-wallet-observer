r"""La couverture des carnets est-elle STABLE ? Les creux tuent les episodes, pas l etroitesse.

POURQUOI CET OUTIL (22/11/2026). Le labo rejette 1 613 candidats TRAIN sur 1 613, dont 1 045
faute de carnet a l instant de SORTIE. Trois hypotheses ont ete testees sur le ruban reel :

```
« des coins trades sans carnet »        -> REFUTE : les 156 coins sans carnet sont exactement
                                           ceux que le produit EXCLUT par choix (HIP-3/RWA/spot)
« max_l2book_coins_per_scan = 15 bride » -> REFUTE : les lanes sont shardees, 72 coins/minute
                                           en mediane
« la couverture est VARIABLE »           -> CONFIRME :
     coins par minute : min 2 | median 72 | p90 182 | max 217
     minutes sous la moitie du median : 42,6 %
     creux : 6 episodes, duree mediane 32 min, MAX 80 min
```

**Le plus long horizon cherche par le labo est de 60 minutes.** Un creux de 80 minutes avale
donc un episode ENTIER, entree et sortie comprises. Le carnet de sortie manque parce que le coin
n etait pas collecte a cette minute-la.

A QUOI CA SERT, CONCRETEMENT. Pendant une collecte, cet outil dit en une passe si ce qui est
collecte sera EXPLOITABLE -- au lieu de le decouvrir des jours plus tard quand le labo rejette
tout. Collecter plus longtemps avec les memes creux ne change rien : les episodes meurent au
meme endroit.

CE QU IL NE FAIT PAS. Il ne mesure pas la qualite d un carnet, ni la causalite, ni l execution.
Il mesure UNE chose : combien de coins distincts ont un carnet, minute par minute, et combien de
temps durent les creux. Une couverture stable ne garantit pas un verdict ; une couverture
trouee l interdit.

⚠️ IDENTITE NATIVE DES COINS. On ne met JAMAIS un coin en majuscules : `candle_backfill.py:157`
l avertit -- « kPEPE » ou « xyz:XYZ100 » deviendraient des marches inexistants. Faute commise
dans la premiere version de cette mesure.

LECTURE SEULE, bornee en octets. PAPER.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import statistics
import sys

RACINE = pathlib.Path(__file__).resolve().parents[1]

#: Le plus long horizon de detention explore par le labo. Un creux plus long que lui peut
#: avaler un episode entier -- c est le seuil qui compte, et il n est pas arbitraire.
HORIZON_MAX_LABO_MIN = 60

RUBANS = (
    "runtime/data/copy_vault_l2_tape.jsonl",
    "runtime/labo_tranches_20261121/workspace/runtime/data/copy_vault_l2_tape.jsonl",
)
BUDGET_OCTETS = 300 * 1024 * 1024


def trouver(racine: pathlib.Path) -> pathlib.Path | None:
    for relatif in RUBANS:
        chemin = racine / relatif
        if chemin.is_file() and chemin.stat().st_size > 0:
            return chemin
    return None


def couverture_par_minute(chemin: pathlib.Path, *, budget: int = BUDGET_OCTETS) -> dict[int, set]:
    """Par minute UTC : l ensemble des coins distincts ayant au moins un carnet."""
    par_minute: dict[int, set] = collections.defaultdict(set)
    octets = 0
    with chemin.open(encoding="utf-8", errors="replace") as flux:
        for ligne in flux:
            octets += len(ligne)
            if octets > budget:
                break
            try:
                objet = json.loads(ligne)
            except ValueError:
                continue
            if not isinstance(objet, dict):
                continue
            coin = objet.get("coin")
            instant = objet.get("received_at_ms") or objet.get("ts_ms")
            if isinstance(coin, str) and coin and isinstance(instant, int):
                par_minute[instant // 60_000].add(coin)      # identite NATIVE, jamais .upper()
    return dict(par_minute)


def creux(tailles: list[int], *, fraction: float = 0.5) -> list[int]:
    """Les durees, en minutes, des passages sous `fraction` de la mediane."""
    if not tailles:
        return []
    seuil = statistics.median(tailles) * fraction
    durees: list[int] = []
    courant = 0
    for taille in tailles:
        if taille < seuil:
            courant += 1
        elif courant:
            durees.append(courant)
            courant = 0
    if courant:
        durees.append(courant)
    return durees


def mesurer(par_minute: dict[int, set], *, horizon_min: int = HORIZON_MAX_LABO_MIN) -> dict:
    if not par_minute:
        return {"verdict": "RIEN_A_MESURER",
                "pourquoi": "aucune minute lisible : ce n'est pas une couverture nulle, "
                            "c'est une absence de mesure"}
    tailles = [len(par_minute[k]) for k in sorted(par_minute)]
    n = len(tailles)
    triees = sorted(tailles)
    med = statistics.median(tailles)
    durees = creux(tailles)
    trop_longs = [d for d in durees if d > horizon_min]
    return {
        "minutes_observees": n,
        "coins_par_minute": {
            "min": triees[0], "median": med,
            "p90": triees[int(n * 0.9)] if n else None, "max": triees[-1],
        },
        "minutes_sous_la_moitie_du_median": sum(1 for t in tailles if t < med / 2),
        "part_sous_la_moitie_pct": round(100.0 * sum(1 for t in tailles if t < med / 2) / n, 1),
        "creux": {
            "nombre": len(durees),
            "duree_mediane_min": round(statistics.median(durees), 1) if durees else 0,
            "duree_max_min": max(durees) if durees else 0,
            "plus_longs_que_l_horizon": len(trop_longs),
        },
        "horizon_max_labo_min": horizon_min,
        "verdict": ("CREUX_PLUS_LONG_QUE_L_HORIZON" if trop_longs
                    else "INSTABLE" if durees and max(durees) > horizon_min / 4
                    else "STABLE"),
        "ce_que_ca_ne_prouve_pas": (
            "qu'un verdict economique sortira : une couverture stable ne le garantit pas, "
            "une couverture trouee l'interdit"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--horizon-min", type=int, default=HORIZON_MAX_LABO_MIN)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    racine = pathlib.Path(args.racine)
    chemin = trouver(racine)
    if chemin is None:
        print("  RUBAN L2 INTROUVABLE OU VIDE — rien a mesurer, et ce n'est pas une couverture")
        print("  nulle : c'est une absence de mesure. (Collecteurs eteints ?)")
        return 2
    bilan = mesurer(couverture_par_minute(chemin), horizon_min=args.horizon_min)
    if args.json:
        print(json.dumps(bilan, ensure_ascii=False, indent=1))
        return 0 if bilan.get("verdict") == "STABLE" else 3
    print(f"  STABILITE DE LA COUVERTURE DES CARNETS — {chemin.name}")
    print("  " + "=" * 68)
    if bilan.get("verdict") == "RIEN_A_MESURER":
        print(f"  {bilan['pourquoi']}")
        return 2
    cpm = bilan["coins_par_minute"]
    print(f"  minutes observees : {bilan['minutes_observees']:,}")
    print(f"  coins par minute  : min {cpm['min']} | median {cpm['median']:.0f}"
          f" | p90 {cpm['p90']} | max {cpm['max']}")
    print(f"  minutes sous la MOITIE du median : {bilan['minutes_sous_la_moitie_du_median']:,}"
          f"  ({bilan['part_sous_la_moitie_pct']} %)")
    c = bilan["creux"]
    print(f"  creux : {c['nombre']} | duree mediane {c['duree_mediane_min']} min"
          f" | MAX {c['duree_max_min']} min")
    print(f"  plus longs que l'horizon du labo ({bilan['horizon_max_labo_min']} min)"
          f" : {c['plus_longs_que_l_horizon']}")
    print("  " + "-" * 68)
    print(f"  VERDICT : {bilan['verdict']}")
    if c["plus_longs_que_l_horizon"]:
        print(f"     un creux depassant {bilan['horizon_max_labo_min']} min avale un episode")
        print("     ENTIER (entree ET sortie) : collecter plus longtemps n'y changera rien.")
    print(f"  ce que ca ne prouve PAS : {bilan['ce_que_ca_ne_prouve_pas']}")
    return 0 if bilan["verdict"] == "STABLE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
