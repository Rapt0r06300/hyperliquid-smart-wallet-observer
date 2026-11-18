"""Le labo en DEUX PHASES : chaque tranche prepare, une seule passe explore.

LE PROBLEME QUE CECI RESOUT. Le corpus causal exploitable fait six journees. Les charger d'un seul
coup demande environ 52 Go : impossible. Les decouper en tranches tient en memoire (~2,5 Go par
tranche), mais une tranche de quatre heures ne permet pas un decoupage TRAIN/OOS valide : le labo
rend `TEMPORAL_SPLIT_INVALID_AFTER_PURGE` et n'essaie **aucun** candidat. Decouper et explorer dans
le meme mouvement est donc une impasse, quelle que soit la taille des tranches.

LA SORTIE. On separe ce qui se decoupe de ce qui ne se decoupe pas :

  * **Phase 1, par tranche** : reconstruire les cycles du leader, en tirer les metaordres, et ne
    garder des carnets QUE ceux qui peuvent servir -- ceux qui tombent dans la fenetre causale d'un
    signal. C'est la toute l'economie : un carnet qui n'est pas a portee d'un signal ne sera jamais
    lu par l'alignement, donc il n'a aucune raison de traverser la phase 2. Chaque tranche ecrit
    son resultat sur disque avec un manifeste.
  * **Phase 2, une seule fois** : relire les tranches preparees, fusionner, et laisser le labo
    aligner, decouper TRAIN/OOS et explorer sur l'ENSEMBLE des six journees -- ou le decoupage a
    enfin un sens.

CE QUE CE MODULE NE FAIT PAS, ET C'EST VOULU. Il ne juge rien. Il ne choisit pas de champion, ne
calcule pas de PnL, n'ecarte aucun signal pour une raison economique. Il deplace des donnees et
compte ce qu'il deplace. Tout verdict reste au labo, sur l'ensemble, apres la phase 2 -- parce
qu'un verdict rendu par un morceau sur un morceau est precisement ce qu'on cherche a eviter.

L'HONNETETE DES COMPTES. La phase 1 enregistre, pour chaque tranche, combien de metaordres et de
carnets elle a vus et combien elle a gardes, avec le motif de chaque ecart. La phase 2 refuse de
travailler sur un dossier dont un manifeste manque ou dont une empreinte ne correspond pas : une
tranche absente ferait un corpus silencieusement plus petit, et un corpus plus petit sans le dire
est la meilleure façon de fabriquer un faux resultat.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting.copy_vault_signal_alignment import MAX_BOOK_AGE_MS

#: Le nom du manifeste d'une tranche preparee.
MANIFESTE = "MANIFESTE.json"

#: Les deux rubans d'une tranche preparee.
FICHIER_METAORDRES = "metaordres.jsonl"
FICHIER_CARNETS = "carnets.jsonl"

#: Version du format. Une phase 2 qui lit une tranche d'une autre version REFUSE, plutot que de
#: deviner : deux formats melanges donneraient un corpus dont personne ne connait la composition.
FORMAT_VERSION = 1


def _empreinte(chemin: Path) -> str:
    """L'empreinte d'un fichier, lue par blocs (un ruban peut peser des centaines de Mo)."""
    h = hashlib.sha256()
    with open(chemin, "rb") as flux:
        for bloc in iter(lambda: flux.read(1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def _ecrire_jsonl(chemin: Path, lignes: Iterable[Mapping[str, Any]]) -> int:
    """Ecrit un ruban JSONL et rend le nombre de lignes.

    Ecriture en octets avec un saut de ligne explicite : `Path.write_text` convertirait les fins de
    ligne sous Windows, et une empreinte calculee ici ne correspondrait plus a celle relue
    ailleurs. On passe par un fichier temporaire remplace a la fin, pour qu'une interruption ne
    laisse jamais un ruban tronque passer pour complet.
    """
    temporaire = Path(str(chemin) + ".en-cours")
    compte = 0
    with open(temporaire, "wb") as flux:
        for ligne in lignes:
            flux.write(json.dumps(ligne, separators=(",", ":"), sort_keys=True).encode("utf-8"))
            flux.write(b"\n")
            compte += 1
    os.replace(temporaire, chemin)
    return compte


def _lire_jsonl(chemin: Path) -> list[dict[str, Any]]:
    with open(chemin, "rb") as flux:
        return [json.loads(ligne) for ligne in flux if ligne.strip()]


def carnets_utiles(
    metaordres: Sequence[Mapping[str, Any]],
    carnets: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    fenetre_ms: int = MAX_BOOK_AGE_MS,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Ne garde que les carnets qui peuvent servir a un signal, et dit ce qu'il ecarte.

    L'alignement ne lit qu'un carnet AU PLUS TARD au signal et AU PLUS TOT ``fenetre_ms`` avant
    lui. Un carnet hors de cette fenetre ne sera jamais lu : le transporter en phase 2 coute de la
    memoire sans rien apporter.

    La fenetre est fermee des deux cotes et inclut ses bornes, exactement comme l'alignement :
    ``signal - fenetre_ms <= ts_ms <= signal``. Prendre une fenetre plus LARGE ici serait sans
    danger (on garderait des carnets inutiles) ; la prendre plus ETROITE retirerait des carnets que
    l'alignement aurait acceptes, et ferait disparaitre des signaux sans que personne le voie.
    C'est pourquoi la valeur par defaut vient de l'alignement lui-meme, jamais d'une copie.
    """
    par_coin: dict[str, list[int]] = {}
    for ordre in metaordres:
        coin = str(ordre["coin"])
        par_coin.setdefault(coin, []).append(int(ordre["signal_ts_ms"]))
    for instants in par_coin.values():
        instants.sort()

    gardes: dict[str, list[dict[str, Any]]] = {}
    vus_total = 0
    gardes_total = 0
    sans_signal: dict[str, int] = {}
    hors_fenetre = 0
    for coin, liste in carnets.items():
        vus_total += len(liste)
        instants = par_coin.get(str(coin))
        if not instants:
            # Aucun signal sur ce coin : aucun de ses carnets ne peut servir.
            sans_signal[str(coin)] = len(liste)
            continue
        retenus: list[dict[str, Any]] = []
        for carnet in liste:
            ts = int(carnet["ts_ms"])
            # Un carnet sert s'il existe un signal dans [ts, ts + fenetre_ms].
            i = bisect.bisect_left(instants, ts)
            if i < len(instants) and instants[i] - ts <= fenetre_ms:
                retenus.append(dict(carnet))
            else:
                hors_fenetre += 1
        if retenus:
            gardes[str(coin)] = retenus
            gardes_total += len(retenus)
    audit = {
        "carnets_vus": vus_total,
        "carnets_gardes": gardes_total,
        "ecartes_hors_fenetre": hors_fenetre,
        "ecartes_coin_sans_signal": sum(sans_signal.values()),
        "coins_sans_signal": dict(sorted(sans_signal.items())[:20]),
        "fenetre_ms": int(fenetre_ms),
        "coins_gardes": len(gardes),
    }
    # Equation de conservation : rien ne se perd sans motif.
    reste = vus_total - gardes_total - hors_fenetre - audit["ecartes_coin_sans_signal"]
    audit["non_explique"] = reste
    return gardes, audit


def preparer_tranche(
    *,
    metaordres: Sequence[Mapping[str, Any]],
    carnets: Mapping[str, Sequence[Mapping[str, Any]]],
    sortie: Path,
    tranche: tuple[int, int] | None = None,
    identite: str | None = None,
    fenetre_ms: int = MAX_BOOK_AGE_MS,
) -> dict[str, Any]:
    """PHASE 1 : ecrit une tranche preparee sur disque et rend son manifeste.

    Ne juge rien : transporte et compte. Le manifeste porte les empreintes des deux rubans, pour
    que la phase 2 puisse refuser un dossier modifie entre les deux passes.
    """
    sortie.mkdir(parents=True, exist_ok=True)
    utiles, audit = carnets_utiles(metaordres, carnets, fenetre_ms=fenetre_ms)

    chemin_meta = sortie / FICHIER_METAORDRES
    n_meta = _ecrire_jsonl(chemin_meta, (dict(o) for o in metaordres))

    chemin_carnets = sortie / FICHIER_CARNETS
    n_carnets = _ecrire_jsonl(
        chemin_carnets,
        ({"coin": coin, "carnets": liste} for coin, liste in sorted(utiles.items())),
    )

    instants = [int(o["signal_ts_ms"]) for o in metaordres]
    manifeste = {
        "format_version": FORMAT_VERSION,
        "identite": identite or (f"{tranche[0]}-{tranche[1]}" if tranche else "sans-tranche"),
        "tranche_debut_ms": tranche[0] if tranche else None,
        "tranche_fin_ms": tranche[1] if tranche else None,
        "metaordres": n_meta,
        "lignes_carnets": n_carnets,
        "signal_ts_min_ms": min(instants) if instants else None,
        "signal_ts_max_ms": max(instants) if instants else None,
        "audit_carnets": audit,
        "sha256_metaordres": _empreinte(chemin_meta),
        "sha256_carnets": _empreinte(chemin_carnets),
    }
    _ecrire_jsonl(sortie / MANIFESTE, [manifeste])
    return manifeste


#: Les familles du coffre qui portent des carnets, de la plus riche a la plus pauvre.
#: `bbo` et `book_l2` couvrent depuis le 26/10 ; les rubans locaux `runtime/data/*.jsonl` ne
#: commencent qu'au 17/11 18:35 -- mesure du 18/11/2026. Lire le coffre, c'est la difference entre
#: une journee de carnets et trois semaines.
FAMILLES_DE_CARNETS = ("book_l2", "micro_l2", "venue_book", "bbo", "micro_bbo")


def carnets_du_coffre(
    racine: str | Path,
    *,
    coins: Sequence[str],
    debut_ms: int,
    fin_ms: int,
    familles: Sequence[str] = FAMILLES_DE_CARNETS,
    fenetre_ms: int = MAX_BOOK_AGE_MS,
    instants_par_coin: Mapping[str, Sequence[int]] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Lit les carnets du COFFRE en flux, et ne garde que ceux a portee d'un signal.

    POURQUOI LE COFFRE ET PAS LES RUBANS LOCAUX. `load_observed_books` lit
    `runtime/data/*.jsonl`. Mesure du 18/11/2026 : ces rubans commencent au **17/11 18:35**, alors
    que le coffre porte `bbo` et `book_l2` depuis le **26/10**. Une phase 1 branchee sur les rubans
    locaux prepare donc du vide pour toutes les tranches anterieures au 17/11 -- et rend
    honnetement `0/0`, ce qui ressemble a « pas de carnets » alors que la vraie cause est « pas
    regarde au bon endroit ».

    LE FILTRAGE SE FAIT EN FLUX, jamais apres. On ne materialise que les carnets retenus : c'est ce
    qui permet de traverser 111 millions de lignes de `bbo` sans les accumuler. Si on chargeait
    pour filtrer ensuite, l'economie de la phase 1 serait perdue d'avance.
    """
    from hl_observer.backtesting import coffre_tranches

    racine = Path(racine)
    index = racine / "runtime/coffre_certifie/LOCAL_INDEX.json"
    if not index.exists():
        return {}, {"status": "COFFRE_ABSENT", "chemin": str(index)}

    brut = json.loads(index.read_text(encoding="utf-8"))
    shards_tous = brut.get("shards") or brut.get("entrees") or []
    if isinstance(shards_tous, dict):
        shards_tous = list(shards_tous.values())

    # Les instants de signal, par coin, pour filtrer au vol.
    cibles: dict[str, list[int]] = {}
    if instants_par_coin:
        cibles = {str(k): sorted(int(x) for x in v) for k, v in instants_par_coin.items()}

    gardes: dict[str, list[dict[str, Any]]] = {}
    par_famille: dict[str, dict[str, int]] = {}
    for famille in familles:
        choix = coffre_tranches.selectionner(
            shards_tous, famille=famille, coins=list(coins),
            debut_ms=debut_ms - fenetre_ms, fin_ms=fin_ms)
        shards = choix.get("shards") or choix.get("retenus") or []
        if not shards:
            par_famille[famille] = {"shards": 0, "lus": 0, "gardes": 0}
            continue
        horloge = coffre_tranches.horloge_de(famille)
        lus = retenus = 0
        for ligne in coffre_tranches.flux(
            racine, shards, famille=famille, coins=list(coins),
            debut_ms=debut_ms - fenetre_ms, fin_ms=fin_ms, verifier_sha=False,
        ):
            lus += 1
            coin = str(ligne.get("coin") or ligne.get("symbole") or "")
            ts = ligne.get(horloge, ligne.get("ts_ms"))
            if not coin or ts is None:
                continue
            ts = int(ts)
            instants = cibles.get(coin)
            if instants is not None:
                i = bisect.bisect_left(instants, ts)
                if not (i < len(instants) and instants[i] - ts <= fenetre_ms):
                    continue
            carnet = dict(ligne)
            carnet["ts_ms"] = ts
            carnet.setdefault("coin", coin)
            carnet["_famille_coffre"] = famille
            gardes.setdefault(coin, []).append(carnet)
            retenus += 1
        par_famille[famille] = {"shards": len(shards), "lus": lus, "gardes": retenus}

    for liste in gardes.values():
        liste.sort(key=lambda c: int(c["ts_ms"]))
    audit = {
        "status": "LU_DEPUIS_LE_COFFRE",
        "familles": par_famille,
        "lignes_lues": sum(v["lus"] for v in par_famille.values()),
        "carnets_gardes": sum(v["gardes"] for v in par_famille.values()),
        "coins_avec_carnets": len(gardes),
        "fenetre_ms": int(fenetre_ms),
    }
    return gardes, audit


def entrees_de_phase_2(
    chemin: str | Path,
    *,
    tranche: tuple[int, int] | None = None,
    dire: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Ce que le labo appelle pour sa PHASE 2 : relire au lieu de reconstruire.

    Vit ici et non dans le labo, parce que `copy_vault_local_lab` est deja au plafond de lignes que
    son invariant d'architecture lui accorde : y ajouter du code ferait grossir une dette que ce
    garde-fou existe pour contenir. Le labo n'appelle donc qu'une fonction.

    `tranche` est refuse : il borne une RECONSTRUCTION, alors qu'un corpus prepare est deja borne.
    Les combiner laisserait croire a un filtrage qui n'aurait pas lieu -- on leve plutot que de
    laisser passer un corpus dont personne ne connaitrait le perimetre.
    """
    if tranche is not None:
        raise ValueError(
            "corpus_prepare et tranche s'excluent : le premier lit un corpus deja borne, la "
            "seconde borne une reconstruction. Les combiner laisserait croire a un filtrage "
            "qui n'aurait pas lieu."
        )
    parler = dire if callable(dire) else (lambda _message: None)
    parler("Phase 2 : relecture des tranches preparees (aucune reconstruction)")
    metaordres, carnets, audit = charger_tranches_preparees(Path(chemin))
    parler(
        f"Phase 2 : {audit['tranches_chargees']} tranche(s), {audit['metaordres']} metaordres, "
        f"{audit['carnets']} carnets sur {audit['coins']} coin(s)"
    )
    return metaordres, carnets, audit


class TranchePreparéeInvalide(RuntimeError):
    """Une tranche preparee manque, est incomplete, ou ne correspond plus a son empreinte."""


def charger_tranches_preparees(racine: Path) -> tuple[
    list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any]
]:
    """PHASE 2 : relit toutes les tranches preparees et les fusionne.

    REFUSE plutot que de deviner. Un manifeste manquant, un format inconnu, une empreinte qui ne
    correspond plus : on leve. Charger neuf tranches sur dix donnerait un corpus plus petit que
    prevu, et un corpus plus petit sans le dire est la meilleure façon de fabriquer un faux
    resultat -- c'est exactement ce que la phase 2 existe pour empecher.

    Les metaordres sont dedupliques sur (coin, signal_ts_ms, side, notional) : deux tranches
    voisines peuvent se recouvrir, et compter deux fois le meme signal gonflerait le corpus.
    """
    dossiers = sorted(p for p in racine.iterdir() if p.is_dir()) if racine.exists() else []
    if not dossiers:
        raise TranchePreparéeInvalide(f"aucune tranche preparee sous {racine}")

    metaordres: list[dict[str, Any]] = []
    carnets: dict[str, list[dict[str, Any]]] = {}
    vus: set[tuple] = set()
    doublons = 0
    manifestes: list[dict[str, Any]] = []

    for dossier in dossiers:
        chemin_manifeste = dossier / MANIFESTE
        if not chemin_manifeste.exists():
            raise TranchePreparéeInvalide(f"{dossier.name}: manifeste absent")
        manifeste = _lire_jsonl(chemin_manifeste)[0]
        if int(manifeste.get("format_version", -1)) != FORMAT_VERSION:
            raise TranchePreparéeInvalide(
                f"{dossier.name}: format {manifeste.get('format_version')} "
                f"au lieu de {FORMAT_VERSION}"
            )
        chemin_meta = dossier / FICHIER_METAORDRES
        chemin_carnets = dossier / FICHIER_CARNETS
        for chemin, cle in ((chemin_meta, "sha256_metaordres"),
                            (chemin_carnets, "sha256_carnets")):
            if not chemin.exists():
                raise TranchePreparéeInvalide(f"{dossier.name}: {chemin.name} absent")
            reel = _empreinte(chemin)
            if reel != manifeste.get(cle):
                raise TranchePreparéeInvalide(
                    f"{dossier.name}: {chemin.name} modifie depuis la phase 1 "
                    f"({reel[:12]} au lieu de {str(manifeste.get(cle))[:12]})"
                )

        for ordre in _lire_jsonl(chemin_meta):
            cle_ordre = (
                str(ordre.get("coin")),
                int(ordre.get("signal_ts_ms", -1)),
                str(ordre.get("side", "")),
                str(ordre.get("notional_usd", "")),
            )
            if cle_ordre in vus:
                doublons += 1
                continue
            vus.add(cle_ordre)
            metaordres.append(ordre)

        for bloc in _lire_jsonl(chemin_carnets):
            coin = str(bloc["coin"])
            carnets.setdefault(coin, []).extend(bloc["carnets"])

        manifestes.append(manifeste)

    metaordres.sort(key=lambda o: (int(o.get("signal_ts_ms", 0)), str(o.get("coin", ""))))
    for liste in carnets.values():
        liste.sort(key=lambda c: int(c["ts_ms"]))

    instants = [int(o["signal_ts_ms"]) for o in metaordres]
    audit = {
        "tranches_chargees": len(manifestes),
        "metaordres": len(metaordres),
        "metaordres_doublons_ecartes": doublons,
        "coins": len(carnets),
        "carnets": sum(len(v) for v in carnets.values()),
        "signal_ts_min_ms": min(instants) if instants else None,
        "signal_ts_max_ms": max(instants) if instants else None,
        "identites": [m.get("identite") for m in manifestes],
    }
    return metaordres, carnets, audit
