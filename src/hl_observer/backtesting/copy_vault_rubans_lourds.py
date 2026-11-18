"""Les trois rubans LOURDS du labo, produits en flux depuis les deux tiers du coffre.

POURQUOI CE MODULE EXISTE — MESURE DU 18/11/2026.
``materialize_safe_workspace`` dédoublonnait et triait les fills et les carnets dans des
dictionnaires avant de les écrire. Sur la fenêtre ouverte le 13/11, cela demande :

| famille          | lignes      | identités  | en dictionnaire | en flux  |
|------------------|-------------|------------|-----------------|----------|
| ``fills``        | 11 698 999  | 9 315 971  | ~32,2 Go        | 1,65 Go  |
| ``book_l2``      |  7 509 693  | 7 448 613  | ~28,3 Go        | 1,39 Go  |
| **total**        | **19,2 M**  | **16,8 M** | **~60,5 Go**    | **3 Go** |

Soixante gigaoctets demandés à une machine qui en a trente-deux : le labo s'arrêtait en
``MEMOIRE_CRITIQUE`` après 452 shards sur 5 570 et concluait « trop peu de jours » là où le tunnel
compte onze jours exploitables sur onze. Aucun réglage de seuil n'y pouvait rien.

CE QUE FAIT CE MODULE. Il expose les lignes des deux tiers comme des **générateurs rejouables**,
et confie l'écriture à ``rubans_tri_externe`` — deux passes, morceaux triés fusionnés en flux,
**octets identiques** à l'ancien chemin (contrat vérifié par 300 tirages aléatoires côté module,
et par un test d'intégration côté labo).

CE QU'IL NE CHANGE PAS, ET C'EST L'ESSENTIEL :

* les transformations restent celles du labo (``_fill_rows``, ``_book_row``) : ce module ne décode
  rien lui-même, il les appelle ;
* les filtres du tier LOCAL restent ceux du pont (fills datés d'un vault et d'un coin connus,
  carnets à deux horloges et cinq niveaux, adresses classées ``ARCHIVE`` écartées) ;
* la lecture du tier LOCAL passe par ``coffre_tranches.flux``, le point unique de lecture du
  coffre (déjà utilisé par le tunnel et le plan de fouille) : c'est lui qui vérifie les SHA,
  applique la fenêtre et compte les shards refusés — on ne duplique pas cette logique ;
* les compteurs d'audit ne sont alimentés qu'à la PREMIÈRE passe (``compter=False`` ensuite) :
  deux passes compteraient deux fois chaque enveloppe rejetée.

PAPER / LECTURE SEULE : aucun ordre, aucun réseau, aucune écriture dans les shards.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting import coffre_tranches as TR
from hl_observer.backtesting import rubans_tri_externe as RT
from hl_observer.collection.forward_poll_fills import is_causal_live_source

SCHEMA = "hypersmart.copy_vault_rubans_lourds.v1"

#: Familles SAFE qui portent des fills, et le drapeau ``isSnapshot`` attendu de chacune.
FAMILLES_SAFE_FILLS = {"copy_vault_fills": False, "copy_vault_snapshot": True}
#: Famille SAFE des carnets.
FAMILLE_SAFE_CARNETS = "copy_vault_l2"
#: Familles du tier LOCAL correspondantes.
FAMILLES_LOCALES_FILLS = ("fills_forward", "fills_backfill", "snapshot")
FAMILLE_LOCALE_CARNETS = "book_l2"

#: Les trois rubans produits ici, et le filtre qui décide des lignes de chacun.
RUBAN_FILLS_HISTORIQUES = "vault_fills.jsonl"
RUBAN_FILLS_DIRECTS = "vault_fills_live.jsonl"
RUBAN_CARNETS = "copy_vault_l2_tape.jsonl"


def identite_fill(ligne: Mapping[str, Any]) -> tuple[Any, ...]:
    """L'identité d'un fill, telle que le labo la compare.

    Tous les champs sont lus par ``get`` : c'est ce que fait le labo pour les lignes du tier LOCAL,
    dont le pont ne garantit que ``vault``, ``coin`` et ``ts_ms``. Pour les lignes SAFE, où tous
    les champs existent, le résultat est identique.
    """
    return (ligne.get("vault"), ligne.get("coin"), ligne.get("ts_ms"), ligne.get("tid"),
            ligne.get("hash"), ligne.get("oid"), ligne.get("px"), ligne.get("sz"),
            ligne.get("signe"))


def tri_fill(ligne: Mapping[str, Any]) -> tuple[Any, ...]:
    return (ligne["ts_ms"], ligne["vault"], str(ligne.get("tid")))


#: Rangs de préférence, du plus fort au plus faible. Ils reproduisent EXACTEMENT ce que faisait
#: le labo : les lignes SAFE entraient avec remplacement d'un snapshot par un fill vu en direct,
#: puis les lignes LOCAL entraient par ``setdefault`` — donc sans jamais déloger une ligne SAFE,
#: pas même un snapshot. Confondre les trois rangs changerait le contenu du ruban.
RANG_SAFE_DIRECT = 0
RANG_SAFE_SNAPSHOT = 1
RANG_LOCAL = 2


def preference_fill(ligne: Mapping[str, Any]) -> int:
    """Rang de préférence d'un fill : SAFE en direct, puis SAFE en snapshot, puis LOCAL."""
    if ligne.get("provenance_tier") == "LOCAL":
        return RANG_LOCAL
    return RANG_SAFE_SNAPSHOT if ligne.get("isSnapshot") else RANG_SAFE_DIRECT


def preference_carnet(ligne: Mapping[str, Any]) -> int:
    """Même règle pour les carnets : une ligne SAFE n'est jamais délogée par une ligne LOCAL."""
    return RANG_LOCAL if ligne.get("provenance_tier") == "LOCAL" else RANG_SAFE_DIRECT


def est_un_fill_historique(ligne: Mapping[str, Any]) -> bool:
    """Le ruban des snapshots : ``isSnapshot`` vaut VRAIMENT ``True``, pas « quelque chose de vrai »."""
    return ligne.get("isSnapshot") is True


def est_un_fill_direct_causal(ligne: Mapping[str, Any]) -> bool:
    """Le ruban du direct : non-snapshot ET source causale (``LIVE_WS`` ou ``LIVE_POLL``).

    Une ligne non-snapshot d'une source non causale n'entre dans AUCUN ruban : elle compte dans
    ``unique_fills`` sans être rejouée. C'est la règle du labo, et elle est volontaire.
    """
    return ligne.get("isSnapshot") is False and is_causal_live_source(ligne.get("source"))


def identite_carnet(ligne: Mapping[str, Any]) -> tuple[Any, ...]:
    """L'identité d'un carnet. Lève ``KeyError`` si un champ manque, comme le labo."""
    return (ligne["coin"], ligne["received_at_ms"], ligne["exchange_ts_ms"],
            ligne["bid"], ligne["ask"], ligne["bids5"], ligne["asks5"])


def tri_carnet(ligne: Mapping[str, Any]) -> tuple[Any, ...]:
    return (ligne["received_at_ms"], ligne["coin"])


def _metadonnees_de_l_asset(asset: Mapping[str, Any], index_sha: str) -> dict[str, Any]:
    """Les arguments de provenance que les transformations du labo attendent."""
    manifeste = asset.get("manifest")
    synchronisation = (manifeste.get("synchronization")
                       if isinstance(manifeste, Mapping) else None)
    connexions = (synchronisation.get("connection_ids")
                  if isinstance(synchronisation, Mapping) else None)
    attendue = (connexions[0] if isinstance(connexions, list) and len(connexions) == 1
                and isinstance(connexions[0], str) else None)
    return {
        "source_dataset_id": str(asset.get("dataset_id") or "") or None,
        "source_shard_sha256": str(asset.get("sha256") or "") or None,
        "source_catalog_sha256": str(index_sha or ""),
        "source_continuity_proven": not bool(asset.get("_heartbeat_evidence_missing")),
        "expected_connection_id": attendue,
    }


def lignes_safe(assets: Sequence[tuple[Path, Mapping[str, Any]]], *, familles: Mapping[str, Any] | Sequence[str],
                index_sha: str, transformer: Callable[..., Any], charger_enveloppes: Callable[[Path], Any],
                payload_audit: Counter[str] | None = None,
                compteurs: dict[str, int] | None = None,
                rend_une_liste: bool = True) -> Iterator[dict[str, Any]]:
    """Les lignes transformées du tier SAFE pour les familles demandées. REJOUABLE.

    ``transformer`` est la fonction du labo (``_fill_rows`` ou ``_book_row``) : ce module ne décode
    aucun format lui-même. ``compteurs`` reçoit les totaux secondaires que le labo publie
    (enveloppes lues, shards de snapshots, observations historiques, enveloppes rejetées).
    """
    compteurs = compteurs if compteurs is not None else {}
    for cle in ("raw_frames", "historical_snapshot_shards", "historical_fill_observations",
                "wrapper_rejections"):
        compteurs.setdefault(cle, 0)
    for chemin, asset in assets:
        famille = str(asset.get("family") or "")
        if famille not in familles:
            continue
        if famille == "copy_vault_snapshot":
            compteurs["historical_snapshot_shards"] += 1
        meta = _metadonnees_de_l_asset(asset, index_sha)
        try:
            for enveloppe in charger_enveloppes(chemin):
                compteurs["raw_frames"] += 1
                if famille == "copy_vault_snapshot":
                    donnees = enveloppe["_raw"].get("data")
                    brut = donnees.get("fills") if isinstance(donnees, Mapping) else None
                    if (isinstance(donnees, Mapping) and donnees.get("isSnapshot") is True
                            and isinstance(brut, list)):
                        compteurs["historical_fill_observations"] += len(brut)
                if rend_une_liste:
                    produit = transformer(enveloppe, family=famille, audit=payload_audit, **meta)
                    yield from produit
                else:
                    ligne = transformer(enveloppe, **meta)
                    if ligne:
                        yield ligne
                    elif payload_audit is not None:
                        payload_audit["INVALID_OR_NONCAUSAL_L2_REJECTED"] += 1
        except (OSError, EOFError, ValueError, TypeError, json.JSONDecodeError):
            compteurs["wrapper_rejections"] += 1


def _ligne_locale_valide(famille: str, ligne: Mapping[str, Any]) -> bool:
    """Les filtres du pont LOCAL, à l'identique : ni plus souples, ni plus stricts."""
    if famille in FAMILLES_LOCALES_FILLS:
        return bool(isinstance(ligne.get("ts_ms"), int) and ligne.get("vault") and ligne.get("coin"))
    if famille == FAMILLE_LOCALE_CARNETS:
        if not (isinstance(ligne.get("received_at_ms"), int)
                and isinstance(ligne.get("exchange_ts_ms"), int)
                and ligne.get("coin") and ligne.get("bids5") and ligne.get("asks5")):
            return False
        # Le labo ignore un carnet dont il ne peut pas CALCULER l'identité (bid/ask absents,
        # niveaux non itérables) : il l'écarte par `except (KeyError, TypeError): continue`.
        try:
            identite_carnet(ligne)
            tuple(tuple(n) for n in ligne["bids5"])
            tuple(tuple(n) for n in ligne["asks5"])
        except (KeyError, TypeError):
            return False
        return True
    return False


def lignes_locales(root: str | Path, shards: Sequence[Mapping[str, Any]], *, famille: str,
                   depuis_ms: int | None = None, jusqu_ms: int | None = None,
                   archivees: set[str] | None = None,
                   compteurs: dict[str, int] | None = None,
                   flux: Callable[..., Iterator[Mapping[str, Any]]] | None = None,
                   ) -> Iterator[dict[str, Any]]:
    """Les lignes du tier LOCAL pour une famille, en flux et REJOUABLE.

    La lecture, la vérification des SHA et la fenêtre sont déléguées à ``coffre_tranches.flux`` —
    le point unique de lecture du coffre, déjà utilisé par le tunnel et le plan de fouille. Ce
    module n'y ajoute que les filtres du pont et l'étiquette de provenance.
    """
    compteurs = compteurs if compteurs is not None else {}
    for cle in ("lignes_lues", "lignes_refusees", "fills_archive"):
        compteurs.setdefault(cle, 0)
    lecteur = flux if flux is not None else TR.flux
    selection = TR.selectionner(shards, famille=famille, debut_ms=depuis_ms, fin_ms=jusqu_ms)
    for ligne in lecteur(root, selection["retenus"], famille=famille,
                         debut_ms=depuis_ms, fin_ms=jusqu_ms, compteurs={}):
        compteurs["lignes_lues"] += 1
        if archivees and famille in FAMILLES_LOCALES_FILLS:
            if str(ligne.get("vault") or "").lower() in archivees:
                compteurs["fills_archive"] += 1
                continue
        if not _ligne_locale_valide(famille, ligne):
            compteurs["lignes_refusees"] += 1
            continue
        yield {**ligne, "provenance_tier": "LOCAL"}


def ecrire_rubans_lourds(dossier: str | Path, *, fabrique_fills: Callable[[], Iterator[Mapping[str, Any]]],
                         fabrique_carnets: Callable[[], Iterator[Mapping[str, Any]]],
                         dossier_temporaire: str | Path | None = None,
                         lignes_par_morceau: int = RT.LIGNES_PAR_MORCEAU,
                         ) -> dict[str, Any]:
    """Écrit les trois rubans lourds et rend un bilan par ruban.

    Les deux rubans de fills sortent du MÊME corpus dédoublonné : la déduplication est faite une
    seule fois, et chaque ruban applique ensuite son filtre. Dédoublonner séparément compterait
    deux fois un fill présent sous les deux formes.
    """
    dossier = Path(dossier)
    temporaire = Path(dossier_temporaire) if dossier_temporaire is not None else dossier / ".tri"
    selection_fills = RT.gagnants(fabrique_fills, cle_identite=identite_fill,
                                  rang_preference=preference_fill)
    bilans: dict[str, Any] = {"schema_version": SCHEMA, "fills": {}, "carnets": {}}
    # Les deux rubans de fills s'écrivent en UNE passe : relire onze millions de lignes pour
    # chacun coûtait 709 s de plus à la mesure du 18/11/2026.
    cibles = [
        (dossier / RUBAN_FILLS_HISTORIQUES, est_un_fill_historique),
        (dossier / RUBAN_FILLS_DIRECTS, est_un_fill_direct_causal),
    ]
    par_chemin = RT.ecrire_rubans_tries(
        cibles, fabrique_fills, cle_tri=tri_fill, cle_identite=identite_fill,
        rang_preference=preference_fill, selection=selection_fills,
        dossier_temporaire=temporaire, lignes_par_morceau=lignes_par_morceau)
    for chemin, _garder in cibles:
        bilans["fills"][chemin.name] = par_chemin[str(chemin)]
    bilans["carnets"][RUBAN_CARNETS] = RT.ecrire_ruban_trie(
        dossier / RUBAN_CARNETS, fabrique_carnets, cle_tri=tri_carnet,
        cle_identite=identite_carnet, rang_preference=preference_carnet,
        dossier_temporaire=temporaire, lignes_par_morceau=lignes_par_morceau)
    bilans["identites_fills"] = selection_fills["identites"]
    bilans["doublons_fills"] = selection_fills["doublons"]
    return bilans


__all__ = ["SCHEMA", "FAMILLES_SAFE_FILLS", "FAMILLE_SAFE_CARNETS", "FAMILLES_LOCALES_FILLS",
           "FAMILLE_LOCALE_CARNETS", "RUBAN_FILLS_HISTORIQUES", "RUBAN_FILLS_DIRECTS",
           "RUBAN_CARNETS", "RANG_SAFE_DIRECT", "RANG_SAFE_SNAPSHOT", "RANG_LOCAL",
           "identite_fill", "tri_fill", "preference_fill", "preference_carnet", "identite_carnet",
           "est_un_fill_historique", "est_un_fill_direct_causal",
           "tri_carnet", "lignes_safe", "lignes_locales", "ecrire_rubans_lourds"]
