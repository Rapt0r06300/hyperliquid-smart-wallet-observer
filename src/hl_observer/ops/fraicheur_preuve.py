"""La preuve est-elle plus VIEILLE que la collecte qu'elle prétend qualifier ?

POURQUOI (chantier 13 de l'audit du 15/11). Le dernier rapport du labo datait du **12 novembre**
alors que la collecte observée était celle du **16**. Un rapport vert sur des données de quatre
jours plus tôt ne qualifie pas l'état présent — et rien ne le signalait. De même, un lot certifié
ou un shard SAFE restauré plus ancien que la collecte en cours laisse la chaîne de preuve derrière
les faits.

Ce module ne juge que des HORLOGES, et il échoue fermé : une date absente ou illisible n'est pas
« récente par défaut », c'est `INCONNU`, et `INCONNU` ferme la porte.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "hypersmart.fraicheur_preuve.v1"

#: Au-delà de ce retard, la preuve ne couvre plus la collecte. 1 heure : assez pour absorber une
#: passe de scellage (30 min de cadence) sans déclarer périmé ce qui est simplement en route.
RETARD_TOLERE_MS = 3_600_000

FRAIS = "FRAIS"
PERIME = "PERIME"
INCONNU = "INCONNU"


def _entier(valeur: Any) -> int | None:
    """Un horodatage EXACT en millisecondes, ou ``None``. Un flottant n'est pas une horloge."""
    if type(valeur) is not int or isinstance(valeur, bool):
        return None
    return valeur if valeur > 0 else None


def evaluer(*, collecte_ms: Any, elements: Mapping[str, Any],
            retard_tolere_ms: int = RETARD_TOLERE_MS) -> dict[str, Any]:
    """``{statut, retards_ms, en_retard, raisons}`` pour chaque élément de la chaîne de preuve.

    ``elements`` : ``{"dernier_lot_certifie": ms, "dernier_safe_restaure": ms,
    "dernier_rapport_labo": ms, ...}``. Chaque élément est comparé à ``collecte_ms``, l'instant de
    la donnée la plus récente réellement collectée.
    """
    collecte = _entier(collecte_ms)
    retards: dict[str, int | None] = {}
    raisons: list[str] = []
    if collecte is None:
        return {
            "schema": SCHEMA, "statut": INCONNU, "collecte_ms": None,
            "retards_ms": {str(k): None for k in elements or {}},
            "en_retard": sorted(str(k) for k in elements or {}),
            "raisons": ["COLLECTE_SANS_HORODATAGE"],
            "retard_tolere_ms": int(retard_tolere_ms),
        }
    en_retard: list[str] = []
    for nom, valeur in (elements or {}).items():
        instant = _entier(valeur)
        if instant is None:
            retards[str(nom)] = None
            en_retard.append(str(nom))
            raisons.append(f"{nom}:HORODATAGE_ABSENT")
            continue
        retard = collecte - instant
        retards[str(nom)] = retard
        if retard > max(0, int(retard_tolere_ms)):
            en_retard.append(str(nom))
            raisons.append(f"{nom}:RETARD_{retard // 3_600_000}H")
    if not elements:
        statut = INCONNU
        raisons.append("AUCUN_ELEMENT_A_VERIFIER")
    elif any(retards[n] is None for n in retards):
        statut = INCONNU
    elif en_retard:
        statut = PERIME
    else:
        statut = FRAIS
    return {
        "schema": SCHEMA, "statut": statut, "collecte_ms": collecte,
        "retards_ms": retards, "en_retard": sorted(set(en_retard)),
        "raisons": sorted(set(raisons)), "retard_tolere_ms": int(retard_tolere_ms),
    }


def message(rapport: Mapping[str, Any]) -> str:
    """Une ligne lisible pour un opérateur. Jamais rassurante par défaut."""
    statut = str(rapport.get("statut") or INCONNU)
    if statut == FRAIS:
        return "[fraicheur] la chaine de preuve couvre la collecte en cours."
    retards = rapport.get("retards_ms") or {}
    details = ", ".join(
        f"{nom}=" + ("inconnu" if retards.get(nom) is None
                     else f"{int(retards[nom]) / 3_600_000:.1f} h de retard")
        for nom in rapport.get("en_retard") or ()
    )
    return (f"[fraicheur] {statut} — la preuve ne couvre PAS la collecte en cours : {details}. "
            "Un rapport vert sur des donnees anterieures ne qualifie pas l'etat present.")


_TAG_DATE = re.compile(r"-(20[0-9]{2})([01][0-9])([0-3][0-9])([0-2][0-9])-")

#: Un rapport de ce statut n'a RIEN rejoué : il ne peut pas rajeunir la chaîne de preuve.
STATUTS_SANS_REJEU = frozenset({"PREFLIGHT_ONLY"})


def date_du_tag_ms(tag: Any) -> int | None:
    """L'horodatage porté par un tag de campagne (``...-AAAAMMJJHH-...``), ou ``None``."""
    trouve = _TAG_DATE.search(str(tag))
    if not trouve:
        return None
    an, mois, jour, heure = (int(x) for x in trouve.groups())
    try:
        return int(datetime(an, mois, jour, heure, tzinfo=UTC).timestamp() * 1000)
    except ValueError:
        return None


def fin_des_donnees_rejouees(resultat: Mapping[str, Any]) -> int | None:
    """Jusqu'à quel instant ce rapport du labo a-t-il RÉELLEMENT rejoué des données ?

    Une chaîne causale a besoin des fills ET des carnets : la fin utile est donc le plus PETIT des
    deux derniers instants. Rend ``None`` si le rapport n'a rien rejoué ou ne dit pas jusqu'où.
    """
    if str(resultat.get("status") or "") in STATUTS_SANS_REJEU:
        return None
    economique = resultat.get("economic_result")
    entrees = resultat.get("safe_inputs")
    if not isinstance(entrees, Mapping) and isinstance(economique, Mapping):
        entrees = economique.get("safe_inputs")
    if not isinstance(entrees, Mapping):
        return None
    fills, carnets = _entier(entrees.get("fill_end_ms")), _entier(entrees.get("book_end_ms"))
    if fills is None or carnets is None:
        return None
    return min(fills, carnets)


def horloges_de_la_chaine(root: str | Path) -> dict[str, int | None]:
    """Les horloges de la chaîne de preuve, lues dans les FAITS et non dans des dates de fichier.

    17/11/2026 — DEUX FAIBLESSES DE LA VERSION DU 16/11, corrigées ici :

    1. ``dernier_rapport_labo`` était l'**heure d'écriture** du dernier ``resultat.json``. Une
       simple pré-vérification (statut ``PREFLIGHT_ONLY``, aucun rejeu) écrit un tel fichier : elle
       suffisait à faire taire l'alerte. C'est arrivé le 17/11 à 13:36. L'horloge est maintenant
       la **fin des données réellement rejouées** par le dernier rapport qui a rejoué quelque
       chose — un rapport écrit aujourd'hui sur des données d'hier reste en retard d'un jour.
    2. L'âge du tier SAFE n'entrait pas dans le verdict, alors que SEULE une chaîne SAFE peut
       soutenir une preuve. Mesuré : dernier tag SAFE le 18/10, collecte au 17/11.

    Un élément illisible vaut ``None`` : l'évaluation le traite comme INCONNU, qui ferme la porte.
    """
    racine = Path(root)
    elements: dict[str, int | None] = {"dernier_lot_certifie": None,
                                       "dernier_rapport_labo": None, "dernier_tag_safe": None}
    manifests = racine / "runtime" / "coffre_certifie" / "local" / "manifests"
    derniers = sorted(manifests.glob("*.json")) if manifests.is_dir() else []
    if derniers:
        try:
            elements["dernier_lot_certifie"] = _entier(
                json.loads(derniers[-1].read_text(encoding="utf-8")).get("genere_ms"))
        except (OSError, ValueError, TypeError, AttributeError):
            elements["dernier_lot_certifie"] = None
    rapports = racine / "runtime" / "reports" / "copy_vault_quant_lab"
    resultats = sorted(rapports.glob("*/resultat.json")) if rapports.is_dir() else []
    for chemin in reversed(resultats[-50:]):          # du plus récent au plus ancien, borné
        try:
            charge = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fin = fin_des_donnees_rejouees(charge) if isinstance(charge, Mapping) else None
        if fin is not None:
            elements["dernier_rapport_labo"] = fin
            break
    index = racine / "runtime" / "coffre_certifie" / "COFFRE_INDEX.json"
    try:
        tier = (json.loads(index.read_text(encoding="utf-8")).get("tiers") or {}).get("SAFE_CLOUD")
        dates = [d for d in (date_du_tag_ms(t) for t in (tier or {}).get("derniers_tags") or ())
                 if d is not None]
        elements["dernier_tag_safe"] = max(dates) if dates else None
    except (OSError, ValueError, TypeError, AttributeError):
        elements["dernier_tag_safe"] = None
    return elements


__all__ = ["SCHEMA", "RETARD_TOLERE_MS", "FRAIS", "PERIME", "INCONNU", "STATUTS_SANS_REJEU",
           "date_du_tag_ms", "fin_des_donnees_rejouees", "horloges_de_la_chaine",
           "evaluer", "message"]
