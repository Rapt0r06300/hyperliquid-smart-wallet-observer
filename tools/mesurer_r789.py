#!/usr/bin/env python3
"""R7 / R8 / R9 — ce qui est DEJA mesurable, et ce qui attend la fin de campagne.

Les trois chantiers partagent une cible : le **PnL NET COPIABLE par leader**, qui sort du moteur
(sonde d'executabilite + couts complets) et donc de la campagne. Cet outil fait tout le reste
MAINTENANT — extraire les caracteristiques, etiqueter, compter — pour que le 19/11 soit un jour
de MESURE et non un jour de developpement. Quand la cible manque, il le DIT : il ne la remplace
par rien.

* **R9** — le style d'execution predit-il la copiabilite ? Caracteristiques par leader :
  part agressive, taille mediane, cadence.
* **R8** — copier pendant un TWAP annonce coute-t-il autre chose ? Part des fills rattachables a
  un TWAP actif au moment du fill.
* **R7** — le regime doit decider : repartition des observations par regime.

PAPER / lecture seule : aucune requete reseau, aucun ordre, aucune ecriture.
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
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))

COFFRE = Path("runtime") / "coffre_certifie" / "local" / "shards"


def lire_shards(dossier: Path, *, limite: int = 12) -> list[dict]:
    """Les enregistrements des shards les plus recents d'une famille certifiee."""
    if not dossier.is_dir():
        return []
    fichiers = sorted(dossier.glob("*.jsonl.gz"), key=lambda p: p.stat().st_mtime,
                      reverse=True)[:limite]
    sortie: list[dict] = []
    for fichier in fichiers:
        try:
            with gzip.open(fichier, "rt", encoding="utf-8", errors="replace") as flux:
                for ligne in flux:
                    texte = ligne.strip()
                    if not texte.startswith("{"):
                        continue
                    try:
                        objet = json.loads(texte)
                    except ValueError:
                        continue
                    if isinstance(objet, dict):
                        sortie.append(objet)
        except OSError:
            continue
    return sortie


def _leader(enregistrement: dict) -> str | None:
    for cle in ("vault", "unit", "user"):
        valeur = enregistrement.get(cle)
        if valeur:
            return str(valeur)
    return None


def caracteristiques_par_leader(fills: list[dict]) -> dict[str, dict]:
    """R9 — le STYLE de chaque leader, mesure sur ses fills certifies.

    `crossed` dit si le fill a traverse le spread (agressif). La part agressive est deja un critere
    du moteur (C86) ; ici on l'agrege par leader, avec la taille et la cadence.
    """
    groupes: dict[str, list[dict]] = defaultdict(list)
    for fill in fills:
        nom = _leader(fill)
        if nom:
            groupes[nom].append(fill)

    sortie: dict[str, dict] = {}
    for nom, items in groupes.items():
        agressifs = sum(1 for f in items if f.get("crossed") in (True, 1, "true", "1"))
        connus = sum(1 for f in items if f.get("crossed") is not None)
        tailles = []
        instants = []
        for f in items:
            try:
                tailles.append(abs(float(f.get("sz") or f.get("size") or 0.0)))
            except (TypeError, ValueError):
                pass
            for cle in ("observed_at_ms", "received_at_ms", "ts_ms", "time"):
                valeur = f.get(cle)
                if valeur is not None:
                    try:
                        instants.append(int(valeur))
                    except (TypeError, ValueError):
                        pass
                    break
        instants.sort()
        ecarts = [b - a for a, b in zip(instants, instants[1:]) if b > a]
        sortie[nom] = {
            "fills": len(items),
            # None et PAS 0.0 : « part inconnue » n'est pas « jamais agressif » (regle C86).
            "part_agressive": (agressifs / connus) if connus else None,
            "fills_avec_crossed": connus,
            "taille_mediane": statistics.median(tailles) if tailles else None,
            "ecart_median_ms": statistics.median(ecarts) if ecarts else None,
        }
    return sortie


def part_twap(fills: list[dict]) -> dict:
    """R8 — part des fills rattachables a un TWAP.

    PRUDENCE : la presence d'un `twapId` dit que le fill APPARTIENT a un TWAP, pas qu'un TWAP
    etait AFFICHE et actif au moment ou un copieur aurait agi. Conclure la visibilite a partir du
    seul identifiant serait un lookahead. Ce compte est donc une BORNE SUPERIEURE de la population
    « visible », pas la population elle-meme.
    """
    avec = sans = inconnu = 0
    for fill in fills:
        if "twapId" not in fill and "twap_id" not in fill:
            inconnu += 1
            continue
        valeur = fill.get("twapId", fill.get("twap_id"))
        if valeur:
            avec += 1
        else:
            sans += 1
    total = avec + sans
    return {
        "avec_twap": avec, "sans_twap": sans, "sans_information": inconnu,
        "part": (avec / total) if total else None,
        "borne_superieure": True,
    }


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--shards", type=int, default=12)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.root)

    from hl_observer.backtesting import test_transversal as T

    fills = lire_shards(root / COFFRE / "fills_forward", limite=args.shards)
    if not fills:
        print("[r789] aucun fill certifie lu : lancer apres une passe de certification.")
        return 2

    styles = caracteristiques_par_leader(fills)
    twap = part_twap(fills)

    # R9 : la cible (PnL net copiable par leader) vient du moteur. Sans elle, on REFUSE.
    observations = [
        {"leader": nom, "part_agressive": donnees["part_agressive"],
         "taille_mediane": donnees["taille_mediane"], "pnl_net_copiable": None}
        for nom, donnees in styles.items()
    ]
    r9 = T.tester(observations, caracteristique="part_agressive",
                  cible="pnl_net_copiable", essais=4)

    avec_part = [d for d in styles.values() if d["part_agressive"] is not None]
    resume = {
        "fills_lus": len(fills),
        "leaders": len(styles),
        "leaders_avec_part_agressive": len(avec_part),
        "twap": twap,
        "r9": r9,
    }
    if args.json:
        print(json.dumps(resume, ensure_ascii=False, indent=1, default=str))
        return 0

    print("R7 / R8 / R9 — etat des mesures")
    print("=" * 72)
    print(f"  {len(fills)} fills certifies | {len(styles)} leaders distincts")
    print()
    print("R9 — STYLE D'EXECUTION (caracteristiques pretes)")
    print(f"  part agressive connue pour {len(avec_part)} leader(s) sur {len(styles)}")
    if avec_part:
        parts = sorted(d["part_agressive"] for d in avec_part)
        print(f"  mediane des parts agressives : {statistics.median(parts):.1%} "
              f"(de {parts[0]:.1%} a {parts[-1]:.1%})")
    print(f"  {r9['lecture']}")
    print("  -> la CIBLE (PnL net copiable par leader) sort du moteur : disponible apres campagne.")
    print()
    print("R8 — TWAP")
    if twap["part"] is None:
        print(f"  aucun fill ne porte l'information TWAP ({twap['sans_information']} sans le champ)")
    else:
        print(f"  {twap['part']:.1%} des fills portent un twapId "
              f"({twap['avec_twap']} sur {twap['avec_twap'] + twap['sans_twap']})")
    print("  -> BORNE SUPERIEURE : un twapId dit l'appartenance, PAS qu'un TWAP etait AFFICHE")
    print("     au moment ou un copieur aurait agi. Conclure la visibilite ici serait un lookahead.")
    print()
    print("R7 — REGIME")
    print("  l'etiquetage existe (`regime_label`, causal, seuil calcule sur le TRAIN seul).")
    print("  La comparaison par regime attend la meme cible que R9.")
    print()
    print("  Aucune de ces trois questions n'est repondue ici : les caracteristiques sont PRETES,")
    print("  la cible arrive avec la campagne. C'est voulu — mieux vaut un outil qui refuse qu'un")
    print("  chiffre invente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
