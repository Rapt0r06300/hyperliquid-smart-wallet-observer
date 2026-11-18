#!/usr/bin/env python3
"""CONDUIRE LE LABO PAR TRANCHES : six journées lues l'une après l'autre, jamais ensemble.

POURQUOI. Le labo chargeait tout le corpus à l'étape 2 : 31,8 Go de fills (8 464 251 lignes à
3 754 octets) et 20,4 Go de carnets (7 527 878 à 2 713), ce qui faisait couper l'enveloppe du
rejeu pour mémoire critique. `run_local_campaign` sait désormais travailler sur une tranche ; cet
outil l'appelle une fois par tranche et combine les rapports par `agregation_tranches`.

DEUX CHOSES QU'IL NE FAIT PAS, VOLONTAIREMENT :

* il ne découpe pas par journée calendaire. Les six journées du corpus sont très inégales — le
  13/11 porte 2 172 496 fills contre 476 078 le 18/11, soit 4,6 fois plus — et la plus dense
  demanderait ~7 Go de fills plus ~4,8 Go de carnets. Le découpage suit donc la DENSITÉ RÉELLE du
  ruban, mesurée en flux avant de commencer, avec un budget de lignes par tranche ;
* il ne fabrique aucun total. Une tranche dont le labo ne rend rien laisse l'agrégat NON
  EXPLOITABLE, avec sa raison. C'est `agregation_tranches` qui porte ce refus, et il est testé là.

PAPER / LECTURE SEULE : aucune requête réseau, aucun ordre, aucune écriture hors du rapport.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))
# La RACINE aussi : `copy_vault_local_lab` importe `tools.copy_vault_continuity`, donc sans elle
# l'import du labo leve `ModuleNotFoundError: No module named 'tools'`. Defaut trouve en lancant
# la conduite reelle le 18/11/2026 : `--plan-seulement` ne l'avait jamais vu, puisqu'il ne charge
# pas le labo. Un outil dont seul le mode « plan » a tourne n'est pas un outil verifie.
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from hl_observer.backtesting import agregation_tranches as AG  # noqa: E402
from hl_observer.ops import budget_ram as RAM  # noqa: E402

SCHEMA = "hypersmart.conduite_labo_tranches.v1"

#: Le ruban dont la densité décide du découpage : c'est lui qui pèse le plus (7,12 Go mesurés).
RUBAN_FILLS = Path("runtime") / "data" / "vault_fills_live.jsonl"

#: Octets par fill en memoire, MESURES le 18/11/2026 (400 000 lignes chargees = 1,50 Go).
#: Sert a estimer le besoin d'une tranche avant de la lancer, pas a le garantir.
OCTETS_PAR_FILL = 3_754

#: Marge pour les carnets de la tranche et le reste de l'etape 2.
#:
#: MESURE SUR LES 129 HEURES DU CORPUS (18/11/2026), rapport des octets carnets/fills :
#:     median 0,70  |  p10 0,43  |  p90 1,03  |  max 1,39
#: soit un facteur `1 + rapport` : median 1,70, p90 2,03, max 2,39.
#:
#: J'avais d'abord pose 1,8, deduit de la seule journee du 18/11 : ce facteur SOUS-ESTIME le besoin
#: une heure sur dix. Pour une GARDE memoire, se tromper vers le bas est le mauvais sens de
#: l'erreur -- elle laisserait partir une tranche qu'elle croyait legere. On prend donc le maximum
#: observe, arrondi vers le haut.
FACTEUR_CARNETS = 2.4

#: Lignes de fills par tranche. 500 000 lignes ont été mesurées à 1,54 Go de pic pour l'étape 2
#: (476 078 fills retenus le 18/11), carnets non compris : c'est un budget prudent sur une machine
#: où la RAM libre tourne autour de 10 Go.
BUDGET_LIGNES = 500_000

#: Granularité du découpage. Descendre sous l'heure ne sert à rien ici : la détention médiane des
#: leaders est de ~47 min, donc une tranche plus courte couperait la plupart des épisodes.
PAS_MS = 3_600_000

_TS = re.compile(rb'"ts_ms":\s*(\d+)')

#: Le seuil du labo, reapplique par l'agregat sur l'UNION des journees des tranches. Il vaut
#: `copy_vault_local_lab._MINIMUM_SIGNAL_UTC_DAYS` : importe plutot que recopie, pour qu'une seule
#: valeur existe.
try:
    from hl_observer.backtesting.copy_vault_local_lab import (  # noqa: E402
        _MINIMUM_SIGNAL_UTC_DAYS as JOURS_MINIMUM,
    )
except ImportError:            # pragma: no cover - le labo doit etre importable ; on le dit
    JOURS_MINIMUM = 6


def densite_par_pas(ruban: Path, *, pas_ms: int = PAS_MS) -> dict[int, int]:
    """Combien de fills dans chaque pas de temps, lu EN FLUX (32 s pour 7,12 Go).

    On mesure avant de découper, parce que le corpus est inégal : supposer une densité uniforme
    ferait une tranche de 7 Go le 13/11 et une de 1,5 Go le 18/11.
    """
    compte: dict[int, int] = {}
    try:
        flux = ruban.open("rb")
    except OSError:
        return compte
    with flux:
        for ligne in flux:
            trouve = _TS.search(ligne)
            if trouve is None:
                continue
            seau = int(trouve.group(1)) // pas_ms * pas_ms
            compte[seau] = compte.get(seau, 0) + 1
    return compte


#: Les familles du coffre qui portent des fills de leaders. Ce sont elles qui dimensionnent les
#: tranches : les carnets suivent le meme decoupage temporel, et les autres familles sont legeres.
FAMILLES_FILLS = ("fills_forward", "fills_backfill")


def densite_depuis_le_coffre(
    index: Path, *, familles: Sequence[str] = FAMILLES_FILLS, pas_ms: int = PAS_MS,
    depuis_ms: int | None = None, jusqu_a_ms: int | None = None,
) -> dict[str, Any]:
    """La densite par pas de temps, lue dans l'INDEX du coffre -- sans ouvrir un seul shard.

    Chaque shard porte `famille`, `ts_min_ms`, `ts_max_ms` et `deposes`. Un shard qui tient dans un
    seul pas y verse toutes ses lignes (exact) ; un shard a cheval les repartit au prorata de la
    duree, ce qui est une HYPOTHESE -- la vraie repartition peut etre concentree sur quelques
    minutes. Acceptable pour dimensionner des tranches, pas pour mesurer quoi que ce soit, et le
    nombre de shards concernes est publie : sans lui, on ne saurait pas si le plan vaut 99 % ou 60 %.
    """
    try:
        charge = json.loads(Path(index).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"densite": {}, "raison": f"INDEX_ILLISIBLE:{type(exc).__name__}",
                "shards_lus": 0, "shards_repartis": 0, "lignes": 0}
    shards = charge.get("shards")
    if not isinstance(shards, list):
        return {"densite": {}, "raison": "INDEX_SANS_SHARDS",
                "shards_lus": 0, "shards_repartis": 0, "lignes": 0}
    voulues = {str(f) for f in familles}
    densite: dict[int, int] = {}
    lus = repartis = lignes = 0
    sans_bornes = hors_fenetre = hors_lignes = 0

    def _dans_la_fenetre(seau: int) -> bool:
        """Un seau est retenu s'il recoupe la fenetre du labo. Le pas entier compte : un seau qui
        commence avant `depuis_ms` mais se termine apres porte des lignes que le labo lira."""
        if depuis_ms is not None and seau + pas_ms - 1 < depuis_ms:
            return False
        return not (jusqu_a_ms is not None and seau > jusqu_a_ms)
    for shard in shards:
        if not isinstance(shard, dict) or str(shard.get("famille")) not in voulues:
            continue
        try:
            debut = int(shard["ts_min_ms"])
            fin = int(shard["ts_max_ms"])
            deposes = int(shard["deposes"])
        except (KeyError, TypeError, ValueError):
            sans_bornes += 1
            continue
        if deposes <= 0 or debut <= 0 or fin < debut:
            sans_bornes += 1
            continue
        # Hors de la FENETRE DU LABO, un shard ne sera jamais lu : le compter ferait annoncer un
        # travail que personne ne fera. Le coffre porte 14 031 heures ; le labo en lit 129.
        if depuis_ms is not None and fin < depuis_ms:
            hors_fenetre += 1
            continue
        if jusqu_a_ms is not None and debut > jusqu_a_ms:
            hors_fenetre += 1
            continue
        lus += 1
        premier, dernier = debut // pas_ms, fin // pas_ms
        if premier == dernier:
            seau = premier * pas_ms
            if _dans_la_fenetre(seau):
                densite[seau] = densite.get(seau, 0) + deposes
                lignes += deposes
            else:
                hors_lignes += deposes
            continue
        repartis += 1
        seaux = list(range(premier, dernier + 1))
        part, reste = divmod(deposes, len(seaux))
        for rang, index_seau in enumerate(seaux):
            seau = index_seau * pas_ms
            # le reste va aux premiers seaux : la somme reste EXACTE, aucune ligne perdue
            portion = part + (1 if rang < reste else 0)
            # ON NE VERSE QUE DANS LES SEAUX DE LA FENETRE. Un shard de 2023 finissant apres le
            # 13/11/2026 passait le filtre des shards et versait des lignes dans des milliers de
            # seaux anterieurs : le plan annoncait 14 031 heures de travail imaginaire.
            if _dans_la_fenetre(seau):
                densite[seau] = densite.get(seau, 0) + portion
                lignes += portion
            else:
                hors_lignes += portion
    return {
        "densite": densite, "raison": None, "shards_lus": lus,
        "shards_repartis": repartis, "shards_sans_bornes": sans_bornes,
        "shards_hors_fenetre": hors_fenetre, "lignes": lignes,
        "lignes_hors_fenetre": hors_lignes,
        "fenetre": [depuis_ms, jusqu_a_ms],
        # Ce que le plan vaut : la part des shards dont les lignes ont ete REPARTIES au prorata
        # plutot que placees exactement. Sans ce chiffre, on ne saurait pas s'il vaut 99 % ou 60 %.
        "part_repartie": round(repartis / lus, 4) if lus else None,
    }


def decouper(
    densite: Mapping[int, int], *, budget: int = BUDGET_LIGNES, pas_ms: int = PAS_MS
) -> list[tuple[int, int]]:
    """Des tranches CONTIGUËS dont aucune ne dépasse le budget, sauf un pas indivisible.

    Les tranches se touchent sans se recouvrir (`fin + 1 == debut` de la suivante), ce que
    `agregation_tranches.couverture` vérifie ensuite : un trou laisserait croire qu'une période vaut
    zéro, un recouvrement compterait deux fois les mêmes signaux.

    Un pas seul au-dessus du budget n'est pas découpé plus fin : on le rend tel quel et l'appelant
    verra sa taille. Le casser en deux séparerait des fills que la reconstruction doit voir
    ensemble, et ce serait un mensonge plus coûteux qu'une tranche lourde.

    CE QUE LA COUVERTURE COUVRE. Les tranches s'étendent sur la période où il y a des FILLS, et
    non sur le calendrier. Une période sans aucun fill n'est donc dans aucune tranche -- et
    c'est correct : sans signal il n'y a rien à évaluer, et un carnet sans signal ne sert à
    rien. Le ruban L2 du corpus porte ainsi quelques milliers de carnets d'octobre, très
    antérieurs au premier jour liable : aucune tranche ne les lira, et aucune mesure ne les
    réclame. Lire `couverture()` comme « tout le corpus est couvert » serait donc un
    contresens : elle dit que les tranches ne laissent ni trou ni recouvrement ENTRE ELLES.
    """
    if not densite:
        return []
    seaux = sorted(densite)
    tranches: list[tuple[int, int]] = []
    debut = seaux[0]
    cumul = 0
    for seau in seaux:
        lignes = int(densite[seau])
        if cumul and cumul + lignes > budget:
            tranches.append((debut, seau - 1))
            debut, cumul = seau, lignes
        else:
            cumul += lignes
    tranches.append((debut, seaux[-1] + pas_ms - 1))
    return tranches


CORPUS_INCONNU = "corpus-inconnu"


def digest_du_corpus(workspace: Path) -> str:
    """L'identite de la SOURCE : le `selection_digest` du manifeste SAFE du workspace.

    Il scelle le catalogue des shards consommes. Un manifeste illisible ne fait pas echouer la
    conduite : on rend `CORPUS_INCONNU`, qui est distinct de tout digest reel -- donc un journal
    ecrit avec un digest connu ne sera pas repris par erreur, et l'inverse non plus.
    """
    chemin = Path(workspace) / "SAFE_INPUT_MANIFEST.json"
    try:
        manifeste = json.loads(chemin.read_text(encoding="utf-8"))
        digest = manifeste["selection_digest"]
    except (OSError, ValueError, TypeError, KeyError):
        return CORPUS_INCONNU
    return digest if isinstance(digest, str) and digest else CORPUS_INCONNU


def empreinte_du_decoupage(
    tranches: Sequence[tuple[int, int]], *, corpus: str = CORPUS_INCONNU
) -> str:
    """Ce qui identifie une conduite : son decoupage ET son corpus.

    Les bornes viennent de la densite du ruban, donc un ruban different donne presque toujours un
    decoupage different -- mais « presque toujours » n'est pas « toujours ». Deux corpus de meme
    densite horaire et de contenu different donneraient les memes bornes : la reprise rendrait alors
    des rapports qui ne decrivent pas les donnees presentes. D'ou le digest de la source.

    Un journal ecrit pour une autre empreinte est inutilisable -- pas « approximativement bon ».
    """
    bornes = ";".join(f"{int(debut)}-{int(fin)}" for debut, fin in tranches)
    graine = f"{corpus}|{bornes}"
    return hashlib.sha256(graine.encode("utf-8")).hexdigest()[:16]


def identite_de_tranche(tranche: tuple[int, int], lignes: int) -> str:
    """Ce qui identifie une tranche SEULE : ses bornes et le nombre de fills qu'elles contiennent.

    POURQUOI PAS LE DECOUPAGE ENTIER. Mesure du 18/11/2026 : un corpus de six heures donne six
    tranches, et trois heures de plus en donnent neuf dont les SIX PREMIERES sont identiques a la
    borne pres -- le decoupage parcourt les seaux dans l'ordre et accumule, donc une collecte
    chronologique n'ajoute des tranches qu'a la fin. Identifier par le decoupage entier faisait
    jeter six tranches deja calculees a chaque nouvelle collecte.

    CE QUE CE CONTROLE VAUT, dit franchement. Il attrape tout ce qui change la QUANTITE de donnees
    d'une fenetre : ajout, retrait, re-materialisation partielle. Il n'attraperait pas un
    remplacement ligne pour ligne a nombre constant dans la meme fenetre -- ce qui n'arrive pas dans
    un coffre append-only certifie, mais qui n'est pas impossible en principe. Le digest du corpus
    reste PUBLIE dans chaque ligne du journal, pour qu'une reprise traversant deux corpus se voie.
    """
    graine = f"{int(tranche[0])}-{int(tranche[1])}-{int(lignes)}"
    return hashlib.sha256(graine.encode("utf-8")).hexdigest()[:16]


def lire_le_journal(chemin: Path, identites: Mapping[tuple[int, int], str]) -> dict[str, Any]:
    """Les rapports deja obtenus pour les tranches dont l'identite correspond.

    `identites` donne, pour chaque tranche demandee, l'identite attendue. Une ligne du journal n'est
    reprise que si sa tranche est demandee ET que son identite correspond : une fenetre dont la
    quantite de donnees a change est donc recalculee, et les autres sont reprises.

    Une ligne illisible est COMPTEE et sautee : une interruption peut tronquer la derniere ligne, et
    la deviner serait inventer un rapport.
    """
    deja: dict[tuple[int, int], Mapping[str, Any]] = {}
    illisibles = 0
    perimees = 0
    try:
        flux = chemin.open("r", encoding="utf-8")
    except OSError:
        return {"rapports": deja, "lignes_illisibles": 0, "autre_decoupage": 0, "journal": False}
    with flux:
        for ligne in flux:
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                enregistre = json.loads(ligne)
                bornes = enregistre["tranche"]
                cle = (int(bornes[0]), int(bornes[1]))
                rapport = enregistre["rapport"]
                signature = str(enregistre["empreinte"])
            except (ValueError, TypeError, KeyError, IndexError):
                illisibles += 1
                continue
            attendue = identites.get(cle)
            if attendue is None or signature != attendue:
                perimees += 1
                continue
            if not isinstance(rapport, Mapping):
                illisibles += 1
                continue
            deja[cle] = rapport
    return {
        "rapports": deja, "lignes_illisibles": illisibles,
        "autre_decoupage": perimees, "journal": True,
    }


def _noter_au_journal(chemin: Path, empreinte: str, tranche: tuple[int, int],
                      rapport: Mapping[str, Any], *, corpus: str = "") -> None:
    """Ecrit APRES la tranche et vidange tout de suite : une coupure ne perd que la derniere.

    `corpus` est publie sans servir a la comparaison : une reprise qui traverse deux corpus reste
    acceptee tranche par tranche, mais elle doit se VOIR dans le journal.
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "a", encoding="utf-8", newline="") as flux:
        flux.write(json.dumps(
            {"empreinte": empreinte, "tranche": [int(tranche[0]), int(tranche[1])],
             "corpus": corpus, "rapport": rapport},
            ensure_ascii=False, default=str) + chr(10))
        flux.flush()
        os.fsync(flux.fileno())


def _rss() -> int:
    """La memoire de CE processus, ou 0 si on ne peut pas la lire.

    Un chiffre indisponible ne doit pas empecher la conduite : il rend la ligne de rapport moins
    informative, rien de plus. On ne devine pas une valeur a sa place.
    """
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except Exception:          # noqa: BLE001 — psutil absent ou refuse : on le dit par un 0
        return 0


def _jour(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M")


def conduire(
    workspace: Path,
    tranches: Sequence[tuple[int, int]],
    *,
    lancer: Callable[[Path, tuple[int, int]], Mapping[str, Any]],
    additifs: Sequence[str] = (),
    ratios: Sequence[tuple[str, str]] = (),
    journal: Callable[[str], None] | None = None,
    estimation: Callable[[tuple[int, int]], int] | None = None,
    jours_minimum: int | None = None,
    journal_reprise: Path | None = None,
    lignes_par_tranche: Callable[[tuple[int, int]], int] | None = None,
    gouverneur: Callable[..., Mapping[str, Any]] = RAM.decision,
    respirer: Callable[[], Mapping[str, Any]] = RAM.attendre_que_ca_respire,
) -> dict[str, Any]:
    """Appelle `lancer` une fois par tranche, puis combine. Un échec ne devient jamais un zéro.

    `lancer` est injecté pour que la conduite soit testable sans corpus. Si une tranche lève, elle
    est consignée avec son type d'erreur et ne produit PAS de rapport : l'agrégat sera donc déclaré
    non exploitable, ce qui est le résultat juste.
    """
    dire = journal or (lambda _m: None)
    rapports: list[Mapping[str, Any]] = []
    incidents: list[dict[str, Any]] = []
    memoires: list[dict[str, Any]] = []
    # Une identite PAR TRANCHE : une collecte qui ajoute des donnees a la fin ne doit pas faire
    # jeter les tranches deja calculees. Sans compteur de lignes, on retombe sur le decoupage
    # entier -- plus prudent, mais sans reprise au-dela d'une nouvelle collecte.
    corpus = digest_du_corpus(Path(workspace))
    empreinte_globale = empreinte_du_decoupage(list(tranches), corpus=corpus)
    identites = {
        (int(debut), int(fin)): (
            identite_de_tranche((debut, fin), lignes_par_tranche((debut, fin)))
            if lignes_par_tranche is not None
            else empreinte_globale
        )
        for debut, fin in tranches
    }
    reprise = (
        lire_le_journal(journal_reprise, identites)
        if journal_reprise is not None
        else {"rapports": {}, "lignes_illisibles": 0, "autre_decoupage": 0, "journal": False}
    )
    if reprise["rapports"]:
        dire(f"  reprise : {len(reprise['rapports'])} tranche(s) deja faite(s) pour ce decoupage")
    if reprise["autre_decoupage"]:
        dire(f"  {reprise['autre_decoupage']} tranche(s) du journal PERIMEE(S) : leurs donnees ont"
             " change, elles seront refaites")
    if reprise["lignes_illisibles"]:
        dire(f"  {reprise['lignes_illisibles']} ligne(s) illisible(s) sautee(s), jamais devinee(s)")
    reprises = 0
    for index, tranche in enumerate(tranches, start=1):
        cle = (int(tranche[0]), int(tranche[1]))
        if cle in reprise["rapports"]:
            rapports.append({**reprise["rapports"][cle], "tranche": list(tranche),
                             "repris_du_journal": True})
            reprises += 1
            dire(f"[{index}/{len(tranches)}] déjà fait — repris du journal")
            continue
        dire(f"[{index}/{len(tranches)}] {_jour(tranche[0])} → {_jour(tranche[1])}")
        besoin = int(estimation(tranche)) if estimation is not None else None
        avis = gouverneur(besoin_octets=besoin)
        if avis.get("action") == RAM.PAUSER:
            dire(f"      RAM critique — je souffle avant de lancer : {avis.get('raison')}")
            souffle = respirer()
            avis = gouverneur(besoin_octets=besoin)
            if avis.get("action") == RAM.PAUSER:
                incidents.append({
                    "tranche": list(tranche), "index": index,
                    "erreur": "MEMOIRE_INSUFFISANTE",
                    "message": str(avis.get("raison"))[:300],
                    "apres_attente_s": round(float(souffle.get("attendu_s", 0.0)), 1)
                    if isinstance(souffle, Mapping) else None,
                })
                dire("      NON EVALUEE : la memoire est restee critique "
                     "(ce n'est pas un zero — l'agregat le dira)")
                continue
        rss_avant = _rss()
        depart = time.time()
        try:
            rapport = lancer(workspace, tranche)
        except Exception as exc:                      # noqa: BLE001 — consigné, jamais avalé
            incidents.append({
                "tranche": list(tranche), "index": index,
                "erreur": type(exc).__name__, "message": str(exc)[:300],
            })
            dire(f"      ÉCHEC {type(exc).__name__} — cette tranche n'aura pas de rapport")
            continue
        if not isinstance(rapport, Mapping):
            incidents.append({
                "tranche": list(tranche), "index": index,
                "erreur": "RAPPORT_NON_LISIBLE", "message": type(rapport).__name__,
            })
            continue
        consomme = _rss() - rss_avant
        memoires.append({
            "tranche": list(tranche), "index": index,
            "octets_consommes": consomme,
            "besoin_estime_octets": besoin,
            "niveau_avant": avis.get("niveau"),
        })
        rapports.append({**rapport, "tranche": list(tranche)})
        if journal_reprise is not None:
            try:
                _noter_au_journal(
                    journal_reprise, identites[cle], tranche, rapport, corpus=corpus)
            except OSError as exc:
                # Ne pas perdre la tranche pour autant : on la garde en memoire et on le DIT.
                incidents.append({
                    "tranche": list(tranche), "index": index,
                    "erreur": "JOURNAL_NON_ECRIT", "message": str(exc)[:200],
                })
                dire("      (journal de reprise non ecrit : cette tranche sera refaite)")
        dire(f"      {rapport.get('status', '?')} en {time.time() - depart:.0f} s"
             + (f" · {consomme / 1e9:+.2f} Go" if consomme else ""))
    agregat = AG.combiner(rapports, tranches=tranches, additifs=additifs, ratios=ratios,
                          jours_minimum=jours_minimum)
    return {
        "schema": SCHEMA,
        "tranches": [list(t) for t in tranches],
        "incidents": incidents,
        "memoire_par_tranche": memoires,
        "tranches_reprises": reprises,
        "empreinte_du_decoupage": empreinte_globale,
        "identites_par_tranche": len(identites),
        "digest_du_corpus": digest_du_corpus(Path(workspace)),
        "agregat": agregat,
        "rapports": rapports,
        "paper_read_only": True,
        "real_execution": False,
    }


def journees_utc(densite: Mapping[int, int]) -> list[str]:
    """Les journees UTC distinctes ou le corpus porte au moins un fill.

    MESUREES, pas supposees : elles sortent du ruban que le conducteur vient de lire. Le labo en a
    besoin pour appliquer son seuil de six journees a l'ENSEMBLE plutot qu'a chaque tranche, et
    l'agregat les reunit ensuite pour refermer la porte.
    """
    jours = {
        datetime.fromtimestamp(seau / 1000, UTC).strftime("%Y-%m-%d")
        for seau, lignes in densite.items() if int(lignes) > 0
    }
    return sorted(jours)


def _lanceur_reel(max_trials: int, campaign_root: Path | None, repository_root: Path,
                  jours_du_corpus: int | None = None):
    """Le vrai appel au labo, isolé ici pour que `conduire` reste testable sans lui.

    CHAQUE TRANCHE A SA PROPRE RACINE DE CAMPAGNE. Une racine commune ferait partager
    `TRIALS.jsonl` et `CHECKPOINT.json` : la tranche 2 sauterait les paramètres essayés sur la
    tranche 1, sur des données différentes. Le labo applique la même règle quand on ne lui passe
    rien (`_nom_de_campagne`) ; ici on garde la racine demandée mais on y ajoute la tranche.
    """
    from hl_observer.backtesting.copy_vault_local_lab import run_local_campaign

    def lancer(workspace: Path, tranche: tuple[int, int]) -> Mapping[str, Any]:
        propre = (
            campaign_root / f"t{int(tranche[0])}-{int(tranche[1])}"
            if campaign_root is not None else None
        )
        return run_local_campaign(
            workspace, tranche=tranche, max_trials=max_trials,
            campaign_root=propre, repository_root=repository_root,
            jours_du_corpus=jours_du_corpus,
        )

    return lancer


def _plan_depuis_le_coffre(args: Any, pas: int) -> int:
    """Le plan annonce par le CERTIFICATEUR : ce que le prochain rejeu du labo decoupera.

    Borne a la fenetre du labo (`choisir_la_fenetre`), parce que le coffre porte tout l'historique
    et que le labo ne lit que depuis le premier jour liable. Sans cette borne, on annoncerait
    soixante-trois tranches la ou il en fera dix-neuf.
    """
    index = RACINE / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    try:
        from hl_observer.backtesting.copy_vault_fenetre_locale import choisir_la_fenetre

        fenetre = choisir_la_fenetre(RACINE)
        depuis = int(fenetre.get("depuis_ms") or 0) or None
        motif = str(fenetre.get("motif") or "")
    except Exception as exc:                  # noqa: BLE001 - on le DIT au lieu de deviner
        depuis, motif = None, f"FENETRE_INDISPONIBLE:{type(exc).__name__}"
    mesure = densite_depuis_le_coffre(index, pas_ms=pas, depuis_ms=depuis)
    if mesure["raison"] is not None:
        print(f"  PLAN INDISPONIBLE : {mesure['raison']} ({index})")
        return 2
    if not mesure["densite"]:
        print("  AUCUN FILL dans la fenetre du labo — rien a decouper, et ce n'est pas un zero.")
        print(f"     fenetre : depuis {depuis} ({motif})"
              f" · {mesure['shards_hors_fenetre']:,} shard(s) hors fenetre")
        return 2
    tranches = decouper(mesure["densite"], budget=args.budget, pas_ms=pas)
    couv = AG.couverture(tranches)
    print(f"  PLAN DE TRANCHES DU PROCHAIN REJEU (lu dans l'index du coffre, {index.name})")
    print(f"     fenetre du labo     : depuis {_jour(depuis) if depuis else 'origine'} ({motif})")
    print(f"     fills concernes     : {mesure['lignes']:,} sur {mesure['shards_lus']:,} shard(s)"
          f" · {mesure['shards_hors_fenetre']:,} shard(s) et"
          f" {mesure['lignes_hors_fenetre']:,} ligne(s) hors fenetre")
    print(f"     tranches a prevoir  : {len(tranches)} AU PLUS (budget {args.budget:,} fills)")
    print("     note                : BORNE HAUTE. Le coffre porte les fills BRUTS ; le labo"
          " ecarte les doublons")
    print("                           (3 543 350 au dernier rejeu) et les non-causaux. Mesure du"
          " 18/11 : 32 annoncees, 19 faites.")
    print(f"     couverture          : continue={couv['continue']}"
          f" · {couv['etendue_ms'] / 3_600_000:.0f} h")
    if mesure["part_repartie"]:
        print(f"     part APPROXIMEE     : {mesure['part_repartie'] * 100:.0f} % des shards"
              " chevauchent plusieurs pas, leurs lignes sont reparties au prorata")
    if args.sortie:
        destination = Path(args.sortie)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with open(destination, "w", encoding="utf-8", newline="") as flux:
            json.dump({
                "schema": "hypersmart.plan_tranches_coffre.v1",
                "source": "LOCAL_INDEX", "fenetre_depuis_ms": depuis, "motif_fenetre": motif,
                "pas_ms": pas, "budget_lignes": args.budget,
                # Le plan decrit le travail MAXIMAL : les fills bruts du coffre incluent les
                # doublons et les non-causaux que le labo ecartera. Mesure du 18/11/2026 :
                # 13 503 314 bruts -> 8 464 251 retenus, soit 32 tranches annoncees pour 19 faites.
                "borne": "HAUTE",
                "pourquoi_borne_haute": (
                    "fills bruts du coffre : doublons inter-sources et fills non causaux"
                    " seront ecartes par le labo"
                ),
                "tranches": [list(t) for t in tranches], "couverture": couv,
                "mesure": {k: v for k, v in mesure.items() if k != "densite"},
                "paper_read_only": True, "real_execution": False,
            }, flux, ensure_ascii=False, indent=2, default=str)
        print(f"     plan ecrit          : {destination}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("workspace", help="le workspace matérialisé par le labo")
    p.add_argument("--budget", type=int, default=BUDGET_LIGNES,
                   help=f"lignes de fills par tranche (défaut {BUDGET_LIGNES:,})")
    p.add_argument("--pas-heures", type=int, default=1, help="granularité du découpage")
    p.add_argument("--max-trials", type=int, default=1)
    p.add_argument("--max-tranches", type=int, default=0,
                   help="ne conduire que les N premieres tranches (0 = toutes) : un essai en petit "
                        "avant une conduite de plusieurs heures. L'agregat reste NON exploitable, "
                        "puisqu'il manque des tranches.")
    p.add_argument("--plan-seulement", action="store_true",
                   help="mesurer et afficher le découpage, sans lancer le labo")
    p.add_argument("--depuis-le-coffre", action="store_true",
                   help="calcule le plan depuis l'INDEX du coffre (0,4 s, sans ouvrir un shard) "
                        "au lieu du ruban du workspace, et s'arrete")
    p.add_argument("--journal", default="",
                   help="journal de reprise (JSONL) : les tranches deja faites sont reprises")
    p.add_argument("--sortie", default="")
    args = p.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    pas = max(1, args.pas_heures) * 3_600_000

    if args.depuis_le_coffre:
        return _plan_depuis_le_coffre(args, pas)
    ruban = workspace / RUBAN_FILLS
    print(f"  mesure de la densité de {ruban.name}…", flush=True)
    depart = time.time()
    densite = densite_par_pas(ruban, pas_ms=pas)
    total = sum(densite.values())
    if not densite:
        print(f"  AUCUN FILL LISIBLE dans {ruban} — rien à conduire, et ce n'est pas un zéro.")
        return 2
    tranches = decouper(densite, budget=args.budget, pas_ms=pas)
    print(f"  {total:,} fills sur {len(densite)} pas de {args.pas_heures} h, "
          f"lus en {time.time() - depart:.0f} s")
    print(f"  → {len(tranches)} tranches (budget {args.budget:,} lignes) :")
    for index, (debut, fin) in enumerate(tranches, start=1):
        lignes = sum(n for seau, n in densite.items() if debut <= seau <= fin)
        marque = "  ⚠ au-dessus du budget" if lignes > args.budget else ""
        print(f"     {index:>2}. {_jour(debut)} → {_jour(fin)}  {lignes:>9,} fills{marque}")
    couverture = AG.couverture(tranches)
    print(f"  couverture : continue={couverture['continue']} "
          f"étendue={couverture['etendue_ms'] / 3_600_000:.1f} h")
    if args.plan_seulement:
        return 0

    def estimer(tranche: tuple[int, int]) -> int:
        lignes = sum(n for seau, n in densite.items() if tranche[0] <= seau <= tranche[1])
        return int(lignes * OCTETS_PAR_FILL * FACTEUR_CARNETS)

    jours = journees_utc(densite)
    print(f"  journees UTC du corpus : {len(jours)} ({jours[0]} -> {jours[-1]})")
    toutes = list(tranches)
    if args.max_tranches and args.max_tranches < len(toutes):
        tranches = toutes[: args.max_tranches]
        print(f"  CONDUITE PARTIELLE : {len(tranches)} tranche(s) sur {len(toutes)}."
              " L'agregat restera NON exploitable, et c'est voulu.")
    def lignes_de(tranche: tuple[int, int]) -> int:
        return sum(n for seau, n in densite.items() if tranche[0] <= seau <= tranche[1])

    resultat = conduire(
        workspace, tranches, estimation=estimer, jours_minimum=JOURS_MINIMUM,
        lignes_par_tranche=lignes_de,
        journal_reprise=Path(args.journal) if args.journal else None,
        lancer=_lanceur_reel(args.max_trials, workspace.parent / "campagne-tranches", RACINE,
                             jours_du_corpus=len(jours)),
        additifs=("net_pnl_usd", "entries", "metaorders", "candidates_tested"),
        ratios=(("temporally_aligned_add_signals", "entries"),),
        journal=lambda message: print(message, flush=True),
    )
    resultat["conduite_partielle"] = len(tranches) < len(toutes)
    resultat["tranches_du_decoupage_complet"] = len(toutes)
    agregat = resultat["agregat"]
    print(f"\n  VERDICT GLOBAL : {agregat['verdict']['status']} "
          f"(exploitable={agregat['exploitable']})")
    if resultat["conduite_partielle"]:
        print(f"  conduite PARTIELLE : {len(tranches)} sur {len(toutes)} tranches —"
              " non exploitable par construction, pas par defaut")
    if not agregat["exploitable"]:
        print(f"  non exploitable : {agregat.get('raison_non_exploitable')}")
    print(f"  jours UTC distincts (union) : {agregat['jours']['distincts']}"
          f" / {agregat.get('jours_minimum') or '-'} requis")
    # Une donnée publiée mais jamais affichée est une donnée invisible : ces trois lignes
    # empêchent de lire un verdict d'ensemble comme une preuve.
    if agregat.get("preuve_possible") is False:
        print(f"  PREUVE IMPOSSIBLE : {agregat.get('raison_preuve_impossible')}"
              f" ({agregat.get('rapports_partiels')} rapport(s) partiel(s) sur"
              f" {agregat.get('rapports_recus')})")
    print(f"  candidats essayés, toutes tranches : {agregat.get('essais_totaux')}")
    if resultat["incidents"]:
        print(f"  {len(resultat['incidents'])} tranche(s) sans rapport :")
        for incident in resultat["incidents"]:
            print(f"     {_jour(incident['tranche'][0])} — {incident['erreur']}")
    if args.sortie:
        destination = Path(args.sortie)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with open(destination, "w", encoding="utf-8", newline="") as flux:
            json.dump(resultat, flux, ensure_ascii=False, indent=2, default=str)
        print(f"\n  rapport : {destination}")
    return 0 if agregat["exploitable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
