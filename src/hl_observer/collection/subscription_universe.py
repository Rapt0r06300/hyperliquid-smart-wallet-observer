"""P3.4 (§5.4) — Subscription Universe Manager : compte les VRAIES subscriptions Hyperliquid, sous quotas.

On ne budgète pas « des coins » mais des SUBSCRIPTIONS réelles. Par coin : BBO + L2 (l2Book) + trades.
Par user (subscriptions user-specific) : userFills + userTwapSliceFills. Plus 1 subscription globale
(allMids). Quotas Hyperliquid réellement appliqués :

  * ≤ 1000 subscriptions au total ;
  * ≤ 10 users uniques (user-specific) — répartis en **8 CORE + 2 CHALLENGERS** ;
  * ≤ 10 connexions WS (chaque connexion porte au plus `subs_par_connexion` subscriptions).

Priorité des coins : positions ouvertes > TWAP/metaorders > candidats anticipation > cross-venue liquides.
**Aucune troncature silencieuse** : ce qui dépasse le budget est retourné nommément. `diff_souscriptions`
fournit le subscribe/unsubscribe dynamique (à brancher sur le collecteur vivant). Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

SCHEMA_VERSION = "hypersmart.subscription_universe.v2"

PRIORITE_COINS = ("positions_ouvertes", "twap_actifs", "candidats_anticipation", "cross_venue_liquides")

#: Streams réels par coin / par user (chacun = 1 subscription Hyperliquid).
STREAMS_COIN_DEFAUT = ("bbo", "l2Book", "trades")
STREAMS_USER_DEFAUT = ("userFills", "userTwapSliceFills")

QUOTA_SUBSCRIPTIONS = 1000
QUOTA_USERS = 10
QUOTA_CONNEXIONS = 10
SUBS_PAR_CONNEXION = 100          # 10 connexions × 100 = 1000 subscriptions
SUBS_GLOBALES = 1                 # allMids


def _coins(items: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for it in items or ():
        c = it.get("coin") if isinstance(it, dict) else it
        if c not in (None, ""):
            out.append(str(c).upper())
    return out


def _prioriser_uniques(sources: list[tuple[str, list[str]]]) -> list[tuple[str, str]]:
    vus: set[str] = set()
    ordonne: list[tuple[str, str]] = []
    for tag, items in sources:
        for it in items:
            if it not in vus:
                vus.add(it)
                ordonne.append((it, tag))
    return ordonne


def selectionner_users(core_wallets: Iterable[Any], challengers: Iterable[Any], *,
                       core_slots: int = 8, challenger_slots: int = 2,
                       quota_user_slots: int = QUOTA_USERS) -> dict[str, Any]:
    """8 CORE + 2 CHALLENGERS, dédupliqués, priorité CORE ; le surplus est ABANDONNÉ nommément."""
    core = list(dict.fromkeys(str(w) for w in (core_wallets or ()) if w not in (None, "")))
    chall = list(dict.fromkeys(str(w) for w in (challengers or ()) if w not in (None, "")))
    chall = [w for w in chall if w not in set(core)]

    core_ret = core[:core_slots]
    core_drop = core[core_slots:]
    reste = max(0, quota_user_slots - len(core_ret))
    chall_ret = chall[:min(challenger_slots, reste)]
    chall_drop = chall[min(challenger_slots, reste):]
    return {"core": core_ret, "challengers": chall_ret,
            "abandons": {"core": core_drop, "challengers": chall_drop},
            "slots_utilises": len(core_ret) + len(chall_ret)}


def construire_univers(
    *,
    positions_ouvertes: Iterable[Any] = (),
    twap_actifs: Iterable[Any] = (),
    candidats_anticipation: Iterable[Any] = (),
    cross_venue_liquides: Iterable[Any] = (),
    core_wallets: Iterable[Any] = (),
    challengers: Iterable[Any] = (),
    streams_coin: Iterable[str] = STREAMS_COIN_DEFAUT,
    streams_user: Iterable[str] = STREAMS_USER_DEFAUT,
    quota_subscriptions: int = QUOTA_SUBSCRIPTIONS,
    quota_users: int = QUOTA_USERS,
    quota_connexions: int = QUOTA_CONNEXIONS,
    subs_par_connexion: int = SUBS_PAR_CONNEXION,
    core_slots: int = 8,
    challenger_slots: int = 2,
) -> dict[str, Any]:
    """Univers de souscription priorisé et borné aux VRAIES subscriptions. Renvoie l'accounting complet."""
    streams_coin = tuple(streams_coin)
    streams_user = tuple(streams_user)
    subs_par_coin = max(1, len(streams_coin))
    subs_par_user = len(streams_user)

    users = selectionner_users(core_wallets, challengers, core_slots=core_slots,
                               challenger_slots=challenger_slots, quota_user_slots=quota_users)
    n_users = users["slots_utilises"]
    subs_user = n_users * subs_par_user

    # Budget coin = subscriptions restantes après users + globales.
    budget_coin_subs = max(0, int(quota_subscriptions) - subs_user - SUBS_GLOBALES)
    max_coins = budget_coin_subs // subs_par_coin

    coins_pri = _prioriser_uniques([
        ("positions_ouvertes", _coins(positions_ouvertes)),
        ("twap_actifs", _coins(twap_actifs)),
        ("candidats_anticipation", _coins(candidats_anticipation)),
        ("cross_venue_liquides", _coins(cross_venue_liquides)),
    ])
    retenus = coins_pri[:max_coins]
    abandonnes = coins_pri[max_coins:]

    n_coin_subs = len(retenus) * subs_par_coin
    total_subs = n_coin_subs + subs_user + SUBS_GLOBALES
    connexions = math.ceil(total_subs / max(1, int(subs_par_connexion))) if total_subs else 0

    return {
        "schema_version": SCHEMA_VERSION,
        "coins": [{"coin": c, "priorite": tag, "streams": list(streams_coin)} for c, tag in retenus],
        "users_core": users["core"],
        "users_challengers": users["challengers"],
        "streams_user": list(streams_user),
        "abandons": {
            "coins": [{"coin": c, "priorite": tag} for c, tag in abandonnes],
            "users": users["abandons"],
        },
        "accounting": {
            "subscriptions_totales": total_subs,
            "subscriptions_coins": n_coin_subs,
            "subscriptions_users": subs_user,
            "subscriptions_globales": SUBS_GLOBALES,
            "quota_subscriptions": int(quota_subscriptions),
            "subscriptions_ok": total_subs <= int(quota_subscriptions),
            "users_uniques": n_users,
            "quota_users": int(quota_users),
            "users_ok": n_users <= int(quota_users),
            "connexions_estimees": connexions,
            "quota_connexions": int(quota_connexions),
            "connexions_ok": connexions <= int(quota_connexions),
            "subs_par_coin": subs_par_coin,
            "subs_par_user": subs_par_user,
        },
        "real_execution": False,
    }


def _cle_sub(coin_ou_user: str, stream: str) -> str:
    return f"{stream}:{coin_ou_user}"


def _subscriptions_set(univers: dict) -> set[str]:
    subs: set[str] = {"allMids:*"}
    for c in univers.get("coins", []):
        for s in c.get("streams", []):
            subs.add(_cle_sub(c["coin"], s))
    for u in [*univers.get("users_core", []), *univers.get("users_challengers", [])]:
        for s in univers.get("streams_user", []):
            subs.add(_cle_sub(u, s))
    return subs


def diff_souscriptions(ancien: dict | None, nouveau: dict) -> dict[str, Any]:
    """Subscribe/unsubscribe DYNAMIQUE entre deux univers : ce qu'il faut ajouter et retirer au collecteur."""
    a = _subscriptions_set(ancien) if ancien else set()
    n = _subscriptions_set(nouveau)
    return {
        "schema_version": SCHEMA_VERSION,
        "a_souscrire": sorted(n - a),
        "a_desouscrire": sorted(a - n),
        "inchangees": len(a & n),
        "real_execution": False,
    }


__all__ = [
    "SCHEMA_VERSION", "PRIORITE_COINS", "STREAMS_COIN_DEFAUT", "STREAMS_USER_DEFAUT",
    "QUOTA_SUBSCRIPTIONS", "QUOTA_USERS", "QUOTA_CONNEXIONS",
    "selectionner_users", "construire_univers", "diff_souscriptions",
]
