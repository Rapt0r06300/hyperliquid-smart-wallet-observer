"""CHANTIER LATENCE — à quel délai de réaction l'avantage de copie devient-il positif (s'il le devient) ?

POURQUOI. L'étude des ouvertures agressives mesure **−18 bps par décision** à un délai de réaction de
60 s, et une mesure antérieure montre que **7,6 bps de dérive partent AVANT l'observation**. Le délai
entre le fill du leader et notre entrée est donc le suspect n°1 : plus il est long, plus la dérive
exploitable a déjà eu lieu quand on entre, et plus il ne reste que le coût (frais + spread) à payer.

CE QUE FAIT L'ÉTUDE. Elle rejoue EXACTEMENT les mêmes signaux avec le vrai moteur d'exécution
(``execute_metaorder`` : carnets causaux, identité de connexion, frais canoniques, spread observé),
en ne faisant varier QUE le délai de copie (5 s, 15 s, 30 s, 60 s, 120 s). Pour chaque délai elle
agrège le PnL net réel. Lecture directe : si le net devient positif à faible délai, un PnL positif est
atteignable en copiant plus vite ; s'il reste négatif même à 5 s, la dérive ne bat pas le coût et il
faut chercher ailleurs (maker, conditionnement, réplication lente).

HONNÊTE. Aucune invention : le moteur refuse tout signal sans carnet causal de référence/entrée/sortie
et sans identité de connexion. Un délai plus court est plus EXIGEANT en données (il faut un carnet plus
tôt après le fill) : l'étude rapporte, par délai, combien de signaux restent exécutables.
"""
from __future__ import annotations

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
    """Net agrégé et refus par motif pour UN délai de copie, avec le vrai moteur d'exécution."""
    net_total = 0.0
    executes = 0
    refus: dict[str, int] = {}
    for meta in metaorders:
        trade, raison = execute_metaorder(
            meta, liste_des_carnets(books_by_coin.get(str(meta.get("coin")), [])),
            horizon_ms=int(horizon_ms), copy_delay_ms=int(copy_delay_ms), require_causal_books=True,
        )
        if trade is None:
            refus[raison] = refus.get(raison, 0) + 1
            continue
        net = trade.get("net_pnl_usd")
        if not isinstance(net, (int, float)):
            refus["NET_NON_CHIFFRE"] = refus.get("NET_NON_CHIFFRE", 0) + 1
            continue
        net_total += float(net)
        executes += 1
    net_bps_moyen = (net_total / executes / NOTIONAL_USD * 1e4) if executes else None
    return {
        "copy_delay_ms": int(copy_delay_ms),
        "signaux_executes": executes,
        "net_total_usd": round(net_total, 6),
        "net_bps_par_decision": None if net_bps_moyen is None else round(net_bps_moyen, 4),
        "refus_par_motif": dict(sorted(refus.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def etude_latence(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *,
    delais_ms: Sequence[int] = DELAIS_MS,
    horizon_ms: int = HORIZON_DEFAUT_MS,
) -> dict[str, Any]:
    """Pour chaque délai de copie : net moyen par décision et nombre de signaux exécutables.

    Le verdict reste prudent : un net positif en balayage n'est PAS une preuve (il faut
    VALIDATION / OOS / FORWARD). C'est une lecture de direction : le délai est-il le verrou ?
    """
    par_delai = [
        _rejouer_a_un_delai(metaorders, books_by_coin, horizon_ms=horizon_ms, copy_delay_ms=delai)
        for delai in delais_ms
    ]
    mesurables = [d for d in par_delai if d["net_bps_par_decision"] is not None]
    meilleur = max(mesurables, key=lambda d: d["net_bps_par_decision"], default=None)
    positif = meilleur is not None and meilleur["net_bps_par_decision"] > 0
    # le délai le plus court mesurable, pour comparer « vite » vs « lent »
    plus_court = min(mesurables, key=lambda d: d["copy_delay_ms"], default=None)
    plus_long = max(mesurables, key=lambda d: d["copy_delay_ms"], default=None)
    gain_vitesse_bps = (
        plus_court["net_bps_par_decision"] - plus_long["net_bps_par_decision"]
        if plus_court is not None and plus_long is not None and plus_court is not plus_long else None
    )
    return {
        "hypothese": "copy_vault_latency_sensitivity",
        "horizon_ms": int(horizon_ms),
        "par_delai": par_delai,
        "meilleur_delai_ms": None if meilleur is None else meilleur["copy_delay_ms"],
        "meilleur_net_bps_par_decision": None if meilleur is None else meilleur["net_bps_par_decision"],
        "net_devient_positif_a_faible_delai": positif,
        "gain_bps_en_copiant_plus_vite": None if gain_vitesse_bps is None else round(gain_vitesse_bps, 4),
        "lecture": (
            "LE DÉLAI EST LE VERROU : net positif atteint en copiant plus vite" if positif
            else "copier plus vite aide mais ne suffit pas (net encore négatif au plus court délai)"
            if gain_vitesse_bps is not None and gain_vitesse_bps > 0
            else "le délai n'explique pas la perte : chercher côté coût (maker) ou conditionnement"
            if mesurables else "pas assez de signaux exécutables : collecter des carnets plus tôt après les fills"
        ),
        "paper_read_only": True, "real_execution": False,
    }


__all__ = ["DELAIS_MS", "HORIZON_DEFAUT_MS", "etude_latence"]
