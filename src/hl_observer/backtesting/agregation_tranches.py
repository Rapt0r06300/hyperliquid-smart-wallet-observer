"""COMBINER LES RAPPORTS DE PLUSIEURS TRANCHES, sans jamais fabriquer un résultat.

POURQUOI CE MODULE EXISTE À PART. Le labo sait désormais tourner sur une tranche de temps
(`run_local_campaign(..., tranche=...)`), parce que charger le corpus entier demandait ~52 Go :
31,8 Go de fills (8 464 251 lignes à 3 754 octets) et 20,4 Go de carnets (7 527 878 à 2 713), ce
qui faisait couper l'enveloppe du rejeu. Restait à recombiner les tranches — et c'est là que se
trouve le vrai danger, bien plus que dans la découpe.

LES QUATRE FAÇONS DE MENTIR EN AGRÉGEANT, et ce que ce module fait à la place :

1. **La moyenne de moyennes.** Faire la moyenne de six taux de réussite journaliers donne un
   nombre qui ne correspond à aucune population : une journée de 40 signaux y pèse autant qu'une de
   40 000. Ici, un ratio se recompose en sommant le NUMÉRATEUR et le DÉNOMINATEUR
   (`ratio_global`), et le dénominateur est toujours publié avec lui.

2. **Le trou qui devient un zéro.** Si une tranche n'a pas été évaluée, sa contribution n'est pas
   nulle : elle est INCONNUE. `combiner` refuse de rendre un total tant qu'une tranche manque,
   recouvre une autre ou laisse un intervalle non couvert (`couverture`).

3. **Le verdict optimiste.** Cinq tranches `MORE_DATA` et une `UNMEASURABLE` ne font pas un
   `MORE_DATA` : elles font un ensemble dont une partie n'est pas mesurable. `verdict_global` prend
   toujours l'état le PLUS FAIBLE présent, et nomme la tranche responsable.

4. **La preuve par juxtaposition.** Des rapports qui se déclarent tous NON CONCLUANTS ne font
   pas une conclusion en s'additionnant. `combiner` compte les rapports partiels et publie
   `preuve_possible: False` dès qu'il en voit un — il continue de rendre son verdict et ses
   totaux, qui sont des mesures et qui valent, mais il refuse de laisser croire qu'ils prouvent.
   Il publie aussi `essais_totaux`, pour qu'on juge la multiplicité à l'échelle de l'ensemble au
   lieu de la deviner (le labo la corrige déjà par tranche, essais des autres tranches compris).

5. **Le total qui oublie son périmètre.** Un PnL sommé sur six tranches dont deux ont été
   écourtées n'est pas comparable à un PnL sur six journées pleines. Chaque sortie porte donc le
   nombre de tranches, leur étendue réelle en millisecondes et la liste des jours UTC couverts.

PAPER / LECTURE SEULE : ce module ne lit aucun fichier et n'écrit rien. Il ne prend que des
rapports déjà produits.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

SCHEMA = "hypersmart.agregation_tranches.v1"

#: Du plus faible au plus fort. L'agrégat prend toujours le plus faible présent : une preuve ne
#: peut pas naître de la juxtaposition de morceaux dont un n'est pas mesurable.
ORDRE_DES_ETATS: tuple[str, ...] = (
    "UNMEASURABLE",
    "REJECTED",
    "MORE_DATA",
    "PROMISING",
    "PROVEN",
)

#: Un état absent ou inconnu est traité comme le plus faible, jamais ignoré.
ETAT_PAR_DEFAUT = "UNMEASURABLE"


def _rang(etat: object) -> int:
    texte = str(etat or "").strip().upper()
    return ORDRE_DES_ETATS.index(texte) if texte in ORDRE_DES_ETATS else 0


def verdict_global(rapports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """L'état le plus FAIBLE présent, avec la tranche qui le porte.

    Sans rapport, le verdict est `UNMEASURABLE` : une liste vide ne prouve rien, et surtout elle ne
    vaut pas « rien à signaler ».
    """
    if not rapports:
        return {"status": ETAT_PAR_DEFAUT, "reason": "AUCUNE_TRANCHE", "tranche_la_plus_faible": None}
    pire = min(range(len(rapports)), key=lambda i: (_rang(rapports[i].get("status")), i))
    faible = rapports[pire]
    etats: dict[str, int] = {}
    for rapport in rapports:
        etat = str(rapport.get("status") or ETAT_PAR_DEFAUT).strip().upper()
        if etat not in ORDRE_DES_ETATS:
            etat = ETAT_PAR_DEFAUT
        etats[etat] = etats.get(etat, 0) + 1
    return {
        "status": str(faible.get("status") or ETAT_PAR_DEFAUT).strip().upper()
        if str(faible.get("status") or "").strip().upper() in ORDRE_DES_ETATS
        else ETAT_PAR_DEFAUT,
        "reason": faible.get("reason"),
        "tranche_la_plus_faible": pire,
        "etats_par_tranche": dict(sorted(etats.items())),
        "unanime": len(etats) == 1,
    }


def sommer(rapports: Iterable[Mapping[str, Any]], cle: str) -> dict[str, Any]:
    """Somme une grandeur ADDITIVE, en comptant les tranches où elle manque.

    Une clé absente n'est pas un zéro : elle est signalée dans `tranches_sans_la_cle`. Le total
    reste rendu — il est juste incomplet, et le dit.
    """
    total = 0.0
    entiers = True
    presentes = manquantes = 0
    for rapport in rapports:
        valeur = rapport.get(cle)
        if valeur is None or isinstance(valeur, bool):
            manquantes += 1
            continue
        try:
            nombre = float(valeur)
        except (TypeError, ValueError):
            manquantes += 1
            continue
        if nombre != nombre or nombre in (float("inf"), float("-inf")):
            manquantes += 1
            continue
        if not isinstance(valeur, int):
            entiers = False
        total += nombre
        presentes += 1
    return {
        "total": int(total) if entiers and float(total).is_integer() else total,
        "tranches_avec_la_cle": presentes,
        "tranches_sans_la_cle": manquantes,
        "complet": manquantes == 0 and presentes > 0,
    }


def ratio_global(
    rapports: Sequence[Mapping[str, Any]], *, numerateur: str, denominateur: str
) -> dict[str, Any]:
    """Un taux recomposé en sommant les DEUX termes — jamais la moyenne des taux.

    La moyenne de six taux journaliers donne autant de poids à une journée de 40 signaux qu'à une de
    40 000 : elle ne décrit aucune population réelle. Le dénominateur est publié avec le taux, pour
    qu'on ne puisse pas citer l'un sans l'autre.
    """
    haut = sommer(rapports, numerateur)
    bas = sommer(rapports, denominateur)
    if not bas["complet"] or float(bas["total"]) <= 0:
        return {
            "taux": None,
            "numerateur": haut["total"], "denominateur": bas["total"],
            "mesurable": False,
            "raison": "DENOMINATEUR_ABSENT_OU_NUL" if bas["complet"] else "DENOMINATEUR_INCOMPLET",
        }
    return {
        "taux": float(haut["total"]) / float(bas["total"]),
        "numerateur": haut["total"], "denominateur": bas["total"],
        "mesurable": haut["complet"],
        "raison": None if haut["complet"] else "NUMERATEUR_INCOMPLET",
    }


def _bornes(tranche: object) -> tuple[int, int] | None:
    try:
        debut, fin = tranche  # type: ignore[misc]
    except (TypeError, ValueError):
        return None
    if type(debut) is not int or type(fin) is not int or debut <= 0 or fin < debut:
        return None
    return debut, fin


def couverture(tranches: Sequence[object]) -> dict[str, Any]:
    """Les tranches couvrent-elles un intervalle continu, sans trou ni recouvrement ?

    Un trou laisserait croire qu'une période a été évaluée à zéro alors qu'elle n'a pas été lue ; un
    recouvrement compterait deux fois les mêmes signaux. Les deux sont nommés, pas corrigés.
    """
    bornes = [_bornes(t) for t in tranches]
    if not bornes or any(b is None for b in bornes):
        return {
            "continue": False, "raison": "TRANCHE_ILLISIBLE",
            "tranches_illisibles": [i for i, b in enumerate(bornes) if b is None],
            "etendue_ms": 0, "trous": [], "recouvrements": [],
        }
    ordonnees = sorted(bornes)  # type: ignore[arg-type]
    trous: list[list[int]] = []
    recouvrements: list[list[int]] = []
    for (d1, f1), (d2, _f2) in zip(ordonnees, ordonnees[1:], strict=False):
        if d2 <= f1:
            recouvrements.append([d2, f1])
        elif d2 > f1 + 1:
            trous.append([f1 + 1, d2 - 1])
    etendue = sum(fin - debut + 1 for debut, fin in ordonnees)
    return {
        "continue": not trous and not recouvrements,
        "raison": None if not trous and not recouvrements
        else ("TROU" if trous else "RECOUVREMENT"),
        "tranches_illisibles": [],
        "etendue_ms": etendue,
        "trous": trous,
        "recouvrements": recouvrements,
        "premier_ms": ordonnees[0][0],
        "dernier_ms": ordonnees[-1][1],
    }


def unir_les_jours(rapports: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Les jours UTC distincts de toutes les tranches, en UNION.

    Les sommer compterait deux fois un jour présent dans deux tranches, et c'est exactement ce que
    le seuil du labo (six journées distinctes) ne doit pas pouvoir franchir par découpage.
    """
    jours: set[str] = set()
    sans = 0
    for rapport in rapports:
        couv = rapport.get("signal_coverage")
        liste = couv.get("utc_days") if isinstance(couv, Mapping) else None
        if not isinstance(liste, (list, tuple)) or not liste:
            sans += 1
            continue
        jours.update(str(j) for j in liste)
    return {
        "jours": sorted(jours),
        "distincts": len(jours),
        "tranches_sans_jours_declares": sans,
    }


def _marquer_incomplet(mesure: dict[str, Any], tranches_sans_rapport: int) -> dict[str, Any]:
    """Une mesure calculee sur des rapports PRESENTS ignore les tranches qui n'en ont pas rendu.

    `sommer` et `ratio_global` ne voient que ce qu'on leur donne : si une tranche entiere a echoue,
    ils annoncent `complet` / `mesurable` en toute bonne foi, et c'est le trou qui devient un zero.
    Seul `combiner` sait combien de tranches etaient ATTENDUES, donc c'est lui qui invalide.

    Defaut trouve le 18/11/2026 par un test ecrit pour ce piege, dans mon propre module : une
    tranche levant `MemoryError` laissait un total declare complet.
    """
    if tranches_sans_rapport <= 0:
        return mesure
    marquee = dict(mesure)
    marquee["tranches_sans_rapport"] = tranches_sans_rapport
    if "complet" in marquee:
        marquee["complet"] = False
    if "mesurable" in marquee:
        marquee["mesurable"] = False
    marquee["raison"] = "TRANCHE_SANS_RAPPORT"
    return marquee


def combiner(
    rapports: Sequence[Mapping[str, Any]],
    *,
    tranches: Sequence[object],
    additifs: Sequence[str] = (),
    ratios: Sequence[tuple[str, str]] = (),
    jours_minimum: int | None = None,
) -> dict[str, Any]:
    """L'agrégat complet : verdict, couverture, totaux et taux, chacun avec son périmètre.

    `exploitable` ne devient vrai que si la couverture est continue, que chaque tranche a rendu
    un rapport, ET que l'union des journées UTC atteint `jours_minimum`. Un agrégat non
    exploitable est rendu quand même — avec sa raison — parce que le cacher reviendrait à laisser
    l'appelant inventer le total lui-même.

    `jours_minimum` EST LE SEUIL DU LABO, APPLIQUÉ ICI. Une tranche de quelques heures ne couvre
    jamais six journées : la porte du labo a donc été déplacée au niveau de l'ensemble, et c'est ce
    paramètre qui la referme. Sans lui, les tranches exploreraient et personne ne vérifierait que
    l'ensemble couvre assez de jours — un desserrage sans contrepartie.
    """
    couv = couverture(tranches)
    manquants = len(tranches) - len(rapports)
    sortie: dict[str, Any] = {
        "schema": SCHEMA,
        "tranches_demandees": len(tranches),
        "rapports_recus": len(rapports),
        "tranches_sans_rapport": max(0, manquants),
        "couverture": couv,
        "verdict": verdict_global(rapports),
        "jours": unir_les_jours(rapports),
        "totaux": {
            cle: _marquer_incomplet(sommer(rapports, cle), manquants)
            for cle in additifs
        },
        "taux": {
            f"{num}/{den}": _marquer_incomplet(
                ratio_global(rapports, numerateur=num, denominateur=den), manquants)
            for num, den in ratios
        },
        "paper_read_only": True,
        "real_execution": False,
    }
    partiels = sum(
        1 for rapport in rapports if rapport.get("verdict_partiel") is True
    )
    essais = sommer(rapports, "candidates_tested")
    sortie["rapports_partiels"] = partiels
    sortie["essais_totaux"] = essais["total"]
    sortie["preuve_possible"] = partiels == 0
    if partiels:
        sortie["raison_preuve_impossible"] = "RAPPORTS_PARTIELS"
    assez_de_jours = (
        jours_minimum is None
        or sortie["jours"]["distincts"] >= int(jours_minimum)
    )
    sortie["jours_minimum"] = jours_minimum
    sortie["assez_de_jours"] = bool(assez_de_jours)
    sortie["exploitable"] = bool(
        rapports and manquants <= 0 and couv["continue"] and assez_de_jours
    )
    if not sortie["exploitable"]:
        sortie["raison_non_exploitable"] = (
            "AUCUNE_TRANCHE" if not rapports
            else "TRANCHE_SANS_RAPPORT" if manquants > 0
            else couv["raison"] if not couv["continue"]
            else "JOURNEES_INSUFFISANTES"
        )
    return sortie


__all__ = [
    "SCHEMA", "ORDRE_DES_ETATS", "ETAT_PAR_DEFAUT",
    "verdict_global", "sommer", "ratio_global", "couverture", "unir_les_jours", "combiner",
]
