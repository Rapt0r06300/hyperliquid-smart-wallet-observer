#!/usr/bin/env python3
"""C110 / C82 / C83 — « ce que je collecte en ce moment sera-t-il mesurable ? », en quelques secondes.

POURQUOI CET OUTIL. La boucle de retour sur la qualité de la collecte durait des JOURS : collecter,
certifier, lancer le labo (dizaines de minutes, 16 Go de RAM), et découvrir alors que **77 008 signaux
sur 98 138** étaient inexploitables faute de carnet dans les 30 s précédant le signal. Ici, le même
constat est fait directement sur les rubans bruts, sans certification et sans labo.

CE QU'IL LIT (lecture seule, coût borné : seule la QUEUE de chaque ruban est lue) :

* ``runtime/data/vault_fills_live.jsonl`` — les fills des leaders ;
* ``runtime/data/copy_vault_l2_tape.jsonl`` — les carnets collectés.

DEUX PRÉCAUTIONS QUI ÉVITENT UNE JAUGE MENTEUSE :

1. **le bon horodatage.** Les carnets portent ``received_at_ms`` ET ``exchange_ts_ms``. Le chargeur du
   labo retient la RÉCEPTION comme horodatage canonique (``copy_vault_book_loader``, ``ts_ms=received``) :
   c'est l'instant où nous AURIONS PU agir. On fait pareil, sinon la jauge et le labo ne parleraient pas
   de la même chose.
2. **la fenêtre réellement observable.** Comme on ne lit que la queue des rubans, les fills antérieurs
   au premier carnet lu paraîtraient tous « sans référence » — un artefact de lecture, pas un défaut de
   collecte. Les fills hors de la fenêtre couverte sont donc ÉCARTÉS et comptés à part.

PAPER / lecture seule : aucune requête réseau, aucun ordre, aucune écriture.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))

FILLS = Path("runtime") / "data" / "vault_fills_live.jsonl"
CARNETS = Path("runtime") / "data" / "copy_vault_l2_tape.jsonl"

#: Queue lue par défaut sur chaque ruban (coût borné quelle que soit la taille du fichier).
OCTETS_FILLS = 4 * 1024 * 1024
OCTETS_CARNETS = 32 * 1024 * 1024


def queue_jsonl(chemin: Path, octets: int) -> list[dict]:
    """Les derniers objets JSON complets du ruban. Ligne tronquée et ligne abîmée : ignorées."""
    try:
        taille = chemin.stat().st_size
        depart = max(0, taille - max(1, int(octets)))
        with chemin.open("rb") as flux:
            flux.seek(depart)
            brut = flux.read()
    except OSError:
        return []
    lignes = brut.decode("utf-8", errors="replace").splitlines()
    if depart > 0 and lignes:
        lignes = lignes[1:]                       # la première ligne lue est coupée en deux
    objets = []
    for ligne in lignes:
        texte = ligne.strip()
        if not texte.startswith("{"):
            continue
        try:
            objet = json.loads(texte)
        except ValueError:
            continue
        if isinstance(objet, dict):
            objets.append(objet)
    return objets


def carnets_par_coin(lignes: list[dict]) -> dict[str, list[dict]]:
    """Carnets groupés par coin et triés, avec ``ts_ms`` = horodatage de RÉCEPTION (comme le labo)."""
    groupes: dict[str, list[dict]] = {}
    for ligne in lignes:
        coin = str(ligne.get("coin") or "")
        recu = ligne.get("received_at_ms", ligne.get("ts_ms"))
        if not coin or recu is None:
            continue
        try:
            ts = int(recu)
        except (TypeError, ValueError):
            continue
        groupes.setdefault(coin, []).append({
            "ts_ms": ts,
            "connection_id": ligne.get("connection_id"),
            "l2_gap_epoch": ligne.get("l2_gap_epoch"),
        })
    for carnets in groupes.values():
        carnets.sort(key=lambda c: c["ts_ms"])
    return groupes


def fenetre_observable(groupes: dict[str, list[dict]], *, delai_ms: int, horizon_ms: int,
                       lag_max_ms: int) -> tuple[int, int] | None:
    """La fenêtre de signaux sur laquelle le verdict a un SENS, vu les carnets réellement lus.

    Avant ``premier_carnet + lag_max`` on n'a pas de quoi juger la référence ; après
    ``dernier_carnet - délai - horizon`` on n'a pas de quoi juger la sortie. Hors de là, un « manque »
    serait un artefact de la lecture bornée, pas un défaut de collecte.
    """
    debuts = [carnets[0]["ts_ms"] for carnets in groupes.values() if carnets]
    fins = [carnets[-1]["ts_ms"] for carnets in groupes.values() if carnets]
    if not debuts or not fins:
        return None
    debut = min(debuts) + int(lag_max_ms)
    fin = max(fins) - int(delai_ms) - int(horizon_ms)
    return (debut, fin) if debut <= fin else None


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--horizon-ms", type=int, default=None,
                   help="horizon teste (defaut : le plus court du moteur, donc le plus indulgent)")
    p.add_argument("--octets-fills", type=int, default=OCTETS_FILLS)
    p.add_argument("--octets-carnets", type=int, default=OCTETS_CARNETS)
    p.add_argument("--sans-fenetre-par-coin", action="store_true",
                   help="lecture PESSIMISTE d'origine : juge aussi les fills hors de la couverture "
                        "de leur coin (utile pour comparer, trompeur pour decider)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.root)

    from hl_observer.collection import reconciliation_carnets as R

    groupes = carnets_par_coin(queue_jsonl(root / CARNETS, args.octets_carnets))
    fills_bruts = queue_jsonl(root / FILLS, args.octets_fills)
    if not groupes or not fills_bruts:
        print("[reconciliation] rubans vides ou absents : rien a reconcilier "
              f"({len(fills_bruts)} fills, {len(groupes)} coins avec carnets).")
        return 2

    horizon = int(args.horizon_ms) if args.horizon_ms else None
    # La fenetre jugeable est calculee PAR COIN par le module (`couverture_du_coin`), pas globalement.
    # Correctif du 12/11 : une fenetre globale accusait a tort 114 fills sur 687 — des fills tombant
    # simplement avant que LEUR coin ait commence a etre suivi. Mesurer faux aurait envoye la collecte
    # corriger un probleme inexistant.
    jauge = R.reconcilier(fills_bruts, groupes, horizon_ms=horizon,
                          ignorer_hors_couverture=not args.sans_fenetre_par_coin)
    jauge["coins_avec_carnets"] = len(groupes)
    fenetre = fenetre_observable(groupes, delai_ms=jauge["delai_ms"], horizon_ms=jauge["horizon_ms"],
                                 lag_max_ms=jauge["lag_max_ms"])
    if fenetre is None:
        print("[reconciliation] les carnets lus ne couvrent pas une fenetre exploitable "
              "(elargir --octets-carnets ou collecter plus longtemps).")
        return 2
    debut, fin = fenetre
    jauge["fenetre_tous_coins_ms"] = [debut, fin]
    hors_fenetre = int(jauge.get("fills_non_jugeables_hors_couverture") or 0)

    if args.json:
        print(json.dumps(jauge, ensure_ascii=False, indent=1))
        return 0

    print("RECONCILIATION DES CARNETS — ce que la collecte actuelle rendra mesurable")
    print("=" * 74)
    print(f"  fenetre observable : {(fin - debut) / 60_000:.0f} min | {len(groupes)} coins suivis "
          f"| {hors_fenetre} fills NON JUGEABLES (hors couverture de leur coin)")
    print(f"  horizon teste : {jauge['horizon_ms'] // 1000} s | delai {jauge['delai_ms'] // 1000} s "
          f"| lag max {jauge['lag_max_ms'] // 1000} s")
    print()
    print(f"  {R.resume_lisible(jauge)}")
    if jauge["par_motif"]:
        print()
        print("  Manques, par motif :")
        for motif, nombre in jauge["par_motif"].items():
            print(f"    {nombre:>6} x {motif}")
            print(f"           {R.EXPLICATIONS.get(motif, '')}")
    a_corriger = R.coins_a_corriger(jauge)
    if a_corriger:
        print()
        print("  Coins a corriger en priorite :")
        for ligne in a_corriger[:10]:
            print(f"    {ligne['coin']:<16} {ligne['incomplets']:>5} incomplets / {ligne['fills']:<5} "
                  f"({ligne['part_complete'] * 100:.0f} % bons)  {ligne['motif_dominant']}")
    if jauge["coins_sans_aucun_carnet"]:
        print()
        print(f"  ALERTE — coins actifs SANS AUCUN carnet : "
              f"{', '.join(jauge['coins_sans_aucun_carnet'][:12])}")
    print()
    print("  Portee : conditions NECESSAIRES (reference + entree + sortie + identite de connexion).")
    print("  Un fill qui passe ici reste soumis au moteur (profondeur, capacite, spread, funding).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
