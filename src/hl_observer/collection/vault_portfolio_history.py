"""Historique de portefeuille des vaults Hyperliquid (``vaultDetails.portfolio``).

POURQUOI. Le collecteur de vaults interroge ``vaultDetails`` à chaque passe pour chaque vault
suivi. La réponse contient, par fenêtre (jour, semaine, mois, vie entière), la courbe de valeur
du compte, la courbe de PnL cumulé et le volume traité. Jusqu'ici, tout était jeté sauf un
drawdown et le dernier PnL. Or c'est la seule source qui donne des MOIS d'historique par vault
sans dépendre de la continuité de nos propres collectes : exactement ce qui manque pour tester
si la compétence d'un leader persiste (condition nécessaire à toute copie lente).

CE MODULE EST PUR (aucune E/S, aucun réseau). Il :

* normalise chaque fenêtre en points ``[ts_ms, valeur_compte, pnl_cumulé]`` strictement croissants ;
* n'émet à chaque passe que les points NOUVEAUX (au-delà du dernier point déjà émis pour ce
  vault et cette fenêtre, avec un espacement minimal par fenêtre) : pas de doublon entre passes ;
* date chaque ligne par NOTRE instant d'observation (``observed_at_ms``).

RIGUEUR. Ces courbes sont un historique relu après coup : elles décrivent le passé du vault tel
que l'API le publie à l'instant d'observation. Elles servent à mesurer une persistance, jamais à
dater un signal de trading en direct. Une valeur absente reste ``None`` (inconnue), jamais 0.
Lecture seule, PAPER : aucun ordre, aucune clé, aucune signature.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

SCHEMA_PORTFOLIO_HISTORY = "hypersmart.copy_vault_portfolio_history.v2"
SOURCE_PORTFOLIO_HISTORY = "VAULT_DETAILS_PORTFOLIO"
#: Base du PnL porté par chaque point. Mesuré sur une réponse réelle le 2026-11-11 : le PnL des
#: fenêtres jour / semaine / mois repart de 0 au DÉBUT de la fenêtre ; seule « vie entière » est
#: cumulée depuis la création. Toutes les fenêtres se terminent au même instant (l'observation) :
#: chaque fenêtre est donc recalée exactement sur la base cumulée. Sans ce recalage, fusionner les
#: fenêtres mélangeait des bases différentes et fabriquait des rendements faux.
PNL_BASE_CUMUL = "CUMUL_DEPUIS_CREATION"
FENETRE_CUMULEE = "allTime"

#: Fenêtres conservées et espacement minimal entre deux points émis (ms). L'espacement ne fait
#: qu'écarter des points plus denses que nécessaire ; il ne déplace ni n'interpole aucun point.
ESPACEMENT_MIN_MS: dict[str, int] = {
    "day": 15 * 60_000,
    "week": 60 * 60_000,
    "month": 4 * 3_600_000,
    "allTime": 12 * 3_600_000,
}
FENETRES: tuple[str, ...] = tuple(ESPACEMENT_MIN_MS)


def _fini(value: Any) -> float | None:
    """Nombre fini ou ``None`` (un booléen n'est pas un nombre)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _ts(value: Any) -> int | None:
    """Horodatage en millisecondes strictement positif, sinon ``None``."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    if not isinstance(value, int) or value <= 0:
        return None
    return value


def _serie(raw: Any) -> dict[int, float]:
    """``[[ts, valeur], ...]`` -> ``{ts: valeur}`` ; toute paire illisible est ignorée."""
    serie: dict[int, float] = {}
    if not isinstance(raw, list):
        return serie
    for pair in raw:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        ts, value = _ts(pair[0]), _fini(pair[1])
        if ts is not None and value is not None:
            serie[ts] = value
    return serie


def extraire_fenetres(payload: Any) -> dict[str, dict[str, Any]]:
    """``vaultDetails`` -> ``{fenêtre: {"points": [[ts, valeur, pnl_cumulé], ...], "vlm_usd", ...}}``.

    Les deux courbes sont alignées par horodatage. Un horodatage présent dans une seule courbe
    garde l'autre grandeur à ``None`` : on ne recopie jamais la valeur voisine. Le PnL de chaque
    fenêtre est ramené à la base cumulée (``pnl_base``) ; si le recalage est impossible (pas de
    courbe « vie entière », ou derniers instants différents), le PnL de la fenêtre reste inconnu.
    """
    fenetres: dict[str, dict[str, Any]] = {}
    if not isinstance(payload, Mapping):
        return fenetres
    brutes: dict[str, tuple[dict[int, float], dict[int, float], float | None]] = {}
    for entree in payload.get("portfolio") or ():
        if not isinstance(entree, (list, tuple)) or len(entree) < 2:
            continue
        nom, bloc = entree[0], entree[1]
        if nom not in ESPACEMENT_MIN_MS or not isinstance(bloc, Mapping):
            continue
        brutes[str(nom)] = (_serie(bloc.get("accountValueHistory")), _serie(bloc.get("pnlHistory")),
                            _fini(bloc.get("vlm")))
    cumul = brutes.get(FENETRE_CUMULEE, ({}, {}, None))[1]
    fin_cumul = max(cumul) if cumul else None
    for nom, (valeurs, pnls, volume) in brutes.items():
        decalage: float | None = 0.0 if nom == FENETRE_CUMULEE else None
        if nom != FENETRE_CUMULEE and pnls and fin_cumul is not None and max(pnls) == fin_cumul:
            decalage = cumul[fin_cumul] - pnls[fin_cumul]
        if decalage is None:
            pnls = {}                                   # base inconnue : jamais mélangée au cumul
        points = [[ts, valeurs.get(ts), None if ts not in pnls else pnls[ts] + decalage]
                  for ts in sorted(set(valeurs) | set(pnls))]
        if points:
            fenetres[nom] = {"points": points, "vlm_usd": volume,
                             "pnl_base": PNL_BASE_CUMUL if decalage is not None else None,
                             "pnl_decalage_usd": decalage}
    return fenetres


def nouveaux_points(points: list[list[Any]], *, haute_eau_ms: int, espacement_ms: int,
                    observed_at_ms: int) -> list[list[Any]]:
    """Points postérieurs au dernier point émis, espacés d'au moins ``espacement_ms``.

    Un point daté APRÈS notre observation est impossible : il est écarté (fail-closed).
    """
    retenus: list[list[Any]] = []
    dernier = int(haute_eau_ms)
    for point in points:
        ts = int(point[0])
        if ts > int(observed_at_ms):
            continue
        if dernier > 0 and ts < dernier + int(espacement_ms):
            continue
        if dernier <= 0 or ts > dernier:
            retenus.append(point)
            dernier = ts
    return retenus


def construire_lignes(
    vault: str,
    payload: Any,
    *,
    observed_at_ms: int,
    etat_vault: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Lignes à écrire pour un vault + sa haute eau mise à jour (par fenêtre).

    Première observation d'un vault : toute la courbe publiée est émise (rattrapage). Passes
    suivantes : uniquement les points nouveaux. ``etat_vault`` n'est jamais modifié en place.
    """
    adresse = str(vault or "").strip().lower()
    observation = _ts(observed_at_ms)
    haute_eau: dict[str, int] = {}
    for nom, valeur in (etat_vault or {}).items():
        ts = _ts(valeur)
        if nom in ESPACEMENT_MIN_MS and ts is not None:
            haute_eau[str(nom)] = ts
    if not adresse or observation is None:
        return [], haute_eau
    details = payload if isinstance(payload, Mapping) else {}
    leader = details.get("leader")
    suiveurs = details.get("followers")
    contexte = {
        # état public du vault à l'observation : sert à mesurer le biais de survie (vault fermé)
        # et la part du rendement qui revient au leader (commission), sans rien supposer.
        "is_closed": details.get("isClosed") if isinstance(details.get("isClosed"), bool) else None,
        "allow_deposits": (details.get("allowDeposits")
                           if isinstance(details.get("allowDeposits"), bool) else None),
        "leader_commission": _fini(details.get("leaderCommission")),
        "apr_affiche": _fini(details.get("apr")),
        "followers_listed": len(suiveurs) if isinstance(suiveurs, list) else None,
    }
    lignes: list[dict[str, Any]] = []
    for nom, bloc in extraire_fenetres(payload).items():
        retenus = nouveaux_points(
            bloc["points"], haute_eau_ms=haute_eau.get(nom, 0),
            espacement_ms=ESPACEMENT_MIN_MS[nom], observed_at_ms=observation,
        )
        if not retenus:
            continue
        haute_eau[nom] = int(retenus[-1][0])
        lignes.append({
            "schema_version": SCHEMA_PORTFOLIO_HISTORY,
            "vault": adresse,
            "fenetre": nom,
            "observed_at_ms": observation,
            "first_ts_ms": int(retenus[0][0]),
            "ts_ms": int(retenus[-1][0]),
            "n_points": len(retenus),
            "points": retenus,
            "vlm_fenetre_usd": bloc["vlm_usd"],
            "pnl_base": bloc["pnl_base"],
            "pnl_decalage_usd": bloc["pnl_decalage_usd"],
            "leader": str(leader).lower() if isinstance(leader, str) and leader else None,
            **contexte,
            "source": SOURCE_PORTFOLIO_HISTORY,
            "observation_mode": "HISTORIQUE_RELU_A_L_OBSERVATION",
            "causal_forward_eligible": False,
            "read_only": True,
            "real_execution": False,
        })
    return lignes, haute_eau


def fusionner_points(lignes: list[Mapping[str, Any]]) -> dict[str, list[tuple[int, float | None, float | None]]]:
    """Reconstitue, par vault, UNE courbe ``(ts, valeur, pnl)`` à partir de toutes les fenêtres.

    Les fenêtres se recouvrent (la vie entière est grossière, le jour est fin). À horodatage
    égal, on garde la grandeur connue ; la courbe finale est triée et sans doublon. Aucune
    interpolation : la résolution reste celle des points réellement publiés.
    """
    par_vault: dict[str, dict[int, list[float | None]]] = {}
    for ligne in lignes:
        vault = str(ligne.get("vault") or "").strip().lower()
        points = ligne.get("points")
        if not vault or not isinstance(points, list):
            continue
        # Un PnL n'est fusionné que s'il est exprimé dans la base cumulée : la fenêtre « vie
        # entière » l'est par nature ; les autres seulement si la ligne le déclare (schéma v2).
        pnl_fiable = ligne.get("fenetre") == FENETRE_CUMULEE or ligne.get("pnl_base") == PNL_BASE_CUMUL
        courbe = par_vault.setdefault(vault, {})
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) < 3:
                continue
            ts = _ts(point[0])
            if ts is None:
                continue
            valeur, pnl = _fini(point[1]), (_fini(point[2]) if pnl_fiable else None)
            connu = courbe.setdefault(ts, [None, None])
            if valeur is not None:
                connu[0] = valeur
            if pnl is not None:
                connu[1] = pnl
    return {
        vault: [(ts, valeurs[0], valeurs[1]) for ts, valeurs in sorted(courbe.items())]
        for vault, courbe in par_vault.items()
    }


__all__ = [
    "ESPACEMENT_MIN_MS", "FENETRES", "FENETRE_CUMULEE", "PNL_BASE_CUMUL", "SCHEMA_PORTFOLIO_HISTORY",
    "SOURCE_PORTFOLIO_HISTORY",
    "construire_lignes", "extraire_fenetres", "fusionner_points", "nouveaux_points",
]
