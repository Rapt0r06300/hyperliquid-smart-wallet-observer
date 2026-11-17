#!/usr/bin/env python3
"""MATRICE DE CONSOMMATION DU COFFRE : pour chaque famille, ce qu'elle contient ET son usage RÉEL.

POURQUOI (chantiers 9, 10 et 12 de la feuille de route d'audit). « Présent dans le coffre » ne veut
dire ni « lu », ni « utilisé dans un modèle », ni « admissible à une preuve ». Le run du 12/11
comptait 13 354 078 lignes de signaux LOCAL, puis le chemin principal appelait
`_charger_tier_local(..., garder_signaux=False)` : les lignes étaient **comptées puis jetées**. Un
inventaire ne prouve pas une consommation.

Cet outil publie, par famille : shards indexés, lignes déposées, **présence physique réellement
vérifiée**, octets, jours couverts, coins, statut de qualité, et la **destination réelle** déduite
du CODE de production (et non d'une intention) :

* `REPLAY_PNL`    — famille chargée pour reconstruire fills et positions ;
* `CARNETS`       — carnets/cotations chargés pour l'exécutabilité ;
* `CONTEXTE`      — signal chargé seulement si `garder_signaux=True` : **compté sinon** ;
* `NON_CHARGEE`   — indexée mais aucun chemin de chargement dans le pont LOCAL.

Les destinations viennent de `copy_vault_tier_local`, importé ici : si le code change, la matrice
change avec lui, et une divergence est impossible.

PAPER / LECTURE SEULE. Un shard introuvable sur le disque est un ÉCHEC VISIBLE, jamais un zéro.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_tier_local as TL  # noqa: E402

LOCAL_INDEX = Path("runtime") / "coffre_certifie" / "LOCAL_INDEX.json"
COFFRE_INDEX = Path("runtime") / "coffre_certifie" / "COFFRE_INDEX.json"


def destination(famille: str) -> str:
    """L'usage RÉEL de cette famille, lu du code de production."""
    if famille in TL._COFFRE_FAMILLES_FILLS:
        return "REPLAY_PNL"
    if famille in {"book_l2", "bbo"}:
        return "CARNETS"
    if famille in getattr(TL, "FAMILLES_EXCLUES_DU_REPLAY", {}):
        return "EXCLUE_MOTIVEE"
    if famille in getattr(TL, "FAMILLES_A_ROLE_MESURE", {}):
        return "ROLE_MESURE"
    if famille in TL._COFFRE_FAMILLES_SIGNAUX:
        return "CONTEXTE"
    return "NON_CHARGEE"


#: Correspondance entre les familles du tier SAFE (catalogue cloud) et celles du tier LOCAL.
FAMILLES_SAFE_VERS_LOCAL: dict[str, tuple[str, ...]] = {
    "copy_vault_fills": ("fills_forward", "fills_backfill"),
    "copy_vault_l2": ("book_l2",),
    "copy_vault_snapshot": ("snapshot",),
    "copy_vault_positions": ("position",),
    "copy_vault_selection": (),
}

from hl_observer.ops.fraicheur_preuve import date_du_tag_ms as _date_du_tag_ms  # noqa: E402


#: 17/11/2026 : UNE seule definition du premier jour liable, pour la matrice ET pour le labo.
from hl_observer.backtesting.copy_vault_fenetre_locale import premier_jour_liable  # noqa: E402,F401


def reconcilier_local_et_safe(root: Path, familles_local: dict[str, Any],
                              shards: list[dict[str, Any]]) -> dict[str, Any]:
    """Ce que le tier SAFE contient, jusqu'à quand — et ce que seul LOCAL possède.

    17/11/2026 — DÉFAUT DE CET OUTIL, CORRIGÉ. L'ancien bloc lisait ``lots`` ou ``shards`` à la
    racine de ``COFFRE_INDEX.json``. Ces clés n'existent pas : l'index range ses tiers sous
    ``tiers``. La matrice annonçait donc **0 entrée SAFE pour 15 456 shards SAFE réels**, et
    personne ne pouvait y lire l'écart qui décide de tout : LOCAL sert à explorer, mais SEULE une
    chaîne SAFE peut soutenir OOS, forward et PnL.

    Ce bloc publie l'écart tel qu'il est : dernier tag SAFE connu, familles SAFE et leurs volumes,
    fenêtre LOCAL de chaque famille correspondante, et le nombre de jours que LOCAL a d'avance —
    c'est-à-dire ce qu'une nouvelle campagne cloud devrait couvrir pour devenir prouvable.
    """
    chemin = root / COFFRE_INDEX
    if not chemin.is_file():
        return {"present": False, "raison": "COFFRE_INDEX_ABSENT"}
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erreur:
        return {"present": False, "raison": type(erreur).__name__}
    tier = (brut.get("tiers") or {}).get("SAFE_CLOUD") if isinstance(brut, dict) else None
    if not isinstance(tier, dict):
        return {"present": False, "raison": "TIER_SAFE_CLOUD_ABSENT_DE_L_INDEX"}
    dates = [d for d in (_date_du_tag_ms(t) for t in tier.get("derniers_tags") or ()) if d]
    dernier_safe_ms = max(dates) if dates else None
    correspondances: dict[str, Any] = {}
    for famille_safe, locales in FAMILLES_SAFE_VERS_LOCAL.items():
        fins = [familles_local[f]["ts_max_ms"] for f in locales
                if f in familles_local and familles_local[f].get("ts_max_ms")]
        fin_local = max(fins) if fins else None
        avance = None
        if dernier_safe_ms and fin_local:
            avance = round((fin_local - dernier_safe_ms) / 86_400_000.0, 1)
        correspondances[famille_safe] = {
            "shards_safe": int((tier.get("par_famille") or {}).get(famille_safe) or 0),
            "familles_local": list(locales),
            "lignes_local": sum(int(familles_local[f]["lignes_deposees"]) for f in locales
                                if f in familles_local),
            "fin_local_ms": fin_local,
            "jours_local_en_avance_sur_safe": avance,
        }
    liaison = premier_jour_liable(root, shards)
    premier = liaison["premier_jour_liable"]
    premier_ms = None
    if premier:
        premier_ms = int(datetime.strptime(premier, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)
    return {
        "present": bool(tier.get("present")),
        "shards_safe": int(tier.get("shards_safe") or 0),
        "releases": int(tier.get("n_releases") or 0),
        "dernier_tag_safe_ms": dernier_safe_ms,
        "dernier_tag_safe": (None if dernier_safe_ms is None else
                             time.strftime("%Y-%m-%d %H:00", time.gmtime(dernier_safe_ms / 1000.0))),
        "tags_lus": len(dates),
        "correspondances": correspondances,
        "liaison_pre_signal": liaison,
        # Le fait qui borne toute preuve : la chaine causale complete commence APRES le dernier
        # tag SAFE. Tant que c'est vrai, rien de ce que le labo mesure dessus n'est prouvable.
        "fenetre_causale_couverte_par_safe": bool(
            dernier_safe_ms and premier_ms and dernier_safe_ms >= premier_ms),
        "condition_de_levee": ("une campagne cloud GitHub-hosted posterieure au premier jour "
                               "liable, puis release et restauration AlinaSync"),
    }


def mesurer(root: Path, *, verifier_octets: bool) -> dict[str, Any]:
    index = json.loads((root / LOCAL_INDEX).read_text(encoding="utf-8"))
    shards = index.get("shards") or []
    familles: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "shards": 0, "deposes": 0, "octets_indexes": 0, "presents": 0, "absents": 0,
        "octets_divergents": 0, "sans_sha": 0, "jours": set(), "coins": set(),
        "ts_min_ms": None, "ts_max_ms": None, "qualites": defaultdict(int),
        "shards_absents": [],
    })
    for s in shards:
        if not isinstance(s, dict):
            continue
        fam = str(s.get("famille") or "?")
        bloc = familles[fam]
        bloc["shards"] += 1
        bloc["deposes"] += int(s.get("deposes") or 0)
        bloc["octets_indexes"] += int(s.get("octets") or 0)
        bloc["qualites"][str(s.get("quality_status") or "?")] += 1
        sha = s.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64:
            bloc["sans_sha"] += 1
        jours = s.get("jours")
        if isinstance(jours, dict):
            bloc["jours"].update(jours)
        elif isinstance(jours, list):
            bloc["jours"].update(str(j) for j in jours)
        coins = s.get("coins")
        if isinstance(coins, list):
            bloc["coins"].update(str(c) for c in coins)
        for cle, nom in (("ts_min_ms", "min"), ("ts_max_ms", "max")):
            v = s.get(cle)
            if type(v) is int:
                actuel = bloc[cle]
                bloc[cle] = v if actuel is None else (min(actuel, v) if nom == "min" else max(actuel, v))
        chemin = root / str(s.get("shard") or "")
        try:
            stat = chemin.stat()
        except OSError:
            bloc["absents"] += 1
            if len(bloc["shards_absents"]) < 5:
                bloc["shards_absents"].append(str(s.get("shard")))
            continue
        bloc["presents"] += 1
        if verifier_octets and int(s.get("octets") or -1) not in (-1, int(stat.st_size)):
            bloc["octets_divergents"] += 1

    sortie = {}
    for fam, bloc in sorted(familles.items()):
        sortie[fam] = {
            "destination": destination(fam),
            "motif_exclusion": getattr(TL, "FAMILLES_EXCLUES_DU_REPLAY", {}).get(fam),
            "fiche_role": getattr(TL, "FAMILLES_A_ROLE_MESURE", {}).get(fam),
            "shards_indexes": bloc["shards"],
            "shards_presents": bloc["presents"],
            "shards_absents": bloc["absents"],
            "exemples_absents": bloc["shards_absents"],
            "octets_divergents": bloc["octets_divergents"],
            "shards_sans_sha": bloc["sans_sha"],
            "lignes_deposees": bloc["deposes"],
            "octets_indexes": bloc["octets_indexes"],
            "jours_couverts": len(bloc["jours"]),
            "coins": len(bloc["coins"]),
            "ts_min_ms": bloc["ts_min_ms"],
            "ts_max_ms": bloc["ts_max_ms"],
            "qualites": dict(bloc["qualites"]),
        }

    safe = reconcilier_local_et_safe(root, sortie, shards)

    return {
        "schema": "hypersmart.matrice_coffre.v1",
        "genere_ms": int(time.time() * 1000),
        "paper_read_only": True,
        "real_execution": False,
        "tier": index.get("tier"),
        "shards_indexes": len(shards),
        "familles": sortie,
        "coffre_safe": safe,
        "totaux": {
            "lignes_deposees": sum(f["lignes_deposees"] for f in sortie.values()),
            "shards_absents": sum(f["shards_absents"] for f in sortie.values()),
            "familles": len(sortie),
            "par_destination": {
                d: sum(1 for f in sortie.values() if f["destination"] == d)
                for d in ("REPLAY_PNL", "CARNETS", "CONTEXTE", "ROLE_MESURE",
                          "EXCLUE_MOTIVEE", "NON_CHARGEE")
            },
        },
    }


def mesurer_roles(root: Path, *, debut_ms: int | None = None, fin_ms: int | None = None,
                  ) -> dict[str, Any]:
    """Exécute la mesure de rôle de chaque famille de ``FAMILLES_A_ROLE_MESURE``, en flux.

    ``debut_ms`` / ``fin_ms`` bornent les deux familles lourdes (``trades_marche``,
    ``fills_forward`` pour compter les ouvertures) ; les trois petites sont lues en entier.
    Chaque bloc publie ce que la lecture a coûté et refusé : un rôle mesuré sur des shards
    refusés serait une mesure sur un corpus amoindri.
    """
    from hl_observer.backtesting import coffre_tranches as TR
    from hl_observer.backtesting import copy_vault_detention as DET
    from hl_observer.backtesting import copy_vault_roles_familles as ROLES
    from hl_observer.backtesting.copy_vault_executable import (
        classify_live_entry_action,
        expected_open_direction,
    )

    index = json.loads((root / LOCAL_INDEX).read_text(encoding="utf-8"))
    shards = [x for x in index.get("shards") or [] if isinstance(x, dict)]

    def flux(famille: str, *, borne: bool) -> tuple[Any, dict[str, Any]]:
        sel = TR.selectionner(shards, famille=famille,
                              debut_ms=debut_ms if borne else None,
                              fin_ms=fin_ms if borne else None)
        compteurs: dict[str, Any] = {"shards_retenus": len(sel["retenus"])}
        return TR.flux(root, sel["retenus"], famille=famille,
                       debut_ms=debut_ms if borne else None,
                       fin_ms=fin_ms if borne else None, compteurs=compteurs), compteurs

    def cout(compteurs: dict[str, Any]) -> dict[str, Any]:
        return {"shards_retenus": compteurs.get("shards_retenus", 0),
                "shards_lus": compteurs.get("shards_lus", 0),
                "shards_refuses": compteurs.get("shards_refuses", []),
                "lignes_sans_horloge": compteurs.get("lignes_sans_horloge", 0)}

    sortie: dict[str, Any] = {}
    lignes, c = flux("trades_marche", borne=True)
    sortie["trades_marche"] = {**ROLES.capacite_par_coin(lignes), "lecture_du_coffre": cout(c)}
    lignes, c = flux("liquidation", borne=False)
    sortie["liquidation"] = {**ROLES.risque_de_liquidation(lignes), "lecture_du_coffre": cout(c)}
    lignes, c = flux("vault_ledger", borne=False)
    sortie["vault_ledger"] = {**ROLES.flux_de_capital(lignes), "lecture_du_coffre": cout(c)}
    lignes, c = flux("overshoot", borne=False)
    sortie["overshoot"] = {**ROLES.resultat_overshoot(lignes), "lecture_du_coffre": cout(c)}

    # Applicabilite de la microstructure : les ouvertures COPIABLES, comptees par coin avec les
    # MEMES regles que le tunnel (fill WS non-snapshot, ouverture explicite, dedoublonne).
    ouvertures: dict[str, int] = {}
    vus: set[tuple] = set()
    lignes, c = flux("fills_forward", borne=True)
    for fill in lignes:
        if fill.get("source") != "LIVE_WS":
            continue
        if fill.get("isSnapshot", fill.get("is_snapshot")) is not False:
            continue
        if expected_open_direction(fill) is None or classify_live_entry_action(fill) is None:
            continue
        cle = DET.cle_d_identite(fill)
        if cle in vus:
            continue
        vus.add(cle)
        coin = fill.get("coin")
        if isinstance(coin, str) and coin:
            ouvertures[coin] = ouvertures.get(coin, 0) + 1
    coins_micro = {str(k) for x in shards if x.get("famille") in ("micro_l2", "micro_trades")
                   for k in (x.get("coins") or [])}
    sortie["microstructure"] = {
        **ROLES.applicabilite_microstructure(ouvertures, coins_micro),
        "lecture_du_coffre": cout(c),
    }
    return {
        "schema": "hypersmart.matrice_coffre.roles.v1",
        "genere_ms": int(time.time() * 1000),
        "fenetre_ms": [debut_ms, fin_ms],
        "paper_read_only": True, "real_execution": False,
        "roles": sortie,
    }


def afficher_roles(rapport: dict[str, Any]) -> None:
    r = rapport["roles"]
    print()
    print("  ROLES MESURES DES FAMILLES SANS CONSOMMATEUR DE REPLAY")
    cap = r["trades_marche"]
    print(f"  trades_marche  [{cap['role']}] {cap['lignes_lues']:,} trades, {cap['coins']} coins : "
          f"multiple median {cap['multiple_median']} x l'ordre de {cap['ordre_usd']:.0f} USD ; "
          f"{cap['coins_a_capacite_large']} coins a capacite large "
          f"({cap['part_coins_a_capacite_large']})")
    etroits = cap["coins_ou_une_minute_mediane_absorbe_moins_que_l_ordre"]
    print(f"                 coins ou une minute mediane absorbe MOINS que l'ordre : {len(etroits)}"
          + (f" — {', '.join(str(c) for c, _ in etroits[:8])}" if etroits else ""))
    liq = r["liquidation"]
    print(f"  liquidation    [{liq['role']}] {liq['evenements']:,} evenements, "
          f"{liq['comptes_touches']} comptes, {liq['jours_avec_evenement']} jours actifs "
          f"({liq['evenements_par_jour_actif']} par jour actif)")
    flx = r["vault_ledger"]
    print(f"  vault_ledger   [{flx['role']}] {flx['jours_compte_avec_flux']:,} jours-compte avec flux "
          f"sur {flx['comptes_avec_flux']} comptes ; retraits {flx['part_retraits']} ; "
          f"montants inconnus {flx['montants_inconnus']:,}")
    ovs = r["overshoot"]
    print(f"  overshoot      [{ovs['role']}] {ovs['evenements']:,} evenements ; "
          f"{ovs['part_avec_champs_du_futur']} portent des prix du futur ; "
          f"|amplitude| p50 {ovs['amplitude_abs_bps']['p50']} bps ; "
          f"reversion nulle {ovs['part_reversion_nulle']}")
    mic = r["microstructure"]
    print(f"  micro_l2/trades [{mic['role']}] {mic['coins_micro']} coins couverts ; "
          f"{mic['ouvertures_sur_coins_micro']:,} / {mic['ouvertures']:,} ouvertures copiables "
          f"= {mic['part_des_ouvertures_couvertes']}")
    refus = {f: len(b["lecture_du_coffre"]["shards_refuses"]) for f, b in r.items()
             if b["lecture_du_coffre"]["shards_refuses"]}
    print(f"  shards refuses a la lecture : {json.dumps(refus) if refus else 'aucun'}")


def afficher(rapport: dict[str, Any]) -> None:
    print("=" * 112)
    print("  MATRICE DE CONSOMMATION DU COFFRE — PAPER / LECTURE SEULE")
    print(f"  tier={rapport['tier']} | {rapport['shards_indexes']:,} shards indexes | "
          f"{rapport['totaux']['familles']} familles | "
          f"{rapport['totaux']['lignes_deposees']:,} lignes deposees")
    print("=" * 112)
    entete = (f"  {'famille':<20} {'destination':<12} {'shards':>7} {'absents':>8} "
              f"{'lignes':>14} {'jours':>6} {'coins':>6} {'sans_sha':>9}")
    print(entete)
    print("  " + "-" * 108)
    for fam, bloc in rapport["familles"].items():
        print(f"  {fam:<20} {bloc['destination']:<12} {bloc['shards_indexes']:>7,} "
              f"{bloc['shards_absents']:>8,} {bloc['lignes_deposees']:>14,} "
              f"{bloc['jours_couverts']:>6} {bloc['coins']:>6} {bloc['shards_sans_sha']:>9,}")
    print()
    print("  par destination :", json.dumps(rapport["totaux"]["par_destination"]))
    manquants = {f: b["shards_absents"] for f, b in rapport["familles"].items() if b["shards_absents"]}
    if manquants:
        print(f"  ECHEC VISIBLE — shards indexes ABSENTS du disque : {json.dumps(manquants)}")
    else:
        print("  tous les shards indexes sont presents sur le disque.")
    safe = rapport.get("coffre_safe") or {}
    if safe.get("present"):
        print()
        print("  RECONCILIATION LOCAL -> SAFE (LOCAL explore ; SEULE une chaine SAFE peut prouver)")
        print(f"  SAFE : {safe['shards_safe']:,} shards, {safe['releases']} releases, "
              f"dernier tag connu {safe.get('dernier_tag_safe') or 'inconnu'}")
        for fam, c in safe["correspondances"].items():
            avance = c["jours_local_en_avance_sur_safe"]
            print(f"    {fam:<22} {c['shards_safe']:>7,} shards SAFE | LOCAL "
                  f"{c['lignes_local']:>12,} lignes"
                  + (f" | LOCAL en avance de {avance} j" if avance is not None else ""))
        liaison = safe["liaison_pre_signal"]
        print(f"  premier jour ou une reference pre-signal est liable : "
              f"{liaison['premier_jour_liable'] or 'aucun'}")
        if not safe["fenetre_causale_couverte_par_safe"]:
            print("  ECART OUVERT — la fenetre causalement complete n'existe qu'en LOCAL : rien de ce "
                  "que le labo y mesure n'est prouvable.")
            print(f"  condition de levee : {safe['condition_de_levee']}")
    elif safe:
        print(f"\n  tier SAFE illisible : {safe.get('raison')}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--sans-verif-octets", action="store_true")
    p.add_argument("--roles", action="store_true",
                   help="mesure le role de chaque famille sans consommateur de replay")
    p.add_argument("--depuis", default="", help="borne basse AAAA-MM-JJ UTC (mode --roles)")
    p.add_argument("--jusqu", default="", help="borne haute AAAA-MM-JJ UTC incluse (mode --roles)")
    p.add_argument("--sortie", default="")
    a = p.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    root = Path(a.root)
    if a.roles:
        def _borne(texte: str, fin_de_journee: bool) -> int | None:
            if not texte.strip():
                return None
            jour = datetime.strptime(texte.strip(), "%Y-%m-%d").replace(tzinfo=UTC)
            ms = int(jour.timestamp() * 1000)
            return ms + 86_399_999 if fin_de_journee else ms

        roles = mesurer_roles(root, debut_ms=_borne(a.depuis, False), fin_ms=_borne(a.jusqu, True))
        afficher_roles(roles)
        cible = Path(a.sortie) if a.sortie else (
            root / "runtime" / "reports" / "matrice_coffre"
            / f"roles_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(json.dumps(roles, ensure_ascii=False, indent=2), encoding="utf-8",
                         newline="\n")
        print(f"\n  rapport : {cible}")
        return 0
    rapport = mesurer(root, verifier_octets=not a.sans_verif_octets)
    afficher(rapport)
    cible = Path(a.sortie) if a.sortie else (
        root / "runtime" / "reports" / "matrice_coffre"
        / f"matrice_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  rapport : {cible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
