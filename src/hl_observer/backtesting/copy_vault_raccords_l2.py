"""Raccorder les connexions L2 d'un coin quand le trou entre elles est COURT.

LE CONSTAT (mesure du 22/11/2026). Le replay refuse un épisode dont la référence, l'entrée et la
sortie ne portent pas la même `connection_id` : il veut la preuve que le marché a été observé sans
interruption. Mais une connexion L2 porte beaucoup de coins et se renouvelle souvent ; plusieurs
lanes observent le même coin en même temps. Les carnets d'un coin sont donc ÉPARPILLÉS sur des
dizaines de connexions, et `une_seule_connexion_par_coin` en écartait 83 % :

    512 654 carnets / 265 coins  ->  87 110 gardés (17,0 %)
    trou médian entre deux connexions : 2,84 s | p90 10,3 s | p99 37,6 s
    raccords de 30 s ou moins : 201 977 | raccords plus longs : 2 197 (1,1 %)

Ce que la règle protège n'est pas l'identité d'un socket, c'est l'ABSENCE DE TROU. Deux carnets du
même coin séparés de 3 secondes prouvent la même continuité, qu'ils viennent d'un socket ou de deux.

LA RÈGLE. Par coin, les carnets sont rangés dans le temps, toutes connexions confondues. Une CHAÎNE
se poursuit tant que deux carnets consécutifs sont séparés d'au plus `trou_max_ms` ; au-delà, elle
se casse et une nouvelle commence. Chaque carnet reçoit pour `connection_id` l'identité de sa
chaîne ; l'identité observée est conservée dans `connection_id_observee`. Un épisode qui tient dans
une chaîne n'a donc traversé aucun trou plus long que le seuil.

LE SEUIL N'EST PAS INVENTÉ : 30 s, c'est `MAX_TARGET_LAG_MS`, la fraîcheur que le labo s'impose déjà
autour de chaque événement copié. Un raccord plus court ne peut rien cacher que le labo aurait
utilisé. Les trous plus longs restent des ruptures : un épisode à cheval dessus est toujours refusé.

L'AUDIT COMPTE TOUT : raccords franchis, raccords refusés, distribution des trous. Sans ce compte on
ne saurait pas si un verdict repose sur 17 % ou sur 93 % du ruban.

OPTIONNEL ET DÉSACTIVÉ PAR DÉFAUT : cette règle touche le cœur causal du replay. Elle ne s'applique
que si l'opérateur la demande (`HL_LABO_RACCORDER_L2=1`).
"""
from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.copy_vault_protocol import MAX_TARGET_LAG_MS

VARIABLE = "HL_LABO_RACCORDER_L2"


def raccord_demande() -> bool:
    return os.environ.get(VARIABLE, "0").strip() == "1"


def raccorder_les_connexions(
    carnets: Mapping[str, Sequence[Mapping[str, Any]]], *, trou_max_ms: int = MAX_TARGET_LAG_MS,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Carnets relabellisés par chaîne de continuité, et l'audit des raccords. PURE.

    Un carnet sans `ts_ms` lisible est écarté ET compté : on ne lui invente pas une place.
    """
    seuil = int(trou_max_ms)
    sortie: dict[str, list[dict[str, Any]]] = {}
    franchis = refuses = sans_horodatage = chaines = 0
    trous_franchis: list[int] = []
    plus_long_refuse = 0
    for coin, liste in carnets.items():
        dates: list[tuple[int, dict[str, Any]]] = []
        for brut in liste:
            try:
                dates.append((int(brut["ts_ms"]), dict(brut)))
            except (KeyError, TypeError, ValueError):
                sans_horodatage += 1
        dates.sort(key=lambda couple: couple[0])
        rang = -1
        precedent: tuple[int, Any] | None = None
        gardes: list[dict[str, Any]] = []
        for ts, carnet in dates:
            observee = carnet.get("connection_id")
            if precedent is None:
                rang += 1
            else:
                trou = ts - precedent[0]
                if trou > seuil:
                    rang += 1                       # rupture : une nouvelle chaîne commence
                    if observee != precedent[1]:
                        refuses += 1
                        plus_long_refuse = max(plus_long_refuse, trou)
                elif observee != precedent[1]:
                    franchis += 1                   # changement d'observateur, trou court : franchi
                    trous_franchis.append(trou)
            carnet["connection_id_observee"] = observee
            carnet["connection_id"] = f"chaine:{coin}:{rang}"
            gardes.append(carnet)
            precedent = (ts, observee)
        chaines += rang + 1
        sortie[str(coin)] = gardes
    trous_franchis.sort()
    quantile = (lambda p: trous_franchis[min(len(trous_franchis) - 1, int(p * len(trous_franchis)))]
                if trous_franchis else None)
    audit = {
        "regle": "RACCORD_L2_TROU_COURT", "trou_max_ms": seuil, "coins": len(sortie), "chaines": chaines,
        "carnets_gardes": sum(len(v) for v in sortie.values()), "carnets_sans_horodatage": sans_horodatage,
        "raccords_franchis": franchis, "raccords_refuses": refuses,
        "trou_franchi_median_ms": quantile(0.5), "trou_franchi_p90_ms": quantile(0.9),
        "trou_franchi_max_ms": trous_franchis[-1] if trous_franchis else None,
        "plus_long_trou_refuse_ms": plus_long_refuse or None,
    }
    return sortie, audit


__all__ = ["VARIABLE", "raccord_demande", "raccorder_les_connexions"]
