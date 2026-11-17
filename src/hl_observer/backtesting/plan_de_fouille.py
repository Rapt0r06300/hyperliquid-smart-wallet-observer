"""PLAN DE FOUILLE du coffre : exploiter 162 millions de lignes avec 2 Go de mémoire.

POURQUOI (mesure du 16/11/2026). Le coffre LOCAL contient **5 427 shards, 162 286 723 lignes,
9,55 Go compressés** — soit de l'ordre de 39 Go de dictionnaires Python. Le pont du labo porte
depuis le 16/11 un plafond de 8 000 000 de lignes : il charge donc au mieux **5 % du corpus**, et
le dit (``chargement_arrete = PLAFOND_LIGNES``). C'est honnête, mais ce n'est pas exploiter.

« Lever le plafond » serait la mauvaise réponse : la règle de l'opérateur est « on ralentit ou on
rétrécit, on ne crashe JAMAIS », et une étude qui tue la machine ne mesure rien. La bonne réponse
est de **ne pas tout charger à la fois** : découper l'axe du temps en GALERIES dont chacune tient
dans le budget, les parcourir toutes, et agréger. Une mine ne se vide pas d'un coup ; elle
s'exploite par galeries.

CE QUE CE MODULE GARANTIT :

* **couverture complète et prouvée** : les galeries sont contiguës et disjointes, bornes inclusives
  ``[debut_ms, fin_ms]``, ``galerie[i].fin_ms + 1 == galerie[i+1].debut_ms``. ``couverture()``
  revérifie l'absence de trou ET de recouvrement — sans quoi une ligne serait comptée deux fois,
  ou jamais.
* **un budget tenu, pas espéré** : la taille d'une galerie vient d'une densité de lignes mesurée
  sur l'index (``deposes`` réparti sur la durée du shard), pas d'un découpage arbitraire par jour.
* **l'estimation est déclarée comme telle** : la densité est supposée uniforme DANS un shard — ce
  qui est faux au détail. ``parcourir()`` compare donc ``lignes_estimees`` à ``lignes_lues`` et
  publie l'écart. Une galerie qui déborde est signalée, jamais masquée.
* **rien ne se perd sur Ctrl+C** : chaque galerie terminée est écrite et synchronisée sur le disque
  avant la suivante. Une reprise saute les galeries déjà faites au lieu de les refaire.
* **une galerie indivisible est dite** : si un seul instant porte plus de lignes que le budget, on
  l'émet seul avec ``indivisible=True``. On ne prétend pas l'avoir découpé.

CE QU'IL NE FAIT PAS. Il ne mesure aucune économie : il donne à une étude le moyen de voir tout le
corpus. Ce qu'on en conclut reste soumis aux mêmes règles de preuve (SAFE pour prouver, LOCAL pour
chercher) et aux états honnêtes PROVEN / PROMISING / MORE_DATA / UNMEASURABLE / REJECTED.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.ops.echec_silencieux import noter as _noter_echec

SCHEMA = "hypersmart.plan_de_fouille.v1"

#: Coût mémoire d'une ligne JSON décodée en dictionnaire Python. MESURÉ le 16/11 : les familles de
#: replay totalisent 59 832 338 lignes pour ~13,9 Go résidents, soit ~232 octets par ligne. On
#: arrondit au-dessus : un budget doit se tromper du côté prudent.
OCTETS_PAR_LIGNE_EN_RAM = 240

#: Part de la mémoire LIBRE qu'une fouille s'autorise. Volontairement basse : la campagne de
#: collecte tourne en même temps et c'est elle qui a la priorité (ses données ne se rattrapent pas).
PART_RAM_PAR_DEFAUT = 0.30

#: Garde-fous du budget : assez pour qu'une galerie soit utile, jamais plus que le plafond du pont.
BUDGET_PLANCHER_LIGNES = 100_000
BUDGET_PLAFOND_LIGNES = 8_000_000

#: Au-delà de ce nombre, une fouille refuse de planifier : c'est le signe d'un budget absurde
#: (galeries d'une milliseconde) plutôt que d'un corpus immense.
MAX_GALERIES = 20_000


def _entier(valeur: Any) -> int | None:
    if type(valeur) is not int or isinstance(valeur, bool):
        return None
    return valeur


def budget_lignes(*, dispo_octets: int | None = None, part: float = PART_RAM_PAR_DEFAUT,
                  plancher: int = BUDGET_PLANCHER_LIGNES,
                  plafond: int = BUDGET_PLAFOND_LIGNES, psutil_mod: Any = None) -> dict[str, Any]:
    """Combien de lignes une galerie peut tenir, d'après la mémoire RÉELLEMENT libre.

    Interroge le gouverneur mémoire (``ops.budget_ram``) et applique en plus son facteur d'ampleur :
    sous pression, les galeries rétrécissent au lieu que la fouille échoue.
    """
    niveau = "INCONNU"
    facteur = 1.0
    if dispo_octets is None:
        try:
            from hl_observer.ops import budget_ram as BR
            dispo_octets = BR.memoire_disponible_octets(psutil_mod=psutil_mod)
            niveau = BR.niveau_pression(dispo_octets=dispo_octets, psutil_mod=psutil_mod)
            facteur = BR.facteur_d_ampleur(niveau)
        except Exception:  # noqa: BLE001 — un gouverneur en panne ne doit pas bloquer la recherche
            dispo_octets = 0
            niveau = "INDISPONIBLE"
    brut = int(max(0, int(dispo_octets)) * max(0.0, float(part)) * max(0.0, float(facteur)))
    lignes = brut // OCTETS_PAR_LIGNE_EN_RAM
    borne = max(int(plancher), min(int(plafond), int(lignes)))
    return {
        "lignes": borne,
        "dispo_octets": int(dispo_octets or 0),
        "part": float(part),
        "niveau_ram": niveau,
        "facteur_ampleur": float(facteur),
        "octets_par_ligne": OCTETS_PAR_LIGNE_EN_RAM,
        "borne_appliquee": ("PLANCHER" if lignes < plancher else
                            "PLAFOND" if lignes > plafond else "AUCUNE"),
    }


def _shards_de(shards: Iterable[Mapping[str, Any]], familles: Sequence[str],
               coins: Sequence[str] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Les shards de ces familles qui croisent ces coins : (datés, sans bornes de temps)."""
    voulues = {str(f) for f in familles}
    voulus = {str(c) for c in coins} if coins else None
    dates: list[dict[str, Any]] = []
    sans_bornes: list[dict[str, Any]] = []
    for s in shards or ():
        if not isinstance(s, Mapping) or str(s.get("famille") or "") not in voulues:
            continue
        ses_coins = s.get("coins")
        if voulus is not None and isinstance(ses_coins, list) and ses_coins:
            if not (voulus & {str(c) for c in ses_coins}):
                continue
        t0, t1 = _entier(s.get("ts_min_ms")), _entier(s.get("ts_max_ms"))
        if t0 is None or t1 is None or t1 < t0:
            sans_bornes.append(dict(s))
            continue
        dates.append(dict(s))
    return dates, sans_bornes


def _segments(shards: Sequence[Mapping[str, Any]], debut_ms: int,
              fin_ms: int) -> list[dict[str, Any]]:
    """Découpe [debut, fin] aux frontières des shards ; chaque segment a une densité constante.

    Densité = somme, sur les shards qui couvrent le segment, de ``deposes / duree_du_shard``. C'est
    l'hypothèse d'uniformité DANS un shard : approximative au détail, suffisante pour dimensionner,
    et vérifiée après coup par ``parcourir()``.
    """
    frontieres: set[int] = {int(debut_ms), int(fin_ms) + 1}
    for s in shards:
        t0, t1 = int(s["ts_min_ms"]), int(s["ts_max_ms"])
        if t1 < debut_ms or t0 > fin_ms:
            continue
        frontieres.add(max(int(debut_ms), t0))
        frontieres.add(min(int(fin_ms) + 1, t1 + 1))
    bornes = sorted(frontieres)
    # densité par shard, pré-calculée une fois
    denses: list[tuple[int, int, float]] = []
    for s in shards:
        t0, t1 = int(s["ts_min_ms"]), int(s["ts_max_ms"])
        n = _entier(s.get("deposes")) or 0
        duree = max(1, t1 - t0 + 1)
        denses.append((t0, t1, n / duree))
    denses.sort(key=lambda d: d[0])
    segments: list[dict[str, Any]] = []
    for a, b in zip(bornes, bornes[1:]):
        if b <= a:
            continue
        densite = 0.0
        for t0, t1, d in denses:
            if t0 >= b:
                break
            if t1 >= a:
                densite += d
        if densite <= 0.0:
            continue
        segments.append({"debut_ms": a, "fin_ms": b - 1, "densite": densite,
                         "lignes": densite * (b - a)})
    return segments


def galeries(shards: Iterable[Mapping[str, Any]], *, familles: Sequence[str],
             budget: int, debut_ms: int | None = None, fin_ms: int | None = None,
             coins: Sequence[str] | None = None,
             max_galeries: int = MAX_GALERIES) -> dict[str, Any]:
    """Le plan : des fenêtres contiguës et disjointes qui couvrent TOUT, chacune sous le budget.

    Pur : ne touche aucun fichier. ``shards`` vient de ``LOCAL_INDEX.json``.
    """
    familles = [str(f) for f in familles]
    dates, sans_bornes = _shards_de(shards, familles, coins)
    if not dates:
        return {"schema": SCHEMA, "familles": familles, "galeries": [],
                "sans_bornes": sans_bornes, "budget": int(budget),
                "lignes_estimees": 0, "raison": "AUCUN_SHARD_DATE",
                "coins": list(coins) if coins else None}
    t_min = min(int(s["ts_min_ms"]) for s in dates)
    t_max = max(int(s["ts_max_ms"]) for s in dates)
    a = t_min if debut_ms is None else max(t_min, int(debut_ms))
    b = t_max if fin_ms is None else min(t_max, int(fin_ms))
    if b < a:
        return {"schema": SCHEMA, "familles": familles, "galeries": [],
                "sans_bornes": sans_bornes, "budget": int(budget),
                "lignes_estimees": 0, "raison": "FENETRE_VIDE",
                "coins": list(coins) if coins else None}

    plafond = max(1, int(budget))
    segs = _segments(dates, a, b)
    sorties: list[dict[str, Any]] = []
    courant_debut: int | None = None
    courant_fin: int | None = None
    courant_lignes = 0.0

    def fermer(indivisible: bool = False) -> None:
        nonlocal courant_debut, courant_fin, courant_lignes
        if courant_debut is None or courant_fin is None:
            return
        sorties.append({
            "rang": len(sorties) + 1,
            "debut_ms": int(courant_debut), "fin_ms": int(courant_fin),
            "lignes_estimees": int(round(courant_lignes)),
            "indivisible": bool(indivisible),
        })
        courant_debut = courant_fin = None
        courant_lignes = 0.0

    for seg in segs:
        sd, sf, densite = seg["debut_ms"], seg["fin_ms"], seg["densite"]
        reste_debut = sd
        while reste_debut <= sf:
            if courant_debut is None:
                courant_debut, courant_fin, courant_lignes = reste_debut, reste_debut - 1, 0.0
            place = plafond - courant_lignes
            if place <= 0:
                fermer()
                continue
            # combien de millisecondes de ce segment tiennent dans la place restante
            tenables = int(place / densite) if densite > 0 else (sf - reste_debut + 1)
            if tenables <= 0:
                if courant_lignes <= 0:
                    # une seule milliseconde depasse deja le budget : on le DIT.
                    courant_fin = reste_debut
                    courant_lignes = densite
                    fermer(indivisible=True)
                    reste_debut += 1
                    continue
                fermer()
                continue
            pris = min(tenables, sf - reste_debut + 1)
            courant_fin = reste_debut + pris - 1
            courant_lignes += densite * pris
            reste_debut += pris
            if courant_lignes >= plafond:
                fermer()
            if len(sorties) >= int(max_galeries):
                fermer()
                return {"schema": SCHEMA, "familles": familles, "galeries": sorties,
                        "sans_bornes": sans_bornes, "budget": plafond,
                        "lignes_estimees": sum(g["lignes_estimees"] for g in sorties),
                        "raison": "TROP_DE_GALERIES",
                        "coins": list(coins) if coins else None,
                        "fenetre_ms": [a, b]}
    fermer()
    # Les galeries doivent se toucher EXACTEMENT : on comble les intervalles sans densite, pour
    # qu'aucune ligne ne puisse tomber entre deux galeries si l'index se revelait imprecis.
    jointives: list[dict[str, Any]] = []
    for g in sorties:
        if jointives and g["debut_ms"] > jointives[-1]["fin_ms"] + 1:
            jointives[-1]["fin_ms"] = g["debut_ms"] - 1
        jointives.append(g)
    if jointives:
        jointives[0]["debut_ms"] = a
        jointives[-1]["fin_ms"] = b
    for rang, g in enumerate(jointives, start=1):
        g["rang"] = rang
        g["duree_ms"] = g["fin_ms"] - g["debut_ms"] + 1
    return {
        "schema": SCHEMA, "familles": familles, "galeries": jointives,
        "sans_bornes": sans_bornes, "budget": plafond,
        "lignes_estimees": sum(g["lignes_estimees"] for g in jointives),
        "lignes_indexees": sum(_entier(s.get("deposes")) or 0 for s in dates),
        "shards_concernes": len(dates),
        "fenetre_ms": [a, b],
        "coins": list(coins) if coins else None,
        "raison": "OK",
    }


def couverture(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Revérifie le plan : contiguïté, absence de recouvrement, budget respecté.

    Un plan qui laisse un trou perdrait des lignes ; un plan qui se recouvre les compterait deux
    fois. Les deux falsifieraient la mesure, donc les deux sont des échecs explicites.
    """
    gals = list(plan.get("galeries") or ())
    trous: list[dict[str, int]] = []
    recouvrements: list[dict[str, int]] = []
    depassements: list[dict[str, Any]] = []
    budget = int(plan.get("budget") or 0)
    for precedent, suivant in zip(gals, gals[1:]):
        if suivant["debut_ms"] > precedent["fin_ms"] + 1:
            trous.append({"apres_rang": precedent["rang"],
                          "debut_ms": precedent["fin_ms"] + 1,
                          "fin_ms": suivant["debut_ms"] - 1})
        elif suivant["debut_ms"] <= precedent["fin_ms"]:
            recouvrements.append({"rangs": [precedent["rang"], suivant["rang"]],
                                  "debut_ms": suivant["debut_ms"],
                                  "fin_ms": precedent["fin_ms"]})
    for g in gals:
        if budget and g["lignes_estimees"] > budget and not g.get("indivisible"):
            depassements.append({"rang": g["rang"], "lignes_estimees": g["lignes_estimees"]})
    fenetre = plan.get("fenetre_ms") or [None, None]
    bords_ok = bool(gals) and gals[0]["debut_ms"] == fenetre[0] and gals[-1]["fin_ms"] == fenetre[1]
    return {
        "schema": SCHEMA,
        "galeries": len(gals),
        "trous": trous, "recouvrements": recouvrements, "depassements": depassements,
        "bords_alignes": bords_ok,
        "indivisibles": [g["rang"] for g in gals if g.get("indivisible")],
        "sans_bornes": len(plan.get("sans_bornes") or ()),
        "complete": bool(gals) and not trous and not recouvrements and not depassements and bords_ok,
    }


def _empreinte(galerie: Mapping[str, Any], familles: Sequence[str]) -> str:
    """Identité stable d'une galerie, pour qu'une reprise reconnaisse ce qui est déjà fait."""
    brut = json.dumps({"d": galerie.get("debut_ms"), "f": galerie.get("fin_ms"),
                       "fam": sorted(str(f) for f in familles)},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:16]


def agreger(mesures: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Agrège les mesures des galeries — et REFUSE ce qui ne s'agrège pas honnêtement.

    Règles, volontairement étroites :

    * ``int`` : sommé. Un suffixe ``_max`` / ``_min`` prend l'extremum au lieu de la somme.
    * ``dict`` à valeurs entières : fusionné clé par clé (histogrammes par jour, par coin).
    * ``list`` de chaînes : union, bornée à 10 000 éléments distincts, troncature déclarée.
    * tout le reste — un ``float`` isolé, une moyenne sans son effectif — part dans
      ``non_agregeable``. Faire la moyenne de moyennes de tailles différentes est un faux, et un
      faux silencieux est pire qu'un trou déclaré.
    """
    sommes: dict[str, int] = {}
    extremums: dict[str, int] = {}
    histos: dict[str, dict[str, int]] = {}
    unions: dict[str, set[str]] = {}
    tronques: set[str] = set()
    non_agregeable: dict[str, str] = {}
    for m in mesures or ():
        for cle, valeur in (m or {}).items():
            if type(valeur) is int and not isinstance(valeur, bool):
                if cle.endswith("_max"):
                    extremums[cle] = valeur if cle not in extremums else max(extremums[cle], valeur)
                elif cle.endswith("_min"):
                    extremums[cle] = valeur if cle not in extremums else min(extremums[cle], valeur)
                else:
                    sommes[cle] = sommes.get(cle, 0) + valeur
            elif isinstance(valeur, Mapping) and all(
                    type(v) is int and not isinstance(v, bool) for v in valeur.values()):
                cible = histos.setdefault(cle, {})
                for k, v in valeur.items():
                    cible[str(k)] = cible.get(str(k), 0) + int(v)
            elif isinstance(valeur, list) and all(isinstance(v, str) for v in valeur):
                cible_u = unions.setdefault(cle, set())
                for v in valeur:
                    if len(cible_u) >= 10_000:
                        tronques.add(cle)
                        break
                    cible_u.add(v)
            else:
                non_agregeable[cle] = type(valeur).__name__
    return {
        "schema": SCHEMA,
        "sommes": dict(sorted(sommes.items())),
        "extremums": dict(sorted(extremums.items())),
        "histogrammes": {k: dict(sorted(v.items())) for k, v in sorted(histos.items())},
        "unions": {k: sorted(v) for k, v in sorted(unions.items())},
        "unions_cardinal": {k: len(v) for k, v in sorted(unions.items())},
        "unions_tronquees": sorted(tronques),
        "non_agregeable": dict(sorted(non_agregeable.items())),
        "galeries_mesurees": len(list(mesures or ())),
    }


def _journal_existant(chemin: Path, familles: Sequence[str]) -> dict[str, dict[str, Any]]:
    faits: dict[str, dict[str, Any]] = {}
    if not chemin.is_file():
        return faits
    try:
        with chemin.open("r", encoding="utf-8") as fh:
            for brut in fh:
                brut = brut.strip()
                if not brut:
                    continue
                try:
                    ligne = json.loads(brut)
                except ValueError:
                    continue   # ligne tronquee par une coupure : on la refera, jamais on ne la croit
                if isinstance(ligne, dict) and isinstance(ligne.get("empreinte"), str):
                    faits[ligne["empreinte"]] = ligne
    except OSError:
        return {}
    return faits


def parcourir(plan: Mapping[str, Any], mesurer: Callable[[Mapping[str, Any]], Mapping[str, Any]],
              *, journal: str | Path | None = None,
              progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Parcourt TOUTES les galeries, agrège, et ne perd rien sur Ctrl+C.

    ``mesurer(galerie)`` reçoit la fenêtre et rend ses mesures (voir ``agreger`` pour ce qui
    s'agrège). Chaque galerie terminée est écrite puis synchronisée sur le disque : une
    interruption coûte au pire la galerie en cours, et une reprise saute celles déjà faites.
    """
    familles = list(plan.get("familles") or ())
    gals = list(plan.get("galeries") or ())
    chemin = Path(journal) if journal is not None else None
    deja = _journal_existant(chemin, familles) if chemin is not None else {}
    mesures: list[dict[str, Any]] = []
    reprises = 0
    faites = 0
    interrompu = False
    handle = None
    if chemin is not None:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        handle = chemin.open("a", encoding="utf-8")
    try:
        for g in gals:
            empreinte = _empreinte(g, familles)
            if empreinte in deja:
                mesures.append(dict(deja[empreinte].get("mesures") or {}))
                reprises += 1
                continue
            try:
                brut = mesurer(g)
            except KeyboardInterrupt:
                interrompu = True
                break
            mesure = dict(brut or {})
            mesures.append(mesure)
            faites += 1
            if handle is not None:
                handle.write(json.dumps({
                    "schema": SCHEMA, "empreinte": empreinte, "rang": g.get("rang"),
                    "debut_ms": g.get("debut_ms"), "fin_ms": g.get("fin_ms"),
                    "lignes_estimees": g.get("lignes_estimees"), "mesures": mesure,
                }, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())   # la galerie est acquise, meme si tout s'arrete apres
                except OSError as exc:
                    # Sans fsync, la galerie est ecrite mais pas garantie sur disque : la promesse
                    # « Ctrl+C ne perd rien » s'affaiblit, et il faut le savoir.
                    _noter_echec("backtesting/plan_de_fouille.py:fsync_journal", exc)
            if progress is not None:
                progress(f"galerie {g.get('rang')}/{len(gals)} · "
                         f"{mesure.get('lignes_lues', 0):,} lignes lues")
    except KeyboardInterrupt:
        interrompu = True
    finally:
        if handle is not None:
            handle.close()
    total = agreger(mesures)
    estimees = sum(int(g.get("lignes_estimees") or 0) for g in gals[:len(mesures)])
    lues = int(total["sommes"].get("lignes_lues", 0))
    return {
        "schema": SCHEMA,
        "etat": "INTERROMPU" if interrompu else "COMPLET",
        "galeries_planifiees": len(gals),
        "galeries_faites": faites,
        "galeries_reprises": reprises,
        "galeries_restantes": len(gals) - len(mesures),
        "total": total,
        "lignes_estimees": estimees,
        "lignes_lues": lues,
        "ecart_estimation": (None if estimees == 0 else round((lues - estimees) / estimees, 4)),
        "journal": None if chemin is None else str(chemin),
    }


__all__ = [
    "SCHEMA", "OCTETS_PAR_LIGNE_EN_RAM", "PART_RAM_PAR_DEFAUT",
    "BUDGET_PLANCHER_LIGNES", "BUDGET_PLAFOND_LIGNES", "MAX_GALERIES",
    "budget_lignes", "galeries", "couverture", "agreger", "parcourir",
]
