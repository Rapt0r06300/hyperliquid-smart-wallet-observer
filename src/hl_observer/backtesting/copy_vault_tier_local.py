"""Chargement du tier LOCAL du coffre-fort certifié pour la recherche exploratoire du labo.

Lecture seule, SHA-256 revérifié (fail-closed). Les rangées sont étiquetées
``provenance_tier=LOCAL`` : elles nourrissent la recherche, jamais une preuve.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.collection.forward_poll_fills import CADENCE_ARCHIVE, cadence_plan, is_causal_live_source
from hl_observer.backtesting import copy_vault_fenetre_locale as _FENETRE

#: plan publié par l'étude de copiabilité : classe de chaque adresse suivie (voir ``cadence_plan``)
PLAN_DE_COLLECTE = Path("runtime") / "data" / "copy_vault_besoins_collecte.json"


#: familles du coffre LOCAL qui alimentent les fills de replay.
_COFFRE_FAMILLES_FILLS = {"fills_forward", "fills_backfill", "snapshot"}
#: familles LOCAL de SIGNAUX de contexte (PAS le replay PnL) : nouvelles observations
#: certifiées (liquidations, overshoots, OI/funding, prix, cross-venue, bougies). Elles
#: sont mises à DISPOSITION de la recherche exploratoire, séparées du calcul PnL SAFE.
_COFFRE_FAMILLES_SIGNAUX = {
    "liquidation", "overshoot", "asset_ctx", "allmids",
    "trades_marche", "candle", "position",
    # 2026-11-12 : flux AUPARAVANT collectés + certifiés mais JAMAIS chargés par le labo (gâchés).
    # Branchés comme signaux de contexte : disponibles à la recherche exploratoire (comptés sans coût
    # mémoire dans le labo principal via garder_signaux=False). Chacun a une valeur propre :
    "leader_orders",       # ordres EN ATTENTE des leaders -> intention, anticipation (copy_vault_order_intent)
    "funding_history",     # funding horaire LOCAL (plus de coins que le SAFE) -> coût de portage
    "vault_ledger",        # dépôts/retraits LOCAUX -> NAV as-of, détection de retrait
    "vault_portfolio",     # portefeuille complet des leaders (dex réunis) -> réplication par position
    "micro_bbo", "micro_l2", "micro_trades",   # microstructure fine -> OFI, lead-lag, horloges séparées
}


#: 16/11/2026 — FAMILLES EXCLUES AVEC MOTIF, et non laissées en limbe.
#:
#: Le chantier 10 de l'audit exige que toute famille du coffre soit « consommée avec un rôle
#: justifié OU explicitement exclue ». La matrice du coffre a trouvé `explorer_tx` dans un
#: troisième état : 196 shards, 7 914 792 lignes, 9 jours — indexée, et sans aucun chemin de
#: chargement ici. Son rôle EST documenté ailleurs (`tools/auditer_donnees_collectees.py` :
#: « découverte de leaders actifs — métadonnée, pas un signal de marché ») : c'est une source de
#: DÉCOUVERTE, pas une observation de marché datée au tick.
#:
#: On l'inscrit donc ici comme exclusion MOTIVÉE du pont de replay. L'exclure explicitement n'est
#: pas l'enterrer : c'est rendre son absence lisible dans la matrice, pour que personne ne la
#: confonde avec un oubli de câblage — et pour qu'une réadmission exige un motif économique écrit.
FAMILLES_EXCLUES_DU_REPLAY: dict[str, str] = {
    # Cross-Venue est DISABLED_BY_SCOPE par la constitution : ces deux familles décrivent
    # explicitement une autre venue. Les lire pour Copy-Vault reviendrait à réactiver un scope
    # fermé par un chemin détourné.
    "venue_book": (
        "DISABLED_BY_SCOPE:cross_venue — carnet d'une AUTRE venue ; la constitution ferme cette "
        "famille economique, seule une modification revue du scope canonique peut la rouvrir"),
    "venue_dispersion": (
        "DISABLED_BY_SCOPE:cross_venue — dispersion entre venues ; meme verrou constitutionnel, "
        "sa readmission exige un changement de scope revu, pas un branchement"),
    "explorer_tx": (
        "DECOUVERTE_DE_LEADERS : metadonnee d'activite on-chain, sans horloge de marche par coin ; "
        "sa readmission exige une fonction economique ecrite et une jointure as-of prouvee"
    ),
}


def _cotation_collecteur_vers_labo(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Cotation Hyperliquid du collecteur BBO (``bid``/``ask``/``ts_ex``) -> forme BBO du labo.

    Memes grandeurs observees, autres noms : rien n'est invente. ``None`` pour toute ligne
    qui n'est pas une cotation Hyperliquid complete (autre venue, transaction, taille
    absente, carnet croise, horloge incoherente) : fail-closed.
    """
    if row.get("venue") != "HL" or row.get("type_ligne") != "QUOTE" or not row.get("coin"):
        return None
    recu, bourse = row.get("recv_wall_ts_ms"), row.get("ts_ex")
    if isinstance(recu, bool) or not isinstance(recu, int):
        return None
    if isinstance(bourse, bool) or not isinstance(bourse, (int, float)) or not math.isfinite(bourse):
        return None
    bourse = int(bourse)
    valeurs = [row.get(nom) for nom in ("bid", "bid_sz", "ask", "ask_sz")]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in valeurs):
        return None
    bid, bid_sz, ask, ask_sz = (float(v) for v in valeurs)
    if not (0 < bid < ask and bid_sz > 0 and ask_sz > 0 and 0 < bourse <= recu):
        return None
    return {
        "schema_version": "hypersmart.copy_vault_bbo.v1", "coin": row["coin"],
        "received_at_ms": recu, "exchange_ts_ms": bourse,
        "bid_px": bid, "bid_sz": bid_sz, "ask_px": ask, "ask_sz": ask_sz,
        "source": "HYPERLIQUID_BBO_WS", "data_origin": "REAL_OBSERVED", "causal_observation": True,
        "provenance_tier": "LOCAL", "adapte_depuis": "bbo_tape",
    }


#: Champs d'un fill dont la valeur se répète d'une ligne à l'autre (adresse du leader, marché, source,
#: sens...). ``json`` crée une chaîne NEUVE à chaque ligne : sur des millions de fills, les mêmes
#: quelques centaines de valeurs occupaient des gigaoctets. On les partage ; les valeurs sont inchangées.
_CHAMPS_REPETES = (
    "vault", "coin", "source", "source_id", "observation_transport", "reconciliation_status", "dir", "dir_raw",
    "side", "side_raw", "fill_side", "tier", "feeToken", "fee_token", "groupe", "quality_status", "data_origin",
    "schema_version", "source_dataset_id", "source_shard_sha256", "position_direction_before",
    "position_direction_after",
)


#: Adresse du leader lue dans la ligne BRUTE : un fill écarté ne doit même pas être décodé. Décodé puis
#: jeté, il laisse sa mémoire entremêlée à celle des lignes gardées, et le système ne la récupère jamais
#: (mesuré : 5 millions de fills écartés, mémoire inchangée à 20 Go).
_VAULT_DANS_LA_LIGNE = re.compile(r'"vault":\s*"(0x[0-9a-fA-F]{40})"')
_CHAMPS_HORODATAGE_SIGNAL = (
    "ts_ms", "snapshot_ts_ms", "received_at_ms", "open_ts_ms",
    "exchange_ts_ms", "ts_ex",
)
_HORODATAGE_DANS_LA_LIGNE = re.compile(
    r'"(?:ts_ms|snapshot_ts_ms|received_at_ms|open_ts_ms|exchange_ts_ms|ts_ex)":\s*[1-9][0-9]*'
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _signal_horodate(row: Mapping[str, Any]) -> bool:
    return any(type(row.get(field)) is int and row[field] > 0 for field in _CHAMPS_HORODATAGE_SIGNAL)


def _partager_les_chaines(row: dict[str, Any]) -> None:
    for champ in _CHAMPS_REPETES:
        valeur = row.get(champ)
        if type(valeur) is str:
            row[champ] = sys.intern(valeur)


def adresses_archivees(repository_root: Path) -> set[str] | None:
    """Adresses que le plan du labo classe ``ARCHIVE`` : robots à haute fréquence non copiables et
    clones d'un opérateur déjà suivi. ``None`` si le plan est absent ou illisible (rien n'est écarté
    sur la foi d'un classement qui n'existe pas).

    C'est la MÊME classe que celle qui ralentit leur collecte : leurs fills restent au coffre et
    nourrissent l'étude de copiabilité (c'est elle qui les classe), mais ils ne sont pas rejoués par
    la recherche principale. Un robot produit des millions de fills par jour ; les rejouer ne
    mesurait rien de copiable et saturait la mémoire (cas réel du 2026-11-11 : 8,5 millions de
    fills, 21 Go, passage jamais terminé)."""
    try:
        plan = json.loads((repository_root / PLAN_DE_COLLECTE).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    classes = cadence_plan(plan)
    if not classes:
        return None
    return {adresse for adresse, classe in classes.items() if classe == CADENCE_ARCHIVE}


#: Plafond de lignes materialisees par le pont. MESURE DU 16/11 : les familles de replay
#: (fills + carnets) totalisent 59 832 338 lignes, soit ~13,9 Go de dictionnaires Python — sur une
#: machine de 31,9 Go dont 9 etaient libres. Il n'existait AUCUNE garde : le pont chargeait, et la
#: machine mourait. 8 millions de lignes tiennent dans ~2 Go, ce qui laisse de la place au reste.
MAX_LIGNES_MATERIALISEES = 8_000_000

#: Tous les N shards, on redemande au gouverneur memoire s'il faut s'arreter. Assez souvent pour
#: reagir, assez rare pour ne pas payer la mesure a chaque fichier.
SHARDS_ENTRE_CONTROLES_RAM = 20


def _charger_tier_local(
    repository_root: Path, *, progress: Callable[[str], None] | None = None, garder_signaux: bool = True,
    depuis_ms: int | None = None, jusqu_ms: int | None = None,
    max_lignes: int = MAX_LIGNES_MATERIALISEES, garder_replay: bool = True,
) -> dict[str, Any]:
    """Charge le tier LOCAL du coffre-fort (certifie) EN MEMOIRE pour la recherche.

    Lit ``runtime/coffre_certifie/LOCAL_INDEX.json`` + ses shards gzip, re-verifie leur
    SHA-256 (fail-closed : un shard altere est IGNORE), et renvoie les rangees par type
    (``_fills`` / ``_books`` / ``_bbo``), chacune etiquetee ``provenance_tier=LOCAL`` et
    SANS ``quality=SAFE`` : elles nourrissent la recherche EXPLORATOIRE (signaux causaux)
    mais NE PEUVENT JAMAIS etre « prouvees » economiquement (la preuve exige SAFE).

    ``garder_signaux=False`` : les signaux de contexte (prix, OI, cross-venue...) sont COMPTES par
    famille sans etre gardes en memoire. Le labo principal ne lit que leur decompte ; les garder
    occupait plusieurs gigaoctets pour rien.

    ``garder_replay=False`` : MEME TRAITEMENT POUR LES FILLS ET LES CARNETS.
    18/11/2026 — mesure sur la fenetre du 13/11 : 11 698 999 fills et 7 509 693 carnets, soit
    ~60,5 Go de dictionnaires Python pour 32 Go de machine. Le labo les lit desormais en flux
    (``copy_vault_rubans_lourds``) et n'a plus besoin que des DECOMPTES : les garder ici ferait
    payer deux fois la meme memoire, et c'est elle qui arretait le chargement a 452 shards sur
    5 570 en annoncant ``MEMOIRE_CRITIQUE``.

    LES COTATIONS BBO RESTENT MATERIALISEES, et ce n'est pas un oubli. Leur deduplication est a
    ETAT (une cotation par coin et par seconde, avec adaptation des lignes du collecteur) : la
    porter en flux demande plus qu'un changement de boucle. Elles pesent 481 Mo sur disque, loin
    des 60 Go des deux autres familles. Le 18/11, les avoir coupees avec elles a vide le ruban
    ``copy_vault_bbo_tape.jsonl`` dont le labo tire le cout de spread — regression mesuree sur les
    rubans produits, puis corrigee ici.
    """
    import gzip as _gzip

    vide = {"statut": "ABSENT", "_fills": [], "_books": [], "_bbo": [], "_signaux": {},
            "fills_causaux": 0, "fills_backfill": 0, "carnets": 0, "bbo": 0,
            "bbo_adaptees": 0, "bbo_denses_non_retenues": 0,
            "signaux_par_famille": {}, "signaux_total": 0, "signaux_non_horodates": {},
            "familles_indexees": {}, "familles_non_chargees": {},
            "signaux_gardes_en_memoire": garder_signaux,
            "chargement_arrete": None, "shards_hors_fenetre": 0, "shards_non_lus": 0,
            "plafond_lignes": int(max_lignes), "fenetre_depuis_ms": depuis_ms,
            "fenetre_jusqu_ms": jusqu_ms,
            "shards_injectes": 0, "shards_rejetes": 0,
            "fills_archive_non_rejoues": 0, "adresses_archive": None}
    index_path = repository_root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    if index_path.is_symlink() or not index_path.is_file():
        return vide
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {**vide, "statut": "INDEX_ILLISIBLE"}
    shards = index.get("shards") if isinstance(index, dict) else None
    if not isinstance(shards, list) or not shards:
        return {**vide, "statut": "VIDE"}
    coffre_root = (repository_root / "runtime" / "coffre_certifie" / "local" / "shards").resolve()

    familles_indexees: dict[str, dict[str, int]] = {}
    familles_non_chargees: dict[str, dict[str, Any]] = {}
    familles_chargeables = _COFFRE_FAMILLES_FILLS | _COFFRE_FAMILLES_SIGNAUX | {"book_l2", "bbo"}
    for entree in shards:
        if not isinstance(entree, dict):
            continue
        famille = str(entree.get("famille") or "INCONNUE")
        compte = familles_indexees.setdefault(famille, {"shards": 0, "lignes_declarees": 0})
        compte["shards"] += 1
        n = entree.get("deposes")
        if type(n) is int and n >= 0:
            compte["lignes_declarees"] += n
        if famille not in familles_chargeables:
            autres = familles_non_chargees.setdefault(famille, {
                "shards": 0, "lignes_declarees": 0,
                "motif": "AUCUN_ADAPTATEUR_COPY_VAULT_DANS_LE_PONT_LOCAL",
            })
            autres["shards"] += 1
            if type(n) is int and n >= 0:
                autres["lignes_declarees"] += n

    _fills: list[dict[str, Any]] = []
    _books: list[dict[str, Any]] = []
    _bbo: list[dict[str, Any]] = []
    _signaux: dict[str, list[dict[str, Any]]] = {}
    # cotations du collecteur BBO : flux tres dense -> une par coin et par seconde (la premiere
    # observee), largement assez pour dater un prix d'execution, sans saturer la memoire.
    _bbo_secondes: set[tuple[str, int]] = set()
    # Comptes tenus au fil de l'eau : ils restent exacts meme quand les lignes ne sont pas gardees.
    comptes_replay = {"fills": 0, "fills_causaux": 0, "carnets": 0, "bbo": 0}
    bbo_adaptees = 0
    bbo_denses_non_retenues = 0
    archivees = adresses_archivees(repository_root)
    fills_archive = 0
    signaux_comptes: dict[str, int] = {}
    signaux_non_horodates: dict[str, int] = {}
    shards_ok = 0
    shards_rejetes = 0
    # 16/11/2026 — TROIS GARDES, parce qu'il n'y en avait AUCUNE.
    shards_hors_fenetre = 0
    arret_chargement: str | None = None
    shards_non_lus = 0
    memoire_attendue_s, memoire_incidents, memoire_detail = 0.0, 0, None
    for index_shard, entree in enumerate(shards):
        if arret_chargement is not None:
            shards_non_lus += 1
            continue
        if not isinstance(entree, dict):
            continue
        famille = str(entree.get("famille") or "")
        est_signal = famille in _COFFRE_FAMILLES_SIGNAUX
        if famille not in familles_chargeables:
            continue
        # GARDE 1 — FENETRE. L'index porte les bornes de chaque shard (completees par le
        # reindexage du 16/11) : un shard entierement anterieur a la fenetre etudiee n'a aucune
        # raison d'etre decompresse ni hashe.
        if depuis_ms is not None:
            borne = entree.get("ts_max_ms")
            if type(borne) is int and borne < int(depuis_ms):
                shards_hors_fenetre += 1
                continue
        # 16/11 (2e passe) — BORNE HAUTE. Sans elle, une fenêtre n'avait pas de fin : le pont ne
        # pouvait pas être conduit galerie par galerie (`plan_de_fouille`), donc le corpus entier
        # restait inaccessible autrement qu'en une seule charge tronquée à 8 M lignes.
        if jusqu_ms is not None:
            borne_basse = entree.get("ts_min_ms")
            if type(borne_basse) is int and borne_basse > int(jusqu_ms):
                shards_hors_fenetre += 1
                continue
        # GARDE 2 — PLAFOND DE LIGNES. Une troncature silencieuse ferait mesurer sur un
        # echantillon inconnu : on s'arrete et on le DIT.
        if comptes_replay["fills"] + comptes_replay["carnets"] + comptes_replay["bbo"] >= int(max_lignes):
            arret_chargement = "PLAFOND_LIGNES"
            shards_non_lus += 1
            continue
        # GARDE 3 — MEMOIRE. « On ralentit ou on retrecit, on ne crashe JAMAIS. »
        if index_shard % SHARDS_ENTRE_CONTROLES_RAM == 0:
            # 17/11/2026 : a la premiere alerte le pont abandonnait TOUT le reste (60 shards lus,
            # 6 349 non lus) alors que la memoire revenait au vert trente secondes plus tard. On
            # attend si la pression vient d'ailleurs ; on ne s'arrete que si elle persiste, ou si
            # c'est notre propre charge.
            souffle = _FENETRE.patienter_sous_pression(progress=progress)
            memoire_attendue_s += float(souffle["attendu_s"])
            memoire_incidents += 1 if souffle["incident"] else 0
            if not souffle["continuer"]:
                arret_chargement, memoire_detail = _FENETRE.ARRET_MEMOIRE, souffle["detail"]
                shards_non_lus += 1
                continue
        rel = entree.get("shard")
        if not isinstance(rel, str):
            shards_rejetes += 1
            continue
        sha_attendu = str(entree.get("sha256") or "").lower()
        shard_path = repository_root / rel
        if _SHA256_RE.fullmatch(sha_attendu) is None:
            shards_rejetes += 1
            continue
        if (not shard_path.resolve().is_relative_to(coffre_root)
                or shard_path.is_symlink() or not shard_path.is_file()):
            shards_rejetes += 1
            continue
        # fail-closed : le SHA du shard doit correspondre a l'index certifie.
        h = hashlib.sha256()
        try:
            with shard_path.open("rb") as fb:
                for bloc in iter(lambda: fb.read(1 << 20), b""):
                    h.update(bloc)
        except OSError:
            shards_rejetes += 1
            continue
        if h.hexdigest() != sha_attendu:
            shards_rejetes += 1
            continue
        # Aucun fragment d'un gzip incomplet ne doit survivre au rejet du shard.
        debut_fills, debut_books, debut_bbo = len(_fills), len(_books), len(_bbo)
        debut_signaux = len(_signaux.get(famille, ()))
        debut_compte = signaux_comptes.get(famille, 0)
        debut_non_horodate = signaux_non_horodates.get(famille, 0)
        debut_archive, debut_adaptees, debut_denses = fills_archive, bbo_adaptees, bbo_denses_non_retenues
        debut_comptes = dict(comptes_replay)
        try:
            with _gzip.open(shard_path, "rt", encoding="utf-8") as src:
                for ligne in src:
                    ligne = ligne.strip()
                    if not ligne:
                        continue
                    if archivees and famille in _COFFRE_FAMILLES_FILLS:
                        trouve = _VAULT_DANS_LA_LIGNE.search(ligne)
                        if trouve is not None and trouve.group(1).lower() in archivees:
                            fills_archive += 1          # robot HFT ou clone : compté, jamais décodé
                            continue
                    if est_signal and not garder_signaux:
                        if _HORODATAGE_DANS_LA_LIGNE.search(ligne) is not None:
                            signaux_comptes[famille] = signaux_comptes.get(famille, 0) + 1
                        else:
                            signaux_non_horodates[famille] = signaux_non_horodates.get(famille, 0) + 1
                        continue
                    try:
                        row = json.loads(ligne)
                    except (ValueError, TypeError):
                        raise ValueError("ligne JSON invalide dans le shard certifie")
                    if not isinstance(row, dict):
                        raise ValueError("ligne JSON non objet dans le shard certifie")
                    row["provenance_tier"] = "LOCAL"
                    if famille in _COFFRE_FAMILLES_FILLS:
                        if isinstance(row.get("ts_ms"), int) and row.get("vault") and row.get("coin"):
                            if archivees and str(row["vault"]).lower() in archivees:
                                fills_archive += 1      # (écriture inhabituelle de l'adresse dans la ligne)
                            else:
                                comptes_replay["fills"] += 1
                                if (row.get("isSnapshot") is False
                                        and is_causal_live_source(row.get("source"))):
                                    comptes_replay["fills_causaux"] += 1
                                if garder_replay:
                                    _partager_les_chaines(row)
                                    _fills.append(row)
                    elif famille == "book_l2":
                        if (isinstance(row.get("received_at_ms"), int)
                                and isinstance(row.get("exchange_ts_ms"), int)
                                and row.get("coin") and row.get("bids5") and row.get("asks5")):
                            comptes_replay["carnets"] += 1
                            if garder_replay:
                                _books.append(row)
                    elif famille == "bbo":
                        if (isinstance(row.get("received_at_ms"), int)
                                and isinstance(row.get("exchange_ts_ms"), int)
                                and row.get("coin") and row.get("bid_px") is not None
                                and row.get("ask_px") is not None):
                            comptes_replay["bbo"] += 1
                            _bbo.append(row)      # cotations TOUJOURS materialisees : voir la docstring
                        else:
                            adaptee = _cotation_collecteur_vers_labo(row)
                            if adaptee is not None:
                                seconde = (adaptee["coin"], adaptee["received_at_ms"] // 1000)
                                if seconde in _bbo_secondes:
                                    bbo_denses_non_retenues += 1
                                else:
                                    _bbo_secondes.add(seconde)
                                    comptes_replay["bbo"] += 1
                                    _bbo.append(adaptee)
                                    bbo_adaptees += 1
                    elif est_signal:
                        # Signal de contexte LOCAL : tout enregistrement certifié avec
                        # un horodatage explicite est mis à disposition de la recherche.
                        if _signal_horodate(row):
                            _signaux.setdefault(famille, []).append(row)
                            signaux_comptes[famille] = signaux_comptes.get(famille, 0) + 1
                        else:
                            signaux_non_horodates[famille] = signaux_non_horodates.get(famille, 0) + 1
        except (OSError, EOFError, UnicodeError, ValueError):
            del _fills[debut_fills:]
            del _books[debut_books:]
            for row in _bbo[debut_bbo:]:
                if row.get("adapte_depuis") == "bbo_tape":
                    _bbo_secondes.discard((row["coin"], row["received_at_ms"] // 1000))
            del _bbo[debut_bbo:]
            if est_signal:
                del _signaux.setdefault(famille, [])[debut_signaux:]
                if debut_compte:
                    signaux_comptes[famille] = debut_compte
                else:
                    signaux_comptes.pop(famille, None)
                if debut_non_horodate:
                    signaux_non_horodates[famille] = debut_non_horodate
                else:
                    signaux_non_horodates.pop(famille, None)
            fills_archive, bbo_adaptees, bbo_denses_non_retenues = (
                debut_archive, debut_adaptees, debut_denses
            )
            comptes_replay.update(debut_comptes)   # un shard rejete ne laisse AUCUNE trace
            shards_rejetes += 1
            continue
        shards_ok += 1
        if progress is not None and shards_ok % 5 == 0:
            progress(f"Coffre LOCAL · {shards_ok} shards · {comptes_replay['fills']:,} fills")

    fills_causaux = comptes_replay["fills_causaux"]
    return {
        "statut": ("REJECTED" if shards_ok == 0 else "PARTIAL" if shards_rejetes else "OK"),
        "shards_injectes": shards_ok, "shards_rejetes": shards_rejetes,
        "_fills": _fills, "_books": _books, "_bbo": _bbo,
        # familles présentes même quand les lignes ne sont pas gardées (le labo en publie la liste)
        "_signaux": {famille: _signaux.get(famille, []) for famille in signaux_comptes},
        "fills_causaux": fills_causaux,
        "fills_backfill": comptes_replay["fills"] - fills_causaux,
        "carnets": comptes_replay["carnets"], "bbo": comptes_replay["bbo"],
        # Les lignes sont-elles REELLEMENT en memoire, ou seulement comptees ?
        "replay_garde_en_memoire": garder_replay,
        # Les cotations ne sont jamais coupees : le ruban du cout de spread en depend.
        "bbo_toujours_materialise": True,
        "bbo_adaptees": bbo_adaptees, "bbo_denses_non_retenues": bbo_denses_non_retenues,
        "signaux_par_famille": dict(sorted(signaux_comptes.items())),
        "signaux_total": sum(signaux_comptes.values()),
        "signaux_non_horodates": dict(sorted(signaux_non_horodates.items())),
        "familles_indexees": dict(sorted(familles_indexees.items())),
        "familles_non_chargees": dict(sorted(familles_non_chargees.items())),
        "signaux_gardes_en_memoire": garder_signaux,
        # Ce que le pont a DELIBEREMENT laisse de cote, et pourquoi. Jamais de coupe muette.
        "chargement_arrete": arret_chargement,
        "memoire": {"incidents": memoire_incidents, "attendu_s": round(memoire_attendue_s, 1),
                    "arret_detail": memoire_detail},
        "shards_hors_fenetre": shards_hors_fenetre,
        "shards_non_lus": shards_non_lus,
        "plafond_lignes": int(max_lignes),
        "fenetre_depuis_ms": depuis_ms,
        "fenetre_jusqu_ms": jusqu_ms,
        # fills des adresses classées ARCHIVE par le plan du labo : au coffre, mais non rejoués
        "fills_archive_non_rejoues": fills_archive,
        "adresses_archive": None if archivees is None else len(archivees),
    }

#: 17/11/2026 — CHAQUE FAMILLE SANS CONSOMMATEUR DE REPLAY A DÉSORMAIS UN RÔLE MESURÉ.
#:
#: Historique. Au run du 12/11, dix familles étaient comptées sans que personne sache qu'elles
#: dormaient. Le 16/11 elles ont reçu un état déclaré, ``A_CABLER`` : la fonction qu'elles
#: serviraient et la condition pour les brancher. C'était mieux que le silence, mais c'était encore
#: un état d'ATTENTE, et l'objectif exige pour chaque famille un rôle « consommé et mesuré » ou
#: une « exclusion motivée ».
#:
#: « Utiliser tout » ne veut toujours pas dire injecter tout dans un modèle : brancher une famille
#: sans hypothèse préenregistrée ajoute des essais multiples, et les lois mesurées n'ont pas besoin
#: d'un degré de liberté de plus. La réponse est une MESURE DESCRIPTIVE par famille, qui tranche la
#: seule question utile : cette famille peut-elle seulement changer quelque chose ?
#:
#: Chaque fiche nomme le rôle, la fonction qui le mesure (elle doit EXISTER : un test l'importe),
#: et la limite — ce que la famille ne fait PAS, pour qu'un rôle mesuré ne soit jamais lu comme un
#: branchement dans la décision.
FAMILLES_A_ROLE_MESURE: dict[str, dict[str, str]] = {
    "trades_marche": {
        "role": "CAPACITE_MESUREE",
        "mesure": "capacite_par_coin",
        "limite": "decrit ce que le marche echange par minute ; n'entre dans aucun signal d'entree",
    },
    "liquidation": {
        "role": "RISQUE_MESURE",
        "mesure": "risque_de_liquidation",
        "limite": "frequence observee des liquidations et ADL ; aucun filtre de risque n'est gele",
    },
    "vault_ledger": {
        "role": "FLUX_DE_CAPITAL_MESURE",
        "mesure": "flux_de_capital",
        "limite": "compte les jours-compte avec depot ou retrait ; la correction reste celle de Dietz",
    },
    "overshoot": {
        "role": "RESULTAT_SEULEMENT_EXCLUE_COMME_ENTREE",
        "mesure": "resultat_overshoot",
        "limite": ("porte mid_fwd_* et reversion_bps, des valeurs du FUTUR de l'evenement : "
                   "look-ahead par construction, donc jamais une entree de decision"),
    },
    "micro_l2": {
        "role": "APPLICABILITE_MESUREE",
        "mesure": "applicabilite_microstructure",
        "limite": "quelques coins seulement ; un conditionnement OFI exige un preenregistrement",
    },
    "micro_trades": {
        "role": "APPLICABILITE_MESUREE",
        "mesure": "applicabilite_microstructure",
        "limite": "meme couverture que micro_l2 ; horloge fine disponible, aucune hypothese gelee",
    },
}
