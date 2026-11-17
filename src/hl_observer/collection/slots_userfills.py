"""Attribution des emplacements `userFills` : voir ce que le poll voit, suivre le labo, ne pas lâcher.

LE DÉFAUT, MESURÉ LE 17/11/2026 SUR LES RUBANS RÉELS.
Hyperliquid plafonne à 10 le nombre d'utilisateurs suivis en direct par IP. Le collecteur attribue
donc 10 emplacements : les retenus, une sentinelle, puis les candidats « actifs » — et il fait
tourner le reste parmi les silencieux. Mais « actif » voulait dire **« vu en direct depuis moins de
45 minutes »** : un leader qui n'occupe pas d'emplacement ne peut pas être vu, donc ne peut pas
devenir actif. Il devait attendre que la rotation des silencieux retombe sur lui.

Mesure, contre l'historique complet des fills (rattrapage REST, par heure d'échange) :

* une fois abonné, le direct capte ~100 % des fills d'un leader (0 perte dans une connexion) ;
* mais sur 49 reprises d'activité (après ≥ 45 min de silence), **30 n'ont jamais été vues en
  direct**, et la découverte prend 38, 40, 114 minutes sur les plus grosses ;
* résultat : **61,0 % des fills de ces rafales sont manqués** (6 956 sur 11 395) — et toujours
  le DÉBUT de la rafale, là où le méta-ordre commence.

Or un autre collecteur voit déjà tout le monde : le poll REST (`vault_fills_poll.jsonl`) interroge
chaque leader en quelques minutes. Sa première ligne sur une rafale arrive 1 à 340 s après le
premier fill. Avec cette alerte, la perte mesurée tombe à **19,6 %** (borne : promotion à la page
suivante, un emplacement disponible).

CE QUE FAIT CE MODULE.
1. `activite_poll_par_vault` lit la QUEUE du ruban du poll (lecture bornée) et compte les fills
   récents par leader. Ce compte ne sert qu'à décider OÙ REGARDER : aucun fill du poll ne devient
   un signal, aucune heure de réception n'est touchée.
2. `activite_effective` : l'activité d'un candidat est le maximum de ce que voient le direct et le
   poll. Un leader que le labo a classé `ARCHIVE` (HFT non copiable, ou clone) n'est JAMAIS promu
   par le poll : le budget suit le plan du labo, comme pour la cadence du poll.
3. `ordonner_les_actifs` : classe du labo d'abord (PRIORITAIRE, STANDARD, puis le reste), et à
   classe égale le TITULAIRE garde sa place. Avant, l'ordre suivait un score qui bouge à chaque
   fill : la page changeait à chaque cycle, et un seul changement reconstruisait TOUTES les
   connexions (1 497 connexions en 44 h, un petit trou aveugle toutes les 150 s pour chacun).
4. `ordre_stable` : les titulaires gardent leur rang dans la page. Même ensemble → même page →
   connexions maintenues, comme le collecteur le prévoyait déjà.
5. `choisir_les_libres` : les emplacements restants ne tournent plus que parmi les candidats que
   le poll NE COUVRE PAS — eux seuls ont encore besoin du direct pour être découverts. Les autres
   restent en place. Mesuré en simulation : avec la rotation générale, la page changeait à chaque
   cycle même avec l'indice du poll. Si le poll est muet ou périmé, on retombe EXACTEMENT sur la
   rotation historique : un indice absent ne doit jamais geler la découverte.
6. `journaliser_page` : une ligne par cycle, avec les leaders abonnés. Sans elle, on ne pouvait pas
   distinguer « abonné et silencieux » de « pas abonné » : un trou d'observation se lisait comme
   une absence de fill.
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.collection.forward_poll_fills import (
    CADENCE_ARCHIVE,
    CADENCE_PRIORITAIRE,
    CADENCE_STANDARD,
    cadence_plan,
)
from hl_observer.ops.echec_silencieux import noter as _noter_echec

SCHEMA_PAGES = "hypersmart.userfills_pages.v1"
RUBAN_POLL = Path("runtime") / "data" / "vault_fills_poll.jsonl"
BESOINS_COLLECTE = Path("runtime") / "data" / "copy_vault_besoins_collecte.json"
#: `.ndjson` et non `.jsonl` : c'est une trace d'audit, pas un flux de collecte à sceller.
JOURNAL_PAGES = Path("runtime") / "data" / "userfills_pages.ndjson"
#: État du poll : ses clés sont les leaders qu'il interroge.
LEADERS_DU_POLL = Path("runtime") / "data" / "userfills_poll_watermarks.json"

#: Même fenêtre que l'activité vue en direct (`HYPERSMART_VAULT_ACTIVITE_FENETRE_MIN`, 45 min).
FENETRE_MS = 45 * 60_000
#: Mesuré le 17/11 : 40 Mo de queue couvrent 77 min de poll, lus et filtrés en ~0,3 s.
BUDGET_OCTETS_POLL = 32 * 1024 * 1024
#: Le poll écrit des centaines de lignes par minute. Sans ligne depuis 10 min, il ne voit plus rien :
#: son silence ne prouve alors l'inactivité de personne.
FRAICHEUR_POLL_MS = 10 * 60_000

MOTIF_OK = "OK"
MOTIF_ABSENT = "RUBAN_DU_POLL_ABSENT"
MOTIF_ILLISIBLE = "RUBAN_DU_POLL_ILLISIBLE"
MOTIF_VIDE = "AUCUNE_LIGNE_LISIBLE"
#: La queue lue ne remonte pas jusqu'au début de la fenêtre : le compte est un MINORANT.
MOTIF_PARTIEL = "FENETRE_PARTIELLEMENT_COUVERTE"
#: La dernière ligne du poll est trop ancienne : l'indice est ignoré, rotation historique.
MOTIF_PERIME = "POLL_PERIME"

#: Rang de budget d'une classe du labo. Une adresse non classée vaut une « découverte ».
RANG_CLASSE = {CADENCE_PRIORITAIRE: 0, CADENCE_STANDARD: 1}
RANG_PAR_DEFAUT = 2

_TEMPS = re.compile(rb'"time":\s*(\d+)')
_VAULT = re.compile(rb'"vault":\s*"(0x[0-9a-fA-F]{40})"')
_RECU = re.compile(rb'"received_at_ms":\s*(\d+)')


def charger_plan(root: Path) -> dict[str, str]:
    """``adresse (minuscules) -> classe`` depuis le plan du labo ; vide s'il est absent ou illisible."""
    try:
        besoins = json.loads((Path(root) / BESOINS_COLLECTE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(adresse).lower(): classe for adresse, classe in cadence_plan(besoins).items()}


def activite_poll_par_vault(root: Path, *, maintenant_ms: int | None = None,
                            fenetre_ms: int = FENETRE_MS,
                            budget_octets: int = BUDGET_OCTETS_POLL,
                            ) -> tuple[dict[str, int], dict[str, Any]]:
    """``({adresse: fills récents}, diagnostic)`` d'après la queue du ruban du poll.

    Un compte vide n'est jamais muet : le diagnostic dit s'il n'y avait rien à lire, si on n'a pas
    su lire, ou si la queue lue ne couvrait qu'une partie de la fenêtre.
    """
    maintenant = int(time.time() * 1000) if maintenant_ms is None else int(maintenant_ms)
    seuil = maintenant - int(fenetre_ms)
    diagnostic: dict[str, Any] = {"motif": MOTIF_OK, "octets_lus": 0, "lignes": 0,
                                  "lignes_dans_la_fenetre": 0, "fenetre_ms": int(fenetre_ms),
                                  "plus_ancienne_reception_ms": None,
                                  "plus_recente_reception_ms": None, "frais": False}
    chemin = Path(root) / RUBAN_POLL
    try:
        with chemin.open("rb") as flux:
            taille = flux.seek(0, 2)
            depart = max(0, taille - max(0, int(budget_octets)))
            flux.seek(depart)
            if depart:
                flux.readline()            # première ligne coupée : on la laisse
            bloc = flux.read()
    except FileNotFoundError:
        diagnostic["motif"] = MOTIF_ABSENT
        return {}, diagnostic
    except OSError as exc:
        _noter_echec("collection/slots_userfills.py:lecture_du_poll", exc)
        diagnostic["motif"] = MOTIF_ILLISIBLE
        return {}, diagnostic
    diagnostic["octets_lus"] = len(bloc)
    comptes: dict[str, int] = {}
    plus_ancienne: int | None = None
    plus_recente: int | None = None
    for ligne in bloc.splitlines():
        temps, vault = _TEMPS.search(ligne), _VAULT.search(ligne)
        if temps is None or vault is None:
            continue
        diagnostic["lignes"] += 1
        recu = _RECU.search(ligne)
        if recu is not None:
            valeur = int(recu.group(1))
            plus_ancienne = valeur if plus_ancienne is None else min(plus_ancienne, valeur)
            plus_recente = valeur if plus_recente is None else max(plus_recente, valeur)
        if int(temps.group(1)) >= seuil:
            adresse = vault.group(1).decode("ascii").lower()
            comptes[adresse] = comptes.get(adresse, 0) + 1
            diagnostic["lignes_dans_la_fenetre"] += 1
    diagnostic["plus_ancienne_reception_ms"] = plus_ancienne
    diagnostic["plus_recente_reception_ms"] = plus_recente
    diagnostic["frais"] = bool(plus_recente is not None
                               and maintenant - plus_recente <= FRAICHEUR_POLL_MS)
    if not diagnostic["lignes"]:
        diagnostic["motif"] = MOTIF_VIDE
    elif not diagnostic["frais"]:
        # Un poll arrêté ne dit rien de l'activité de personne : on ne promeut ni ne gèle rien.
        diagnostic["motif"] = MOTIF_PERIME
        return {}, diagnostic
    elif depart and plus_ancienne is not None and plus_ancienne > seuil:
        diagnostic["motif"] = MOTIF_PARTIEL
    return comptes, diagnostic


def leaders_suivis_par_le_poll(root: Path) -> set[str]:
    """Adresses (minuscules) que le poll interroge ; vide si son état est absent ou illisible."""
    try:
        etat = json.loads((Path(root) / LEADERS_DU_POLL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(etat, Mapping):
        return set()
    return {str(adresse).lower() for adresse in etat if str(adresse).lower().startswith("0x")}


def indice_d_attribution(root: Path, *, maintenant_ms: int | None = None,
                         fenetre_ms: int = FENETRE_MS) -> dict[str, Any]:
    """Tout ce que le collecteur doit savoir pour attribuer ses emplacements. NE LÈVE JAMAIS.

    Pensé pour ``asyncio.to_thread`` : la lecture ne retient pas la boucle qui horodate les fills.
    """
    try:
        activite, diagnostic = activite_poll_par_vault(root, maintenant_ms=maintenant_ms,
                                                       fenetre_ms=fenetre_ms)
        plan = charger_plan(root)
        # Un poll périmé ne « couvre » plus personne : tous les silencieux retournent à la rotation.
        suivis = leaders_suivis_par_le_poll(root) if diagnostic.get("frais") else set()
    except Exception as exc:  # noqa: BLE001 - un indice ne doit jamais arrêter la collecte
        _noter_echec("collection/slots_userfills.py:indice_d_attribution", exc)
        return {"activite_poll": {}, "plan": {}, "leaders_du_poll": set(),
                "diagnostic": {"motif": MOTIF_ILLISIBLE, "frais": False}}
    return {"activite_poll": activite, "plan": plan, "leaders_du_poll": suivis,
            "diagnostic": diagnostic}


def classe_du_labo(plan: Mapping[str, str] | None, vault: object) -> str | None:
    return (plan or {}).get(str(vault or "").lower())


def activite_effective(candidats: Iterable[str], direct: Mapping[str, int] | None,
                       indice: Mapping[str, Any] | None) -> dict[str, int]:
    """Activité retenue pour l'attribution : le maximum du direct et du poll, par candidat.

    Un leader `ARCHIVE` n'est jamais promu par le poll ; ce qu'on voit de lui en direct reste
    compté tel quel (rien n'est retiré à ce qui existait).
    """
    direct = direct or {}
    poll = (indice or {}).get("activite_poll") or {}
    plan = (indice or {}).get("plan") or {}
    resultat = {str(vault): int(compte) for vault, compte in direct.items() if int(compte) > 0}
    for vault in candidats:
        cle = str(vault)
        vu = int(poll.get(cle.lower(), 0) or 0)
        if vu <= 0 or classe_du_labo(plan, cle) == CADENCE_ARCHIVE:
            continue
        if vu > resultat.get(cle, 0):
            resultat[cle] = vu
    return resultat


def ordonner_les_actifs(actifs: Sequence[Mapping[str, Any]], *, plan: Mapping[str, str] | None,
                        en_place: Iterable[str] = ()) -> list[Mapping[str, Any]]:
    """Classe du labo d'abord ; à classe égale le titulaire d'abord ; sinon l'ordre reçu.

    Le tri est stable : l'ordre reçu (le score de rotation du collecteur) départage le reste.
    """
    titulaires = {str(v).lower() for v in en_place}

    def cle(candidat: Mapping[str, Any]) -> tuple[int, int]:
        vault = str(candidat.get("vault") or "")
        rang = RANG_CLASSE.get(classe_du_labo(plan, vault) or "", RANG_PAR_DEFAUT)
        return rang, 0 if vault.lower() in titulaires else 1

    return sorted(actifs, key=cle)


def ordre_stable(selection: Sequence[Mapping[str, Any]],
                 en_place: Sequence[str] = ()) -> list[Mapping[str, Any]]:
    """Les titulaires d'abord, dans l'ordre de la page en cours ; puis les nouveaux, dans l'ordre reçu.

    Même ensemble → même liste → le collecteur ne reconstruit aucune connexion.
    """
    rang = {str(v).lower(): i for i, v in enumerate(en_place)}
    titulaires = [c for c in selection if str(c.get("vault") or "").lower() in rang]
    nouveaux = [c for c in selection if str(c.get("vault") or "").lower() not in rang]
    titulaires.sort(key=lambda c: rang[str(c.get("vault") or "").lower()])
    return titulaires + nouveaux


def choisir_les_libres(silencieux: Sequence[Mapping[str, Any]], *, libres: int, rotation_index: int,
                       indice: Mapping[str, Any] | None,
                       en_place: Iterable[str] = ()) -> list[Mapping[str, Any]]:
    """Qui occupe les emplacements que les actifs laissent libres.

    Les silencieux que le poll NE couvre PAS tournent comme avant : le direct est leur seule chance
    d'être vus. Les silencieux couverts ne tournent plus — le poll signalera leur réveil — et le
    titulaire garde sa place, pour que la page reste identique d'un cycle à l'autre.

    Sans liste des leaders du poll (absente, illisible, poll périmé), TOUS les silencieux sont
    « non couverts » : c'est exactement la rotation historique.
    """
    libres = max(0, int(libres))
    if not libres or not silencieux:
        return []
    suivis = (indice or {}).get("leaders_du_poll") or set()
    hors = [c for c in silencieux if str(c.get("vault") or "").lower() not in suivis]
    couverts = [c for c in silencieux if str(c.get("vault") or "").lower() in suivis]
    choisis: list[Mapping[str, Any]] = []
    if hors:
        if len(hors) <= libres:
            choisis = list(hors)
        else:
            depart = (max(0, int(rotation_index)) * libres) % len(hors)
            choisis = [hors[(depart + k) % len(hors)] for k in range(libres)]
    reste = libres - len(choisis)
    if reste > 0 and couverts:
        titulaires = {str(v).lower() for v in en_place}
        ordonnes = sorted(couverts,
                          key=lambda c: 0 if str(c.get("vault") or "").lower() in titulaires else 1)
        choisis += ordonnes[:reste]
    return choisis


def journaliser_page(root: Path, *, page: int, roles: Sequence[Sequence[Any]], maintenue: bool,
                     indice: Mapping[str, Any] | None = None,
                     maintenant_ms: int | None = None) -> bool:
    """Ajoute UNE ligne décrivant la page d'abonnement de ce cycle. Rend ``False`` si l'écriture échoue.

    ``maintenue`` distingue une page reconduite (connexions gardées) d'une page reconstruite.
    """
    diagnostic = (indice or {}).get("diagnostic") or {}
    plan = (indice or {}).get("plan") or {}
    poll = (indice or {}).get("activite_poll") or {}
    ligne = {
        "schema_version": SCHEMA_PAGES,
        "ts_ms": int(time.time() * 1000) if maintenant_ms is None else int(maintenant_ms),
        "page": int(page),
        "maintenue": bool(maintenue),
        "vaults": [
            {"vault": str(r[0]), "role": str(r[1]),
             "classe_labo": classe_du_labo(plan, r[0]),
             "fills_poll_fenetre": int(poll.get(str(r[0]).lower(), 0) or 0)}
            for r in roles
        ],
        "indice_poll": diagnostic.get("motif"),
        "leaders_actifs_au_poll": len(poll),
        "poll_frais": bool(diagnostic.get("frais")),
        "paper_read_only": True,
        "real_execution": False,
    }
    chemin = Path(root) / JOURNAL_PAGES
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("a", encoding="utf-8", newline="") as flux:
            flux.write(json.dumps(ligne, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as exc:
        _noter_echec("collection/slots_userfills.py:journal_des_pages", exc)
        return False
    return True


__all__ = [
    "SCHEMA_PAGES", "RUBAN_POLL", "BESOINS_COLLECTE", "JOURNAL_PAGES", "LEADERS_DU_POLL", "FENETRE_MS",
    "BUDGET_OCTETS_POLL", "FRAICHEUR_POLL_MS", "MOTIF_OK", "MOTIF_ABSENT", "MOTIF_ILLISIBLE", "MOTIF_VIDE",
    "MOTIF_PARTIEL", "MOTIF_PERIME", "RANG_CLASSE", "RANG_PAR_DEFAUT",
    "charger_plan", "activite_poll_par_vault", "leaders_suivis_par_le_poll", "indice_d_attribution", "classe_du_labo",
    "activite_effective", "ordonner_les_actifs", "choisir_les_libres", "ordre_stable", "journaliser_page",
]
