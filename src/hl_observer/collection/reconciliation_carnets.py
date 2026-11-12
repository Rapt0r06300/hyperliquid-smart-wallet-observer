"""C110 / C82 / C83 — RÉCONCILIATION EN DIRECT : chaque fill de leader aura-t-il ses TROIS carnets ?

LE PROBLÈME QUE ÇA RÉSOUT. Aujourd'hui la boucle de retour sur la qualité de la collecte est
catastrophiquement lente : on collecte des jours, on certifie, on lance le labo (dizaines de minutes,
16 Go), et on découvre alors que **77 008 signaux sur 98 138** étaient inexploitables parce qu'aucun
carnet n'avait été enregistré dans les 30 s précédant le signal. Six jours pour apprendre un échec que
l'on pouvait voir en quelques minutes. Ce module fait ce constat DIRECTEMENT sur les rubans collectés,
sans certification et sans labo.

CE QU'IL VÉRIFIE. Pour qu'un fill de leader devienne un trade mesurable, il faut TROIS carnets :

* **référence** : un carnet dans la fenêtre ``[signal - lag_max, signal]`` (sinon aucun coût d'entrée
  n'est calculable — c'est le motif de refus n°1 mesuré) ;
* **entrée** : un carnet au plus tôt à ``signal + délai de copie`` (on n'entre pas avant d'avoir réagi) ;
* **sortie** : un carnet au plus tôt à ``signal + délai + horizon`` (sans lui, la position ne se clôture
  jamais et le trade est perdu) ;
* et les trois doivent partager la **même identité de connexion** (``connection_id`` + ``l2_gap_epoch``) :
  deux carnets issus de sockets différentes ou séparés par un trou ne prouvent pas une continuité
  d'observation.

HONNÊTETÉ SUR LA PORTÉE. C'est un test de CONDITIONS NÉCESSAIRES, pas le moteur d'exécution. Si un fill
échoue ici, il est certainement inexploitable ; s'il passe, il est *probablement* exécutable — le moteur
applique en plus la profondeur, la capacité, le spread, le funding. On ne promet donc jamais un PnL à
partir de cette jauge : on détecte un trou de collecte, ce qui est exactement son rôle. Les seuils sont
importés du moteur (jamais recopiés) pour que la jauge ne puisse pas diverger silencieusement.

Pur, 0 réseau, 0 ordre. Tout est injectable pour les tests.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.copy_vault_executable import (
    COPY_DELAY_MS,
    HORIZONS_MS,
    MAX_TARGET_LAG_MS,
)

#: Motifs, volontairement alignés sur le vocabulaire des refus du moteur.
SANS_REFERENCE = "AUCUN_CARNET_DE_REFERENCE"
SANS_ENTREE = "AUCUN_CARNET_D_ENTREE"
SANS_SORTIE = "AUCUN_CARNET_DE_SORTIE"
SANS_IDENTITE = "IDENTITE_DE_CONNEXION_INCOMPLETE"
IDENTITES_DIFFERENTES = "CARNETS_DE_CONNEXIONS_DIFFERENTES"
AUCUN_CARNET_DU_COIN = "AUCUN_CARNET_POUR_CE_COIN"
HORS_COUVERTURE = "HORS_COUVERTURE_DE_CE_COIN"

EXPLICATIONS = {
    SANS_REFERENCE: "aucun carnet dans la fenetre precedant le signal : cout d'entree non calculable",
    SANS_ENTREE: "aucun carnet apres le delai de reaction : l'entree n'a pas de prix observe",
    SANS_SORTIE: "aucun carnet a l'horizon : la position ne se cloture jamais",
    SANS_IDENTITE: "un carnet sans identite de connexion ne prouve pas la continuite d'observation",
    IDENTITES_DIFFERENTES: "les trois carnets viennent de sockets differentes ou sont separes par un trou",
    AUCUN_CARNET_DU_COIN: "ce coin n'est pas suivi du tout : aucun carnet collecte",
    HORS_COUVERTURE: "fill hors de la fenetre ou ce coin a des carnets : NON JUGEABLE, ce n'est pas un defaut de collecte",
}


def _identite(carnet: Mapping[str, Any]) -> tuple[Any, Any] | None:
    """(connection_id, l2_gap_epoch) ou ``None`` si l'identité est incomplète."""
    cid = carnet.get("connection_id")
    epoque = carnet.get("l2_gap_epoch")
    if cid in (None, "") or epoque is None:
        return None
    return (cid, epoque)


def _premier_a_partir_de(carnets: Sequence[Mapping[str, Any]], borne_ms: int) -> Mapping[str, Any] | None:
    """Le premier carnet dont l'horodatage est >= ``borne_ms`` (les carnets sont triés)."""
    for carnet in carnets:
        try:
            if int(carnet.get("ts_ms")) >= borne_ms:
                return carnet
        except (TypeError, ValueError):
            continue
    return None


def _dernier_dans(carnets: Sequence[Mapping[str, Any]], debut_ms: int,
                  fin_ms: int) -> Mapping[str, Any] | None:
    """Le dernier carnet dans ``[debut_ms, fin_ms]`` (le plus proche du signal, donc le plus pertinent)."""
    trouve = None
    for carnet in carnets:
        try:
            ts = int(carnet.get("ts_ms"))
        except (TypeError, ValueError):
            continue
        if debut_ms <= ts <= fin_ms:
            trouve = carnet
        elif ts > fin_ms:
            break
    return trouve


def reconcilier_un_fill(fill: Mapping[str, Any], carnets_du_coin: Sequence[Mapping[str, Any]], *,
                        delai_ms: int = COPY_DELAY_MS, horizon_ms: int | None = None,
                        lag_max_ms: int = MAX_TARGET_LAG_MS) -> dict[str, Any]:
    """Ce fill a-t-il ses trois carnets, avec une identité de connexion continue ?

    ``horizon_ms`` par défaut : le PLUS COURT des horizons du moteur — c'est le plus facile à
    satisfaire, donc un échec ici est un échec à tous les horizons (la lecture est conservatrice dans
    le bon sens : on ne surestime jamais la qualité de la collecte).
    """
    horizon = int(horizon_ms) if horizon_ms is not None else int(min(HORIZONS_MS))
    try:
        signal_ms = int(fill.get("ts_ms"))
    except (TypeError, ValueError):
        return {"complet": False, "motifs": [SANS_REFERENCE], "signal_ms": None}

    if not carnets_du_coin:
        return {"complet": False, "motifs": [AUCUN_CARNET_DU_COIN], "signal_ms": signal_ms}

    reference = _dernier_dans(carnets_du_coin, signal_ms - int(lag_max_ms), signal_ms)
    entree = _premier_a_partir_de(carnets_du_coin, signal_ms + int(delai_ms))
    sortie = _premier_a_partir_de(carnets_du_coin, signal_ms + int(delai_ms) + horizon)

    motifs: list[str] = []
    if reference is None:
        motifs.append(SANS_REFERENCE)
    if entree is None:
        motifs.append(SANS_ENTREE)
    if sortie is None:
        motifs.append(SANS_SORTIE)

    if not motifs:
        identites = [_identite(c) for c in (reference, entree, sortie)]
        if any(i is None for i in identites):
            motifs.append(SANS_IDENTITE)
        elif len(set(identites)) > 1:
            motifs.append(IDENTITES_DIFFERENTES)

    return {"complet": not motifs, "motifs": motifs, "signal_ms": signal_ms,
            "horizon_ms": horizon,
            "reference_ms": None if reference is None else int(reference.get("ts_ms")),
            "entree_ms": None if entree is None else int(entree.get("ts_ms")),
            "sortie_ms": None if sortie is None else int(sortie.get("ts_ms"))}


def couverture_du_coin(carnets: Sequence[Mapping[str, Any]], *, delai_ms: int, horizon_ms: int,
                       lag_max_ms: int) -> tuple[int, int] | None:
    """Fenetre de signaux JUGEABLES pour CE coin, vu ses propres carnets.

    POURQUOI C'EST CRUCIAL (correctif du 12/11, decouvert en verifiant la jauge contre les donnees).
    Chaque coin a sa PROPRE periode de couverture : un coin entre dans la liste suivie plus tard, ou
    sa lane demarre apres. Juger tous les fills sur une fenetre GLOBALE (premier au dernier carnet,
    tous coins confondus) fait apparaitre comme « sans carnet de reference » des fills qui tombent
    simplement avant que CE coin ait commence a etre suivi. Mesure : **114 fills sur 687** etaient
    ainsi accuses a tort — soit la quasi-totalite des echecs rapportes par la premiere version. La
    jauge disait 83 % alors que la collecte etait quasi parfaite dans sa vraie fenetre.
    """
    valides = []
    for carnet in carnets or ():
        try:
            valides.append(int(carnet.get("ts_ms")))
        except (TypeError, ValueError):
            continue
    if not valides:
        return None
    debut = min(valides) + int(lag_max_ms)
    fin = max(valides) - int(delai_ms) - int(horizon_ms)
    return (debut, fin) if debut <= fin else None


def reconcilier(fills: Sequence[Mapping[str, Any]],
                carnets_par_coin: Mapping[str, Sequence[Mapping[str, Any]]], *,
                delai_ms: int = COPY_DELAY_MS, horizon_ms: int | None = None,
                lag_max_ms: int = MAX_TARGET_LAG_MS,
                ignorer_hors_couverture: bool = True) -> dict[str, Any]:
    """La jauge : part des fills qui auront leurs trois carnets, et POURQUOI les autres non.

    Ventilée par coin (C83 : un coin actif sans aucun carnet saute aux yeux) et par motif (C82).

    ``ignorer_hors_couverture`` (défaut) écarte les fills tombant hors de la fenêtre où LEUR coin a
    des carnets : ils ne sont pas jugeables, et les compter comme des échecs accusait la collecte à
    tort (voir ``couverture_du_coin``). Les mettre à ``False`` donne l'ancienne lecture, pessimiste.
    """
    par_motif: dict[str, int] = {}
    par_coin: dict[str, dict[str, Any]] = {}
    complets = 0
    total = 0
    non_jugeables = 0
    horizon_retenu = int(horizon_ms) if horizon_ms is not None else int(min(HORIZONS_MS))
    couvertures = {
        coin: couverture_du_coin(carnets, delai_ms=delai_ms, horizon_ms=horizon_retenu,
                                 lag_max_ms=lag_max_ms)
        for coin, carnets in (carnets_par_coin or {}).items()
    }

    for fill in fills or ():
        coin = str(fill.get("coin") or "")
        if not coin:
            continue
        if ignorer_hors_couverture:
            fenetre = couvertures.get(coin)
            try:
                ts = int(fill.get("ts_ms"))
            except (TypeError, ValueError):
                ts = None
            if fenetre is not None and ts is not None and not (fenetre[0] <= ts <= fenetre[1]):
                non_jugeables += 1
                fiche = par_coin.setdefault(coin, {"fills": 0, "complets": 0, "motifs": {}})
                fiche.setdefault("non_jugeables", 0)
                fiche["non_jugeables"] += 1
                continue
        total += 1
        carnets = carnets_par_coin.get(coin) or ()
        detail = reconcilier_un_fill(fill, carnets, delai_ms=delai_ms, horizon_ms=horizon_ms,
                                     lag_max_ms=lag_max_ms)
        fiche = par_coin.setdefault(coin, {"fills": 0, "complets": 0, "motifs": {}})
        fiche["fills"] += 1
        if detail["complet"]:
            complets += 1
            fiche["complets"] += 1
        for motif in detail["motifs"]:
            par_motif[motif] = par_motif.get(motif, 0) + 1
            fiche["motifs"][motif] = fiche["motifs"].get(motif, 0) + 1

    for fiche in par_coin.values():
        fiche.setdefault("non_jugeables", 0)
        fiche["incomplets"] = fiche["fills"] - fiche["complets"]
        fiche["part_complete"] = round(fiche["complets"] / fiche["fills"], 4) if fiche["fills"] else 0.0

    return {
        "fills": total,
        "fills_non_jugeables_hors_couverture": non_jugeables,
        "complets": complets,
        "incomplets": total - complets,
        "part_complete": round(complets / total, 4) if total else 0.0,
        "par_motif": dict(sorted(par_motif.items(), key=lambda kv: (-kv[1], kv[0]))),
        "explications": {m: EXPLICATIONS.get(m, m) for m in par_motif},
        "par_coin": par_coin,
        "coins_sans_aucun_carnet": sorted(
            coin for coin, f in par_coin.items() if f["motifs"].get(AUCUN_CARNET_DU_COIN)),
        "delai_ms": int(delai_ms),
        "horizon_ms": int(horizon_ms) if horizon_ms is not None else int(min(HORIZONS_MS)),
        "lag_max_ms": int(lag_max_ms),
        "portee": "CONDITIONS_NECESSAIRES_SEULEMENT_PAS_LE_MOTEUR_D_EXECUTION",
    }


def coins_a_corriger(jauge: Mapping[str, Any], *, maximum: int = 20) -> list[dict[str, Any]]:
    """Coins classés par nombre de fills INCOMPLETS : la file d'attente de correction de la collecte."""
    lignes = [
        {"coin": coin, "fills": f["fills"], "incomplets": f["incomplets"],
         "part_complete": f["part_complete"],
         "motif_dominant": next(iter(sorted(f["motifs"].items(), key=lambda kv: (-kv[1], kv[0]))), (None,))[0]}
        for coin, f in (jauge.get("par_coin") or {}).items() if f.get("incomplets")
    ]
    lignes.sort(key=lambda ligne: (-ligne["incomplets"], ligne["coin"]))
    return lignes[:maximum]


def resume_lisible(jauge: Mapping[str, Any], *, maximum: int = 4) -> str:
    """Une phrase : où en est la collecte, et ce qui la bloque."""
    total = int(jauge.get("fills") or 0)
    if not total:
        return "aucun fill de leader dans la fenetre observee : rien a reconcilier"
    part = float(jauge.get("part_complete") or 0.0)
    if part >= 1.0:
        return f"{total} fills : TOUS auront leurs trois carnets"
    motifs = list((jauge.get("par_motif") or {}).items())[:maximum]
    detail = " ; ".join(f"{nombre} x {motif}" for motif, nombre in motifs)
    return (f"{int(jauge.get('complets') or 0)}/{total} fills ({part * 100:.0f} %) auront leurs trois "
            f"carnets — manques : {detail}")


__all__ = ["SANS_REFERENCE", "SANS_ENTREE", "SANS_SORTIE", "SANS_IDENTITE", "IDENTITES_DIFFERENTES",
           "AUCUN_CARNET_DU_COIN", "HORS_COUVERTURE", "EXPLICATIONS", "couverture_du_coin", "reconcilier_un_fill", "reconcilier",
           "coins_a_corriger", "resume_lisible"]
