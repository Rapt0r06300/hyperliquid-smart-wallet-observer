"""CHANTIER LATENCE — mesurer sans biais de cohorte l'effet du délai de copie.

L'étude fait varier le délai de copie en passant par le vrai moteur d'exécution. Elle distingue la
couverture de chaque délai de l'effet apparié sur les mêmes signaux, et évite ainsi de conclure à un
avantage de vitesse lorsqu'un résultat vient seulement de cohortes différentes.

CE QUE FAIT L'ÉTUDE. Elle rejoue EXACTEMENT les mêmes signaux avec le vrai moteur d'exécution
(``execute_metaorder`` : carnets causaux, identité de connexion, frais canoniques, spread observé),
en ne faisant varier QUE le délai de copie (5 s, 15 s, 30 s, 60 s, 120 s). La comparaison de vitesse
est appariée aux mêmes métaordres exécutables aux deux délais extrêmes ; la couverture est affichée
séparément pour éviter de confondre changement de cohorte et effet de latence. Le balayage reste
exploratoire, soumis au biais de sélection et ne constitue jamais une preuve OOS.

HONNÊTE. Aucune invention : le moteur refuse tout signal sans carnet causal de référence/entrée/sortie
et sans identité de connexion. Un délai plus court est plus EXIGEANT en données (il faut un carnet plus
tôt après le fill) : l'étude rapporte, par délai, combien de signaux restent exécutables.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.copy_vault_book_index import liste_des_carnets
from hl_observer.backtesting.copy_vault_executable import execute_metaorder
from hl_observer.backtesting.copy_vault_protocol import NOTIONAL_USD

#: Délais de copie balayés (ms). 5 s est le plus court réaliste pour une observation WebSocket.
DELAIS_MS: tuple[int, ...] = (5_000, 15_000, 30_000, 60_000, 120_000)
#: Horizon de détention par défaut pour la mesure (5 minutes : assez pour voir la dérive, pas trop de funding).
HORIZON_DEFAUT_MS = 300_000


def _rejouer_a_un_delai(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *,
    horizon_ms: int,
    copy_delay_ms: int,
) -> dict[str, Any]:
    """Net agrégé, couverture, refus et résultat par candidat pour un délai."""
    net_total = 0.0
    executes = 0
    refus: dict[str, int] = {}
    net_par_candidat: dict[int, float] = {}
    for candidat_id, meta in enumerate(metaorders):
        trade, raison = execute_metaorder(
            meta, liste_des_carnets(books_by_coin.get(str(meta.get("coin")), [])),
            horizon_ms=int(horizon_ms), copy_delay_ms=int(copy_delay_ms), require_causal_books=True,
        )
        if trade is None:
            refus[raison] = refus.get(raison, 0) + 1
            continue
        net = trade.get("net_pnl_usd")
        if isinstance(net, bool) or not isinstance(net, (int, float)):
            refus["NET_NON_CHIFFRE"] = refus.get("NET_NON_CHIFFRE", 0) + 1
            continue
        try:
            net = float(net)
        except (OverflowError, TypeError, ValueError):
            refus["NET_NON_FINI"] = refus.get("NET_NON_FINI", 0) + 1
            continue
        if not math.isfinite(net):
            refus["NET_NON_FINI"] = refus.get("NET_NON_FINI", 0) + 1
            continue
        net_par_candidat[candidat_id] = net
        net_total += net
        executes += 1
    net_bps_moyen = (net_total / executes / NOTIONAL_USD * 1e4) if executes else None
    candidats = len(metaorders)
    return {
        "copy_delay_ms": int(copy_delay_ms),
        "signaux_candidats": candidats,
        "signaux_executes": executes,
        "signaux_refuses": candidats - executes,
        "couverture_execution_pct": None if not candidats else round(executes / candidats * 100.0, 4),
        "net_total_usd": None if not executes else round(net_total, 6),
        "net_bps_par_decision": None if net_bps_moyen is None else round(net_bps_moyen, 4),
        "refus_par_motif": dict(sorted(refus.items(), key=lambda kv: (-kv[1], kv[0]))),
        "_net_par_candidat_usd": net_par_candidat,
    }


def etude_latence(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *,
    delais_ms: Sequence[int] = DELAIS_MS,
    horizon_ms: int = HORIZON_DEFAUT_MS,
) -> dict[str, Any]:
    """Pour chaque délai de copie : net moyen par décision et nombre de signaux exécutables.

    Le verdict reste exploratoire : un net positif, même à délai court, n'est PAS une preuve
    économique (il faut une politique gelée, validation chronologique, OOS et forward).
    """
    if type(horizon_ms) is not int or horizon_ms <= 0:
        raise ValueError("horizon_ms doit être un entier strictement positif")
    delais = tuple(delais_ms)
    if not delais:
        raise ValueError("delais_ms ne peut pas être vide")
    if any(type(delai) is not int or delai < 0 for delai in delais):
        raise ValueError("chaque délai doit être un entier positif ou nul")
    if len(set(delais)) != len(delais):
        raise ValueError("delais_ms ne peut pas contenir de doublons")

    mesures = [
        _rejouer_a_un_delai(metaorders, books_by_coin, horizon_ms=horizon_ms, copy_delay_ms=delai)
        for delai in delais
    ]
    mesurables = [d for d in mesures if d["net_bps_par_decision"] is not None]
    meilleur = max(mesurables, key=lambda d: d["net_bps_par_decision"], default=None)
    # Comparer les extrêmes demandés, sans remplacer un délai non mesurable par un délai voisin.
    plus_court = next(d for d in mesures if d["copy_delay_ms"] == min(delais))
    plus_long = next(d for d in mesures if d["copy_delay_ms"] == max(delais))
    rapides = plus_court["_net_par_candidat_usd"]
    lents = plus_long["_net_par_candidat_usd"]
    candidats_apparies = sorted(rapides.keys() & lents.keys()) if plus_court is not plus_long else []
    gain_vitesse_bps = None
    if candidats_apparies:
        delta_usd_moyen = sum(rapides[i] - lents[i] for i in candidats_apparies) / len(candidats_apparies)
        gain_vitesse_bps = delta_usd_moyen / NOTIONAL_USD * 1e4
    net_rapide = plus_court["net_bps_par_decision"]
    positif = None if net_rapide is None else net_rapide > 0
    # Ne pas exposer les clés internes de rapprochement dans le rapport JSON.
    par_delai = [{k: v for k, v in d.items() if not k.startswith("_")} for d in mesures]

    if positif is None:
        lecture = (
            "pas assez de signaux exécutables : le délai court n'est pas mesurable"
            if not mesurables
            else "délai court non mesurable : aucun signal exécutable à ce délai"
        )
    elif positif:
        lecture = "NET POSITIF AU DÉLAI COURT (résultat exploratoire, validation OOS requise)"
    elif gain_vitesse_bps is not None and gain_vitesse_bps > 0:
        lecture = "copier plus vite améliore la cohorte appariée, mais son net moyen reste négatif"
    elif gain_vitesse_bps is not None and gain_vitesse_bps < 0:
        lecture = "la cohorte appariée ne confirme pas un avantage à copier plus vite"
    elif not mesurables:
        lecture = "pas assez de signaux exécutables : vérifier la disponibilité des carnets causaux"
    else:
        lecture = "effet du délai non mesurable : aucun signal commun exécutable aux deux extrêmes"

    return {
        "hypothese": "copy_vault_latency_sensitivity",
        "horizon_ms": int(horizon_ms),
        "par_delai": par_delai,
        "scope_resultat": "EXPLORATOIRE_NON_OOS",
        "validation_requise": "WALK_FORWARD_OOS",
        "delais_comparaison": {"rapide_ms": min(delais), "lent_ms": max(delais)},
        "signaux_apparies_delai_extremes": len(candidats_apparies),
        "meilleur_delai_ms": None if meilleur is None else meilleur["copy_delay_ms"],
        "meilleur_net_bps_par_decision": None if meilleur is None else meilleur["net_bps_par_decision"],
        "net_devient_positif_a_faible_delai": positif,
        "gain_bps_en_copiant_plus_vite": None if gain_vitesse_bps is None else round(gain_vitesse_bps, 4),
        "lecture": lecture,
        "paper_read_only": True, "real_execution": False,
    }


__all__ = ["DELAIS_MS", "HORIZON_DEFAUT_MS", "etude_latence"]
