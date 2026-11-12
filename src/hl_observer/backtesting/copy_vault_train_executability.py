"""Le segment TRAIN contient-il au moins un trade EXÉCUTABLE ? Sinon la recherche tournerait à vide.

POURQUOI. Mesuré le 2026-11-12 sur le corpus réel : 128 essais de recherche (32 minutes) ont tous rendu
« non mesurable », parce qu'AUCUN signal du segment TRAIN ne pouvait être exécuté — les carnets collectés
localement ne portaient pas l'identité de leur connexion (refus ``L2_CONNECTION_IDENTITY_INCOMPLETE``) et
les rares carnets certifiés s'arrêtaient avant la sortie des positions (``STALE_OR_MISSING_EXIT_BOOK``).
Ces refus ne dépendent d'aucun paramètre cherché : aucun réglage ne pouvait produire un trade. Les essais
n'en ont pas moins été comptés dans la correction de multiplicité, ce qui durcit pour rien toute preuve
future.

CE QUE FAIT LA SONDE. Avant la recherche, elle rejoue les signaux du segment TRAIN avec les règles
d'exécution canoniques (carnets causaux, identité de connexion prouvée), sans aucun filtre de stratégie,
à chacun des horizons que la recherche explore. Si aucun horizon ne produit un seul trade, le labo
s'arrête sur ``MORE_DATA / TRAIN_NOT_EXECUTABLE`` et dit pourquoi, motif par motif ET **coin par coin** :
la ventilation par coin est la carte de ce qu'il reste à collecter (quels marchés manquent de carnets),
qui pilote directement les collecteurs (``tools/generer_coins_lanes.py``).

LIMITE DÉCLARÉE. La sonde utilise le délai de copie et les tolérances du protocole ; la recherche fait
varier la tolérance du carnet de référence. Un réglage plus tolérant ne lève ni l'absence d'identité de
connexion ni l'absence de carnet de sortie : le verdict de la sonde reste valable pour ces deux motifs.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.copy_vault_executable import replay_metaorders
from hl_observer.backtesting.copy_vault_protocol import HORIZONS_MS

RAISON = "TRAIN_NOT_EXECUTABLE"
_COMPTEURS_NON_MOTIFS = frozenset({"metaorders_considered", "completed_positions"})

#: Ce que chaque refus veut dire, et ce qu'il faut pour le lever.
EXPLICATIONS: dict[str, str] = {
    "L2_CONNECTION_IDENTITY_INCOMPLETE":
        "carnets collectés sans identité de connexion (collecteurs d'avant le 2026-11-12) : "
        "le moteur ne peut pas prouver que référence, entrée et sortie viennent du même flux",
    "L2_GAP_EPOCH_IDENTITY_INCOMPLETE": "carnets collectés sans époque de trou : continuité du flux non prouvée",
    "L2_CONNECTION_GAP_CROSSED": "une reconnexion sépare l'entrée de la sortie",
    "L2_GAP_EPOCH_CROSSED": "un trou du flux sépare l'entrée de la sortie",
    "STALE_OR_MISSING_REFERENCE_BOOK": "aucun carnet dans les 30 secondes avant le signal",
    "STALE_OR_MISSING_ENTRY_BOOK": "aucun carnet au moment de l'entrée (signal + délai de copie)",
    "STALE_OR_MISSING_EXIT_BOOK": "aucun carnet au moment de la sortie : la collecte s'arrête avant la fin de la position",
    "NO_OBSERVED_BOOK_FOR_COIN": "aucun carnet collecté pour ce marché",
    "NON_CAUSAL_FORWARD_SIGNAL": "signal reconstitué après coup (pas observé en direct)",
    "NON_CAUSAL_FORWARD_BOOK": "carnet non observé en direct",
    "FUNDING_BOUNDARY_UNPRICED": "la position chevauche un paiement de funding non chiffré",
    "INVALID_OBSERVED_BOOK": "carnet invalide",
    "INVALID_OBSERVED_BOOK_L2": "niveaux du carnet invalides",
}


def _sonder_univers(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    debut: int,
    fin: int,
    horizons_ms: Sequence[int],
) -> dict[str, Any]:
    """Exécutabilité d'un jeu de signaux : exécutés (meilleur horizon), refus par motif, par horizon."""
    par_horizon: dict[str, int] = {}
    pire_par_motif: dict[str, int] = {}
    meilleur: tuple[int, int, dict[str, int]] | None = None
    signaux = 0
    for horizon in horizons_ms:
        _trades, audit = replay_metaorders(
            metaorders, books_by_coin, horizon_ms=int(horizon), start_ms=debut, end_ms=fin,
            require_causal_observation=True,
        )
        executes = int(audit.get("completed_positions") or 0)
        par_horizon[str(int(horizon))] = executes
        signaux = max(signaux, int(audit.get("metaorders_considered") or 0))
        refus_horizon = {
            motif: int(nombre) for motif, nombre in audit.items()
            if motif not in _COMPTEURS_NON_MOTIFS and int(nombre) > 0
        }
        for motif, nombre in refus_horizon.items():
            pire_par_motif[motif] = max(pire_par_motif.get(motif, 0), nombre)
        if meilleur is None or executes > meilleur[0]:
            meilleur = (executes, int(horizon), refus_horizon)
    executes, horizon, refus = meilleur if meilleur is not None else (0, 0, {})
    if executes == 0:
        # Aucun horizon n'exécute rien : on montre, par motif, son pire décompte tous horizons confondus
        # (un horizon court bute sur la sortie, un long sur l'identité : les deux comptent).
        refus = pire_par_motif
    return {
        "signaux": signaux, "executables": executes, "meilleur_horizon_ms": horizon,
        "trades_executables_par_horizon_ms": par_horizon,
        "refus_par_motif": dict(sorted(refus.items(), key=lambda item: (-item[1], item[0]))),
    }


def sonder_train(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    bounds: Mapping[str, Any],
    *,
    horizons_ms: Sequence[int] = HORIZONS_MS,
    par_coin: bool = True,
) -> dict[str, Any]:
    """Exécutabilité du segment TRAIN, globale et (par défaut) ventilée par coin.

    La ventilation par coin est la **carte de collecte** : les coins avec le plus de signaux non
    exécutables sont exactement ceux dont il manque des carnets. Elle pilote ``generer_coins_lanes``.
    """
    debut, fin = int(bounds["train_start_ms"]), int(bounds["train_end_ms"])
    global_ = _sonder_univers(metaorders, books_by_coin, debut, fin, horizons_ms)
    ventilation: dict[str, dict[str, Any]] = {}
    if par_coin:
        par_coin_metas: dict[str, list[Mapping[str, Any]]] = {}
        for meta in metaorders:
            par_coin_metas.setdefault(str(meta.get("coin") or ""), []).append(meta)
        for coin, metas in par_coin_metas.items():
            u = _sonder_univers(metas, {coin: list(books_by_coin.get(coin, []))}, debut, fin, horizons_ms)
            ventilation[coin] = {
                "signaux": u["signaux"], "executables": u["executables"],
                "non_executables": max(0, u["signaux"] - u["executables"]),
                "refus_par_motif": u["refus_par_motif"],
            }
    executables = global_["executables"]
    refus = global_["refus_par_motif"]
    return {
        "executable": executables > 0,
        "raison": None if executables > 0 else RAISON,
        "train_start_ms": debut, "train_end_ms": fin,
        "signaux_train": global_["signaux"],
        "signaux_executables": executables,
        "trades_executables_par_horizon_ms": global_["trades_executables_par_horizon_ms"],
        "meilleur_horizon_ms": global_["meilleur_horizon_ms"],
        "refus_par_motif": refus,
        "explications": {motif: EXPLICATIONS.get(motif, motif) for motif in refus},
        "par_coin": ventilation,
        "coins_a_collecter": coins_a_collecter({"par_coin": ventilation}),
        "regles": "CANONIQUES_CARNETS_CAUSAUX_IDENTITE_DE_CONNEXION_PROUVEE_SANS_FILTRE_DE_STRATEGIE",
    }


def coins_a_collecter(sonde: Mapping[str, Any], *, maximum: int = 20) -> list[dict[str, Any]]:
    """Coins classés par nombre de signaux NON exécutables (la file d'attente de collecte, décroissante)."""
    ventilation = sonde.get("par_coin") if isinstance(sonde.get("par_coin"), Mapping) else {}
    lignes = [
        {
            "coin": coin,
            "signaux": int(stats.get("signaux") or 0),
            "non_executables": int(stats.get("non_executables") or 0),
            "motif_principal": next(iter((stats.get("refus_par_motif") or {}).keys()), None),
        }
        for coin, stats in ventilation.items()
        if isinstance(stats, Mapping) and int(stats.get("non_executables") or 0) > 0
    ]
    lignes.sort(key=lambda item: (-item["non_executables"], item["coin"]))
    return lignes[: max(0, int(maximum))]


def resume_lisible(sonde: Mapping[str, Any], *, maximum: int = 4) -> str:
    """Une phrase pour le journal et le rapport : combien de signaux, et pourquoi aucun n'est exécutable."""
    refus = sonde.get("refus_par_motif") or {}
    explications = sonde.get("explications") or {}
    details = " ; ".join(
        f"{nombre} × {explications.get(motif, motif)}" for motif, nombre in list(refus.items())[:maximum]
    )
    coins = coins_a_collecter(sonde, maximum=6)
    cible = (
        " · collecter en priorité : "
        + ", ".join(f"{c['coin']} ({c['non_executables']})" for c in coins)
        if coins else ""
    )
    return (
        f"aucun trade exécutable sur {sonde.get('signaux_train', 0)} signaux de la période d'entraînement"
        + (f" — {details}" if details else "")
        + cible
    )


__all__ = ["EXPLICATIONS", "RAISON", "coins_a_collecter", "resume_lisible", "sonder_train",
           "SEGMENTS", "RAISON_SEGMENT", "sonder_un_segment", "sonder_les_segments",
           "resume_segments"]


# ----------------------------------------------------------------------------------------------------
# L2 — LA MEME SONDE SUR CHAQUE SEGMENT : ne jamais « valider » sur un segment vide
# ----------------------------------------------------------------------------------------------------
#: Les trois segments de la decoupe (voir `copy_vault_executable` : train / validation / oos + purge).
SEGMENTS = ("train", "validation", "oos")
RAISON_SEGMENT = "SEGMENT_NOT_EXECUTABLE"


def sonder_un_segment(metaorders, books_by_coin, bounds, nom, *, horizons_ms=HORIZONS_MS):
    """Executabilite d'UN segment nomme. Rend ``None`` si ses bornes sont absentes des ``bounds``."""
    cle_debut, cle_fin = f"{nom}_start_ms", f"{nom}_end_ms"
    if bounds.get(cle_debut) is None or bounds.get(cle_fin) is None:
        return None
    debut, fin = int(bounds[cle_debut]), int(bounds[cle_fin])
    u = _sonder_univers(metaorders, books_by_coin, debut, fin, horizons_ms)
    return {
        "segment": nom, "debut_ms": debut, "fin_ms": fin,
        "signaux": u["signaux"], "executables": u["executables"],
        "non_executables": max(0, u["signaux"] - u["executables"]),
        "meilleur_horizon_ms": u["meilleur_horizon_ms"],
        "refus_par_motif": u["refus_par_motif"],
        "explications": {m: EXPLICATIONS.get(m, m) for m in u["refus_par_motif"]},
        "mesurable": u["executables"] > 0,
    }


def sonder_les_segments(metaorders, books_by_coin, bounds, *, horizons_ms=HORIZONS_MS,
                        segments=SEGMENTS):
    """Executabilite de CHAQUE segment, pas seulement TRAIN.

    POURQUOI (L2). La sonde d'origine ne regardait que TRAIN : elle empechait de CHERCHER a vide,
    mais pas de VALIDER a vide. Or un segment ou aucun trade n'est executable produit zero trade,
    donc zero perte, donc un resultat qui FRANCHIT les portes sans avoir rien mesure : un faux
    PROVEN. C'est le mensonge exact que ce projet combat — « non mesure » n'est pas « valide ».

    Rend, par segment, s'il est mesurable, et la liste de ceux qui ne le sont pas. L'appelant doit
    REFUSER toute promotion tant que `tous_mesurables` est faux.
    """
    par_segment, absents = {}, []
    for nom in segments:
        resultat = sonder_un_segment(metaorders, books_by_coin, bounds, nom, horizons_ms=horizons_ms)
        if resultat is None:
            absents.append(nom)
        else:
            par_segment[nom] = resultat
    mesurables = [n for n, r in par_segment.items() if r["mesurable"]]
    non_mesurables = [n for n, r in par_segment.items() if not r["mesurable"]]
    tous = bool(par_segment) and not non_mesurables
    return {
        "par_segment": par_segment,
        "segments_absents_des_bornes": absents,
        "segments_mesurables": mesurables,
        "segments_non_mesurables": non_mesurables,
        "tous_mesurables": tous,
        "raison": None if tous else RAISON_SEGMENT,
        "lecture": resume_segments(par_segment, non_mesurables),
    }


def resume_segments(par_segment, non_mesurables):
    """Une phrase lisible : ce qui est mesurable, et ce qui ne l'est surtout pas."""
    if not par_segment:
        return "aucun segment borne : rien n'a pu etre sonde"
    details = ", ".join(
        f"{nom} {r['executables']}/{r['signaux']}" for nom, r in sorted(par_segment.items()))
    if not non_mesurables:
        return f"tous les segments sont mesurables ({details})"
    return (f"segment(s) NON mesurable(s) : {', '.join(sorted(non_mesurables))} — aucun trade "
            f"executable, donc aucune validation possible dessus ({details})")
