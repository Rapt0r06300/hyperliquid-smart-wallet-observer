"""Fenêtres de trou du compagnon de checkpoints, et intervalles `EXECUTION_REPLAY_SAFE`.

POURQUOI CE MODULE EXISTE — BLOQUEUR P0 CONFIRMÉ LE 16/11/2026.
`copy_vault_book_loader` n'acceptait une époque propre que si
``input_rotations + checkpoints_expired + pending_overflow_rejected == 0``. Ces trois compteurs
sont **cumulatifs sur tout le run de l'écrivain**. La campagne active comptait déjà 43 expirations
et une rotation : **tous** les checkpoints du run étaient donc non certifiables, y compris les
milliers de lignes écrites dans des minutes sans aucun trou. Un seul incident fermait l'époque
entière, pour toujours.

La spec autorise des trous globaux mais exige leur quarantaine et des intervalles
`EXECUTION_REPLAY_SAFE` sans trou applicable. C'est ce que fait ce module : l'écrivain publie la
**fenêtre temporelle réellement affectée** par chaque incident — il la connaît, contrairement au
lecteur —, et le lecteur ne certifie qu'une ligne reçue **hors** de toute fenêtre.

CE QUE CE MODULE NE FAIT PAS, PAR CONSTRUCTION :
* il ne remet aucun compteur à zéro — un trou historique reste un trou historique ;
* il ne répare rien rétroactivement : un état d'écrivain SANS journal de fenêtres (c'est le cas de
  tout processus démarré avant ce code) garde le comportement d'avant, c'est-à-dire **rien de
  certifiable** dès qu'un compteur est non nul ;
* si une seule fenêtre a été perdue (journal borné, dépassement), plus rien n'est sûr : on préfère
  `UNMEASURABLE` à une certification qui reposerait sur une preuve absente.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

#: Schéma du journal de fenêtres publié dans l'état de l'écrivain.
SCHEMA_FENETRES = "hypersmart.copy_vault_gap_windows.v1"

#: Nature des incidents. Chaque nom correspond à UN compteur de l'écrivain, pour que la
#: réconciliation « somme des fenêtres == compteur » soit vérifiable ligne à ligne.
TROU_ROTATION = "input_rotation"
TROU_EXPIRATION = "checkpoint_expired"
TROU_DEBORDEMENT = "pending_overflow"
#: 17/11/2026 — l'écrivain lui-même n'observait pas (arrêté, endormi, bloqué). Avant, un arrêt
#: n'était visible que par les checkpoints qu'il faisait expirer : sans checkpoint en attente, il
#: ne laissait AUCUNE fenêtre, et la durée « sûre » publiée à la porte de preuve l'incluait.
TROU_ARRET = "writer_outage"
NATURES = (TROU_ROTATION, TROU_EXPIRATION, TROU_DEBORDEMENT, TROU_ARRET)

#: Compteur de l'écrivain correspondant à chaque nature.
COMPTEUR_PAR_NATURE = {
    TROU_ROTATION: "input_rotations",
    TROU_EXPIRATION: "checkpoints_expired",
    TROU_DEBORDEMENT: "pending_overflow_rejected",
    TROU_ARRET: "writer_outages",
}

#: Compteurs nés APRÈS le journal. Absent d'un état écrit par un code antérieur, un tel compteur
#: vaut zéro : cet écrivain-là n'a jamais déclaré d'arrêt, ni vrai ni faux. Présent, il doit être
#: expliqué fenêtre par fenêtre, comme les autres.
COMPTEURS_FACULTATIFS = frozenset({"writer_outages"})

#: Le journal est borné : l'état est réécrit atomiquement à chaque passe, il ne doit pas enfler.
#: Au-delà, on ne tronque pas en silence : on compte les pertes et plus rien n'est certifiable.
MAX_FENETRES = 512

#: Marge de garde autour d'une fenêtre. Une horloge de réception et une horloge d'écriture ne sont
#: pas la même ; 250 ms coûtent très peu de couverture et évitent de certifier une ligne qui
#: touchait le bord d'un trou.
MARGE_MS = 250


def _entier(valeur: Any) -> int | None:
    """Entier EXACT et non négatif, ou ``None``. Un flottant n'est pas un horodatage."""
    if type(valeur) is not int or isinstance(valeur, bool):
        return None
    return valeur if valeur >= 0 else None


def fenetre(nature: str, *, debut_ms: int, fin_ms: int, n: int = 1) -> dict[str, Any]:
    """Une fenêtre de trou, normalisée. ``n`` = unités de compteur qu'elle justifie."""
    if nature not in NATURES:
        raise ValueError(f"nature de trou inconnue : {nature!r}")
    debut, fin = _entier(debut_ms), _entier(fin_ms)
    if debut is None or fin is None:
        raise ValueError("debut_ms et fin_ms doivent etre des entiers >= 0")
    compte = _entier(n)
    if not compte:
        raise ValueError("n doit etre un entier >= 1")
    if fin < debut:
        debut, fin = fin, debut            # un incident n'a pas d'ordre : on garde l'enveloppe
    return {"nature": nature, "debut_ms": debut, "fin_ms": fin, "n": compte}


def compacter(fenetres: Iterable[Mapping[str, Any]]) -> list[Any]:
    """Fusionne les fenêtres de MÊME nature qui se recouvrent ou se touchent, en sommant ``n``.

    17/11/2026 — UNE SEULE COUPURE POUVAIT FERMER L'ÉPOQUE POUR TOUJOURS. La veille du PC (42 min)
    a fait expirer 302 checkpoints : 302 fenêtres presque identiques, dans un journal plafonné à
    ``MAX_FENETRES`` (512). Une coupure à peine plus longue dépassait le plafond, le journal
    perdait des fenêtres, et plus rien n'était certifiable (`FENETRES_PERDUES`) — alors que tout
    l'incident tient dans UN intervalle.

    Ce qui est conservé EXACTEMENT : l'union des intervalles (on ne fusionne que ce qui se
    recouvre ou se touche) et la somme de ``n`` par nature (la réconciliation avec les compteurs
    de l'écrivain). Une fenêtre invalide est rendue telle quelle, en fin de liste : ce n'est pas
    à cette fonction de forme de la faire disparaître.
    """
    par_nature: dict[str, list[list[int]]] = {}
    invalides: list[Any] = []
    for f in fenetres or ():
        if isinstance(f, Mapping) and f.get("nature") in NATURES:
            debut, fin, n = _entier(f.get("debut_ms")), _entier(f.get("fin_ms")), _entier(f.get("n"))
            if debut is not None and fin is not None and n and fin >= debut:
                par_nature.setdefault(str(f["nature"]), []).append([debut, fin, n])
                continue
        invalides.append(dict(f) if isinstance(f, Mapping) else f)
    compactes: list[dict[str, Any]] = []
    for nature, groupe in par_nature.items():
        groupe.sort()
        courant = groupe[0]
        for debut, fin, n in groupe[1:]:
            if debut <= courant[1]:
                courant[1] = max(courant[1], fin)
                courant[2] += n
            else:
                compactes.append({"nature": nature, "debut_ms": courant[0], "fin_ms": courant[1],
                                  "n": courant[2]})
                courant = [debut, fin, n]
        compactes.append({"nature": nature, "debut_ms": courant[0], "fin_ms": courant[1],
                          "n": courant[2]})
    compactes.sort(key=lambda f: (f["debut_ms"], f["fin_ms"], f["nature"]))
    return compactes + invalides


def fusionner(fenetres: Iterable[Mapping[str, Any]]) -> list[tuple[int, int]]:
    """Fenêtres triées et fusionnées, marge de garde appliquée. Les invalides sont IGNORÉES ici :
    c'est ``intervalles_depuis_etat`` qui décide de fermer la porte, pas cette fonction de forme.
    """
    brutes: list[tuple[int, int]] = []
    for f in fenetres or ():
        if not isinstance(f, Mapping):
            continue
        debut, fin = _entier(f.get("debut_ms")), _entier(f.get("fin_ms"))
        if debut is None or fin is None or fin < debut:
            continue
        brutes.append((max(0, debut - MARGE_MS), fin + MARGE_MS))
    brutes.sort()
    fusionnees: list[tuple[int, int]] = []
    for debut, fin in brutes:
        if fusionnees and debut <= fusionnees[-1][1]:
            fusionnees[-1] = (fusionnees[-1][0], max(fusionnees[-1][1], fin))
        else:
            fusionnees.append((debut, fin))
    return fusionnees


def intervalles_surs(*, debut_ms: int, fin_ms: int,
                     fenetres: Iterable[Mapping[str, Any]]) -> list[tuple[int, int]]:
    """Le COMPLÉMENT des fenêtres de trou dans ``[debut_ms, fin_ms]`` : les intervalles sûrs."""
    debut, fin = _entier(debut_ms), _entier(fin_ms)
    if debut is None or fin is None or fin <= debut:
        return []
    surs: list[tuple[int, int]] = []
    curseur = debut
    for trou_debut, trou_fin in fusionner(fenetres):
        if trou_fin <= curseur:
            continue
        if trou_debut > fin:
            break
        if trou_debut > curseur:
            surs.append((curseur, min(trou_debut, fin)))
        curseur = max(curseur, trou_fin)
        if curseur >= fin:
            return surs
    if curseur < fin:
        surs.append((curseur, fin))
    return surs


def est_sur(ts_ms: Any, intervalles: Sequence[tuple[int, int]]) -> bool:
    """Cet horodatage de réception tombe-t-il dans un intervalle sûr ? Bornes INCLUSES."""
    instant = _entier(ts_ms)
    if instant is None or not intervalles:
        return False
    return any(debut <= instant <= fin for debut, fin in intervalles)


def couverture_ms(intervalles: Sequence[tuple[int, int]]) -> int:
    """Durée totale couverte, pour publier un dénominateur honnête."""
    return sum(max(0, fin - debut) for debut, fin in intervalles or ())


def journal_coherent(etat: Mapping[str, Any]) -> tuple[bool, str]:
    """``(coherent, raison)`` — le journal de fenêtres explique-t-il EXACTEMENT les compteurs ?

    C'est le contrôle qui empêche de certifier sur une preuve partielle : si l'écrivain a compté
    43 expirations et ne publie que 12 fenêtres, les 31 autres sont des trous dont on ne sait PAS
    où ils sont. On ferme.
    """
    if not isinstance(etat, Mapping):
        return False, "ETAT_ABSENT"
    if etat.get("gap_windows_schema") != SCHEMA_FENETRES:
        return False, "JOURNAL_DE_FENETRES_ABSENT"
    perdues = _entier(etat.get("gap_windows_dropped"))
    if perdues is None:
        return False, "COMPTEUR_DE_PERTES_INVALIDE"
    if perdues > 0:
        return False, f"FENETRES_PERDUES:{perdues}"
    fenetres = etat.get("gap_windows")
    if not isinstance(fenetres, list):
        return False, "JOURNAL_DE_FENETRES_INVALIDE"
    compteurs = etat.get("counters")
    if not isinstance(compteurs, Mapping):
        return False, "COMPTEURS_ABSENTS"
    cumul = dict.fromkeys(NATURES, 0)
    for f in fenetres:
        if not isinstance(f, Mapping) or f.get("nature") not in NATURES:
            return False, "FENETRE_INVALIDE"
        debut, fin, n = (_entier(f.get("debut_ms")), _entier(f.get("fin_ms")), _entier(f.get("n")))
        if debut is None or fin is None or not n or fin < debut:
            return False, "FENETRE_INVALIDE"
        cumul[str(f["nature"])] += n
    for nature, compteur in COMPTEUR_PAR_NATURE.items():
        attendu = _entier(compteurs.get(compteur))
        if attendu is None and compteur in COMPTEURS_FACULTATIFS and compteur not in compteurs:
            attendu = 0
        if attendu is None:
            return False, f"COMPTEUR_INVALIDE:{compteur}"
        if cumul[nature] != attendu:
            return False, f"FENETRES_INCOMPLETES:{compteur}={attendu},fenetres={cumul[nature]}"
    return True, "OK"


def intervalles_depuis_etat(etat: Mapping[str, Any], *, fin_ms: int,
                            ) -> tuple[list[tuple[int, int]], str]:
    """``(intervalles_surs, raison)`` depuis l'état de l'écrivain. Liste VIDE = rien n'est sûr.

    Une liste vide n'est jamais une erreur silencieuse : la raison dit toujours pourquoi.
    """
    coherent, raison = journal_coherent(etat)
    if not coherent:
        return [], raison
    debut = _entier(etat.get("clean_epoch_ms"))
    if not debut:
        return [], "EPOQUE_PROPRE_ABSENTE"
    intervalles = intervalles_surs(debut_ms=debut, fin_ms=fin_ms,
                                   fenetres=etat.get("gap_windows") or ())
    if not intervalles:
        return [], "AUCUN_INTERVALLE_SANS_TROU"
    return intervalles, "OK"


def ajouter_fenetre(etat: dict[str, Any], nouvelle: Mapping[str, Any]) -> None:
    """Enregistre une fenêtre dans l'état de l'écrivain, SANS jamais la perdre en silence."""
    etat.setdefault("gap_windows_schema", SCHEMA_FENETRES)
    fenetres = etat.get("gap_windows")
    if not isinstance(fenetres, list):
        fenetres = []
        etat["gap_windows"] = fenetres
    fenetres.append(dict(nouvelle))
    # Un incident = un intervalle : sans cela une seule coupure remplissait le journal.
    fenetres = compacter(fenetres)
    etat["gap_windows"] = fenetres
    if len(fenetres) > MAX_FENETRES:
        perdues = _entier(etat.get("gap_windows_dropped")) or 0
        trop = len(fenetres) - MAX_FENETRES
        etat["gap_windows"] = fenetres[trop:]
        # On DIT qu'on a perdu : a partir de la, plus rien n'est certifiable sur cette epoque.
        etat["gap_windows_dropped"] = perdues + trop
    else:
        etat.setdefault("gap_windows_dropped", 0)


def segmenter_l_epoque(etat: Any, *, recu_valide: bool,
                       ) -> tuple[list[tuple[int, int]], str, bool, int]:
    """``(intervalles_surs, raison, recu_valide, etat_ecrivain_ms)`` pour le chargeur de carnets.

    16/11/2026 — SEGMENTATION DES TROUS (bloqueur P0 de l'audit du 15/11).

    AVANT : le reçu exigeait ``input_rotations + checkpoints_expired + pending_overflow == 0``.
    Ces compteurs sont CUMULATIFS sur tout le run : 43 expirations et une rotation rendaient non
    certifiables les 25 875 checkpoints du run, y compris les minutes sans le moindre incident.
    Zéro ligne certifiable => zéro trade exécutable => aucune preuve possible, jamais.

    MAINTENANT : la spec autorise des trous globaux à condition de ne certifier que des
    intervalles EXECUTION_REPLAY_SAFE. L'écrivain publie la FENÊTRE de chaque trou (il est le seul
    à la connaître) ; on certifie une ligne si sa RÉCEPTION tombe hors de toute fenêtre.

    CE QUI RESTE FERMÉ, ET C'EST L'ESSENTIEL :

    * le reçu n'est valide que si la position de CHAQUE trou est connue (raison ``"OK"`` : la
      somme des fenêtres égale chaque compteur). Un seul trou dont on ignore la position referme
      l'époque entière, exactement comme avant ;
    * un état d'écrivain sans journal de fenêtres — tout processus démarré avant ce code — ne rend
      AUCUN intervalle sûr. Rien n'est réparé rétroactivement ;
    * aucun compteur n'est remis à zéro : un trou historique reste un trou historique.
    """
    brut = etat.get("updated_at_ms") if isinstance(etat, Mapping) else 0
    # même plage que `_optional_epoch_ms` du chargeur : un entier d'époque plausible, sinon 0
    etat_ecrivain_ms = brut if type(brut) is int and 0 <= brut <= 253_402_300_799_999 else 0
    if recu_valide and etat_ecrivain_ms > 0:
        surs, raison = intervalles_depuis_etat(etat, fin_ms=etat_ecrivain_ms)
    elif not recu_valide:
        surs, raison = [], "RECU_INVALIDE"
    else:
        surs, raison = [], "ETAT_ECRIVAIN_SANS_HORODATAGE"
    # La porte de preuve ne s'ouvre que si la segmentation est TOTALEMENT expliquée.
    return surs, raison, bool(recu_valide and raison == "OK" and surs), etat_ecrivain_ms


__all__ = [
    "SCHEMA_FENETRES", "MAX_FENETRES", "MARGE_MS", "NATURES", "COMPTEUR_PAR_NATURE",
    "TROU_ROTATION", "TROU_EXPIRATION", "TROU_DEBORDEMENT", "TROU_ARRET",
    "COMPTEURS_FACULTATIFS", "compacter",
    "fenetre", "fusionner", "intervalles_surs", "est_sur", "couverture_ms",
    "journal_coherent", "intervalles_depuis_etat", "ajouter_fenetre",
    "segmenter_l_epoque",
]
