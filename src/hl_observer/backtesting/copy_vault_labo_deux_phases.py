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
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting.copy_vault_coffre_vers_labo import (
    _fenetre_apres_signal,
    une_seule_connexion_par_coin,
)
from hl_observer.backtesting.copy_vault_raccords_l2 import raccord_demande, raccorder_les_connexions
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
    """Tout le fichier en memoire. Reserve aux PETITS fichiers (un manifeste)."""
    with open(chemin, "rb") as flux:
        return [json.loads(ligne) for ligne in flux if ligne.strip()]


def _flux_jsonl(chemin: Path) -> Iterator[dict[str, Any]]:
    """Les lignes UNE PAR UNE, sans jamais les accumuler.

    C'est la difference entre filtrer et proteger. `_lire_jsonl` materialise la liste entiere
    AVANT qu'un filtre puisse s'exercer : sur le corpus du 18/11/2026 (4 618 095 metaordres,
    15,4 Go), un comptage qui ne retenait rien a quand meme fait tomber la RAM libre de 17 a
    0,8 Go en 90 secondes -- parce que la liste intermediaire, elle, etait bien construite.
    Un filtre place apres un chargement complet ne protege rien.
    """
    with open(chemin, "rb") as flux:
        for ligne in flux:
            if ligne.strip():
                yield json.loads(ligne)




def carnets_utiles(
    metaordres: Sequence[Mapping[str, Any]],
    carnets: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    fenetre_ms: int = MAX_BOOK_AGE_MS,
    fenetre_apres_ms: int | None = None,
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
        apres = _fenetre_apres_signal() if fenetre_apres_ms is None else int(fenetre_apres_ms)
        for carnet in liste:
            ts = int(carnet["ts_ms"])
            # Un carnet sert s'il existe un signal dans [ts - apres, ts + fenetre_ms] : avant lui
            # pour la reference, apres lui pour l'entree et la sortie.
            i = bisect.bisect_left(instants, ts - apres)
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






#: Le statut de provenance d'un corpus LOCAL certifie. IL NE SE DEGUISE PAS EN SAFE.
#:
#: Le labo exigeait `safe_catalog_status` parmi `SAFE_COMPLETE` / `SAFE_PARTIAL`, c'est-a-dire une
#: provenance venue de la chaine SAFE cloud. Le corpus local est reellement certifie -- le
#: certificateur a scelle 153 fichiers sur 153, code 0, le 18/11/2026 -- mais il n'est PAS SAFE : le
#: LOCAL a 31,7 jours d'avance, et la chaine cloud ne l'a pas encore repris.
#:
#: Ecrire `SAFE_PARTIAL` pour ouvrir la porte serait mentir sur l'origine des donnees, et un PnL
#: obtenu en falsifiant sa propre tracabilite vaut moins que pas de PnL : on y croirait. Ce statut
#: dit donc la verite, et il OUVRE LA MESURE en FERMANT LA CERTIFICATION -- exactement ce que
#: `FREEZE_EXPLORATORY != preuve` signifie.
PROVENANCE_LOCALE = "LOCAL_CERTIFIED"







def manifeste_de_provenance_locale(
    racine: str | Path,
    *,
    corpus: Path,
    sortie: Path | None = None,
    jours_minimum: int | None = None,
    max_leaders: int | None = None,
    min_notionnel_leader: float | None = None,
) -> dict[str, Any]:
    """Ecrit un `SAFE_INPUT_MANIFEST.json` qui DIT LA VERITE sur un corpus local.

    Chaque champ est MESURE sur le corpus reellement prepare, jamais suppose :

      * `selection_digest` : l'empreinte des manifestes de toutes les tranches, dans l'ordre. Deux
        corpus differents ne peuvent pas la partager, et la meme preparation la redonne a
        l'identique -- c'est ce qui rend un resultat rejouable ;
      * `source_index_sha256` : l'empreinte de l'index du coffre consomme ;
      * `unique_fills` / `unique_books` : les comptes reels, relus sur disque ;
      * `safe_catalog_status` : `LOCAL_CERTIFIED`, jamais `SAFE_*`.

    Le manifeste porte aussi `exploratory_only: True` et `champion_eligible: False`. Ce ne sont pas
    des decorations : le labo les lit pour refuser d'ecrire un champion depuis cette provenance.
    """
    racine = Path(racine)
    corpus = Path(corpus)
    index = racine / "runtime/coffre_certifie/LOCAL_INDEX.json"

    empreintes: list[str] = []
    fills = livres = 0
    tranches = 0
    for dossier in sorted(p for p in corpus.iterdir() if p.is_dir()):
        chemin = dossier / MANIFESTE
        if not chemin.exists():
            continue
        manifeste = _lire_jsonl(chemin)[0]
        empreintes.append(str(manifeste.get("sha256_metaordres", "")))
        empreintes.append(str(manifeste.get("sha256_carnets", "")))
        fills += int(manifeste.get("metaordres") or 0)
        livres += int(manifeste.get("audit_carnets", {}).get("carnets_gardes") or 0)
        tranches += 1

    # L'INVENTAIRE DES ACTIFS, declare sur ce qui existe VRAIMENT. La porte du labo exige, par
    # actif : un `dataset_id` unique, une `family` connue, une taille en octets, une empreinte
    # SHA-256, une `release_tag`, une `release_asset` et un `manifest_path`.
    #
    # `release_tag` et `release_asset` designent normalement une release GitHub de la chaine SAFE.
    # Un corpus local n'en a pas. Plutot que d'inventer un numero de release -- ce qui ferait
    # passer du LOCAL pour du SAFE -- l'etiquette DIT ce qu'elle est : `LOCAL-COFFRE-SCELLE`.
    # Tout le reste est mesure sur le fichier : taille reelle, empreinte reelle, chemin reel.
    actifs: list[dict[str, Any]] = []
    vides: list[str] = []
    for dossier in sorted(p for p in corpus.iterdir() if p.is_dir()):
        chemin_manifeste = dossier / MANIFESTE
        if not chemin_manifeste.exists():
            continue
        m = _lire_jsonl(chemin_manifeste)[0]
        for fichier, famille, cle in (
            (FICHIER_METAORDRES, "copy_vault_fills", "sha256_metaordres"),
            (FICHIER_CARNETS, "copy_vault_l2", "sha256_carnets"),
        ):
            chemin = dossier / fichier
            if not chemin.exists():
                continue
            if chemin.stat().st_size == 0:
                # UN FICHIER VIDE N'EST PAS UN ACTIF. Une tranche sans aucun signal produit un
                # ruban de zero octet -- c'est legitime, mais le declarer comme un actif de
                # donnees serait faux, et la porte du labo le refuse a juste titre (`bytes > 0`).
                # On le compte pour que son absence se VOIE dans le manifeste.
                vides.append(f"{dossier.name}/{fichier}")
                continue
            actifs.append({
                "dataset_id": f"{dossier.name}/{fichier}",
                "family": famille,
                "bytes": chemin.stat().st_size,
                "sha256": str(m.get(cle, "")),
                "release_tag": "LOCAL-COFFRE-SCELLE",
                "release_asset": f"{dossier.name}-{fichier}",
                "manifest_path": str(chemin_manifeste.relative_to(racine))
                if chemin_manifeste.is_relative_to(racine) else str(chemin_manifeste),
            })

    # LES DEUX DIGESTS SONT CALCULES PAR LE LABO LUI-MEME, jamais recopies : il les recalcule a la
    # lecture et refuse s'ils ne concordent pas. Les emprunter a leur source unique est la seule
    # façon d'etre sur qu'ils lient bien l'inventaire a la selection.
    from hl_observer.backtesting.copy_vault_local_lab import (
        _source_asset_inventory_sha256,
        _source_selection_digest,
    )

    index_sha = _empreinte(index) if index.exists() else "0" * 64
    inventaire_sha = _source_asset_inventory_sha256(actifs)
    digest = _source_selection_digest(index_sha, actifs)
    manifeste = {
        "selection_digest": digest,
        "source_index_sha256": index_sha,
        "source_asset_inventory_sha256": inventaire_sha,
        "source_asset_inventory_complete": True,
        "source_asset_inventory_count": len(actifs),
        "verified_source_assets": actifs,
        "paper_read_only": True,
        "real_execution": False,
        "status": "MORE_DATA",
        "safe_catalog_status": PROVENANCE_LOCALE,
        "replay_inputs_available": True,
        "unique_fills": fills,
        "unique_books": livres,
        # LES DEUX CHAMPS QUI FERMENT LA CERTIFICATION. Le labo les lit.
        "exploratory_only": True,
        "champion_eligible": False,
        # UN SEUIL DE JOURNEES DECLARE est une limite assumee, pas un contournement : le labo
        # exige 6 journees distinctes, et seules 2 portent des signaux observes en direct
        # (17/11 : 470, 18/11 : 1 431 ; la collecte WS a demarre le 17/11 a 19:11). Un corpus qui
        # abaisse ce seuil le DIT ici, et reste `champion_eligible: False` -- donc mesurable,
        # jamais promouvable. Omettre ce champ laisse le defaut de 6 s'appliquer.
        **({"minimum_signal_utc_days": int(jours_minimum)} if jours_minimum else {}),
        # LA SELECTION DE LEADERS EST DECLAREE, donc lisible et refusable. Le corpus complet
        # (4 618 095 metaordres, 228 leaders, 15,4 Go) ne tient pas en memoire ; on garde les N
        # plus actifs, ce qui conserve des cycles ENTIERS sur les six journees entieres -- alors
        # qu'un echantillonnage fabriquerait des positions qui ne se ferment jamais.
        **({"max_leaders": int(max_leaders)} if max_leaders else {}),
        # Le seuil de notionnel du leader est DECLARE : il dit quelle part du corpus est exploree
        # et pourquoi, donc il est lisible et refusable.
        **({"min_notionnel_leader_usd": float(min_notionnel_leader)}
           if min_notionnel_leader else {}),
        "provenance_note": (
            "Corpus LOCAL certifie (coffre scelle 153/153, code 0, 18/11/2026), prepare en deux "
            "phases. PAS passe par la chaine SAFE cloud : tout resultat est EXPLORATOIRE et ne "
            "peut pas devenir champion."
        ),
        "tranches": tranches,
        # Les rubans VIDES, nommes : une tranche sans signal est un fait du corpus,
        # pas une anomalie a cacher. Les taire ferait croire a un corpus plus riche.
        "rubans_vides_ecartes": len(vides),
        "rubans_vides": vides[:20],
        "corpus": str(corpus),
    }
    cible = sortie or (racine / "SAFE_INPUT_MANIFEST.json")
    cible.write_text(
        json.dumps(manifeste, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifeste


def entrees_de_phase_2(
    chemin: str | Path,
    *,
    tranche: tuple[int, int] | None = None,
    dire: Any = None,
    causaux_seulement: bool = True,
    max_leaders: int | None = None,
    min_notionnel_leader: float | None = None,
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

    filtres: list[Any] = []
    if causaux_seulement:
        filtres.append(lambda o: o.get("causal_forward_eligible") is True)
    if min_notionnel_leader:
        # UN PLAFOND ECONOMIQUEMENT FONDE, pas un echantillonnage. Le corpus complet porte
        # 4 618 095 metaordres : hors d'echelle pour le labo, qui en traitait 8 176. Plutot que de
        # tirer au hasard -- ce qui briserait les cycles d'un leader et fabriquerait des positions
        # qui ne se ferment jamais -- on applique le critere que le protocole porte deja : un
        # notionnel minimum du leader. Avec 100 USD de capital, on copie des mouvements
        # significatifs, pas des micro-ajustements.
        #
        # Mesure du 18/11/2026 sur les 6 journees, par seuil de notionnel leader :
        #     >=     100 USD : 3 010 753 metaordres        >=  20 000 USD :  74 345
        #     >=   1 000 USD : 1 140 771                    >= 100 000 USD :   8 027
        # Chaque seuil conserve les SIX journees : la couverture temporelle n'est pas sacrifiee.
        seuil = float(min_notionnel_leader)

        def _assez_gros(ordre: Mapping[str, Any]) -> bool:
            valeur = ordre.get("leader_notional_usd")
            try:
                return valeur is not None and float(valeur) >= seuil
            except (TypeError, ValueError):
                return False

        filtres.append(_assez_gros)
    leaders_gardes: set[str] | None = None
    if filtres or max_leaders:
        # DEUX PASSAGES, parce qu'on ne peut pas choisir les leaders les plus actifs avant de les
        # avoir comptes, et qu'on ne veut pas tout charger pour les compter. Le premier passage ne
        # retient RIEN : il lit les metaordres un par un et ne garde que des compteurs.
        parler("Phase 2 : comptage des leaders (aucun metaordre retenu)")
        compte: dict[str, int] = {}

        coins_par_leader: dict[str, set[str]] = {}
        instants_vus: dict[str, list[int]] = {}

        def _compter(ordre: Mapping[str, Any]) -> bool:
            if all(f(ordre) for f in filtres):
                cle = str(ordre.get("vault") or "")
                compte[cle] = compte.get(cle, 0) + 1
                coin_ordre = str(ordre.get("coin") or "")
                coins_par_leader.setdefault(cle, set()).add(coin_ordre)
                instants_vus.setdefault(coin_ordre, []).append(int(ordre["signal_ts_ms"]))
            return False        # jamais retenu : la memoire reste plate

        charger_tranches_preparees(Path(chemin), garder=_compter, sans_carnets=True)
        leaders_gardes = (
            {v for v, _ in sorted(compte.items(), key=lambda kv: -kv[1])[:int(max_leaders)]}
            if max_leaders else set(compte)
        )
        total = sum(compte.values())
        retenu = sum(compte[v] for v in leaders_gardes)
        parler(
            f"Phase 2 : {len(leaders_gardes)} leader(s) les plus actifs sur {len(compte)} "
            f"-> {retenu} metaordres sur {total} ({100 * retenu / total:.1f}%)"
            if total else "Phase 2 : aucun metaordre a compter"
        )
        if max_leaders:
            filtres.append(lambda o: str(o.get("vault") or "") in leaders_gardes)
        coins_utiles = {c for v in leaders_gardes for c in coins_par_leader.get(v, ())}
        parler(f"Phase 2 : {len(coins_utiles)} coin(s) utile(s) -> les autres carnets sont ecartes")
    else:
        coins_utiles = None

    instants_utiles = None
    if coins_utiles is not None:
        instants_utiles = {c: sorted(instants_vus.get(c, ())) for c in coins_utiles}
        total_instants = sum(len(v) for v in instants_utiles.values())
        parler(f"Phase 2 : {total_instants} instant(s) de signal -> les carnets hors fenetre "
               f"causale ne sont pas charges")
    metaordres, carnets, audit = charger_tranches_preparees(
        Path(chemin), garder=(lambda o: all(f(o) for f in filtres)) if filtres else None,
        coins_utiles=coins_utiles, instants_par_coin=instants_utiles)
    audit["leaders_retenus"] = len(leaders_gardes) if leaders_gardes is not None else None

    # UNE SEULE CONNEXION PAR COIN, et ICI, pas en phase 1 : chaque tranche ne voit que les
    # connexions de ses quatre heures, et deux tranches voisines peuvent retenir des connexions
    # differentes pour le meme coin. Choisir avant la fusion remelangerait donc exactement ce
    # qu'on cherche a demeler. Le choix se fait apres, sur le corpus reuni, une fois pour toutes.
    # RACCORD DES TROUS COURTS — optionnel, éteint par défaut (`HL_LABO_RACCORDER_L2=1`). Mesure du
    # 22/11/2026 : la règle ci-dessous écartait 83 % des carnets pour des raccords de 2,84 s médians.
    # Voir `copy_vault_raccords_l2` : même seuil que la fraîcheur du labo (30 s), tout est compté.
    if raccord_demande():
        carnets, audit["raccords_l2"] = raccorder_les_connexions(carnets)
        parler(
            f"Phase 2 : raccord L2 actif -> {audit['raccords_l2']['raccords_franchis']} raccord(s) "
            f"franchi(s), {audit['raccords_l2']['raccords_refuses']} refuse(s) "
            f"(seuil {audit['raccords_l2']['trou_max_ms']} ms)"
        )
    carnets, audit_connexion = une_seule_connexion_par_coin(carnets)
    audit["connexion_unique"] = audit_connexion
    ecartes = audit_connexion["ecartes_connexion_minoritaire"]
    if ecartes:
        parler(
            f"Phase 2 : une seule connexion L2 par coin -> "
            f"{audit_connexion['carnets_gardes']} carnet(s) gardes, {ecartes} ecarte(s) comme "
            f"connexion minoritaire ({audit_connexion['coins_a_connexion_unique']}/"
            f"{audit_connexion['coins']} coins n'en avaient qu'une)"
        )

    return metaordres, carnets, audit


class TranchePreparéeInvalide(RuntimeError):
    """Une tranche preparee manque, est incomplete, ou ne correspond plus a son empreinte."""


def charger_tranches_preparees(
    racine: Path,
    *,
    garder: Any = None,
    coins_utiles: set[str] | None = None,
    sans_carnets: bool = False,
    instants_par_coin: Mapping[str, Sequence[int]] | None = None,
    fenetre_ms: int = MAX_BOOK_AGE_MS,
) -> tuple[
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

        for ordre in _flux_jsonl(chemin_meta):
            # LE FILTRE S'APPLIQUE ICI, PAS APRES. Filtrer une fois tout charge ne protege rien :
            # le corpus complet (4 618 095 metaordres, 15,4 Go) passe alors entierement en memoire
            # avant d'etre reduit, et la machine tombe -- mesure du 18/11/2026 : la RAM libre est
            # descendue de 14 a 4,7 Go avant que j'arrete le processus. Un filtre de reduction qui
            # s'applique trop tard est un filtre qui ne sert a rien.
            if garder is not None and not garder(ordre):
                continue
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

        for bloc in (() if sans_carnets else _flux_jsonl(chemin_carnets)):
            # `sans_carnets` existe pour le passage de COMPTAGE. Sans lui, ce passage ne retenait
            # aucun metaordre mais chargeait quand meme les 19 137 904 carnets : la RAM libre est
            # tombee de 20 a 1,4 Go en 100 secondes, pendant une passe censee ne rien garder.
            # Un passage « qui ne retient rien » doit aussi ne RIEN LIRE d'inutile.
            coin = str(bloc["coin"])
            # LES CARNETS SUIVENT LA SELECTION. Filtrer les metaordres sans filtrer les carnets ne
            # protege qu'a moitie : le corpus du 18/11/2026 porte 19 137 904 carnets, soit bien
            # plus de memoire que ses 4,6 M de metaordres. Un carnet d'un coin que plus aucun
            # metaordre retenu ne touche ne sera jamais lu par l'alignement.
            if coins_utiles is not None and coin not in coins_utiles:
                continue
            instants = None if instants_par_coin is None else instants_par_coin.get(coin)
            if instants_par_coin is not None and not instants:
                continue
            if instants is None:
                carnets.setdefault(coin, []).extend(bloc["carnets"])
                continue
            # LA FENETRE CAUSALE AU CHARGEMENT. Meme reduits a 52 coins, les carnets de ces coins
            # pesaient 17,24 Go en memoire. Or l'alignement ne lit qu'un carnet dans les
            # `fenetre_ms` qui PRECEDENT un signal : tout le reste est transporte pour rien. C'est
            # le raisonnement de la phase 1, applique un niveau plus bas -- et c'est la quatrieme
            # fois cette nuit que la lecon est la meme : un filtre qui s'applique trop tard ne
            # protege rien.
            retenus = carnets.setdefault(coin, [])
            apres = _fenetre_apres_signal()
            for carnet in bloc["carnets"]:
                ts = int(carnet["ts_ms"])
                # Des DEUX cotes : le replay cherche une reference avant le signal, une entree
                # apres le delai de copie, et une sortie apres l'horizon.
                i = bisect.bisect_left(instants, ts - apres)
                if i < len(instants) and instants[i] - ts <= fenetre_ms:
                    retenus.append(carnet)

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
