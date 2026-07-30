"""P3.4 (§5.4) — Subscription Universe Manager : QUI souscrire, par priorité, sous quotas Hyperliquid.

Le collecteur actuel choisit surtout les majors + les coins de liquidations. On le remplace par une
sélection PRIORISÉE et bornée :

  coins (ordre de priorité) : positions paper ouvertes > TWAP/metaorders actifs > candidats
  anticipation > cross-venue les plus liquides ;
  users (subscriptions user-specific) : 10 slots = **8 CORE + 2 CHALLENGERS**.

Quotas Hyperliquid respectés : au plus `quota_coins` souscriptions coin, au plus `quota_user_slots`
users uniques. **Aucune troncature silencieuse** : ce qui est abandonné faute de quota est retourné
explicitement (nommé), jamais coupé en silence. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

SCHEMA_VERSION = "hypersmart.subscription_universe.v1"

#: Ordre de priorité des sources de coins (le premier gagne en cas de doublon).
PRIORITE_COINS = ("positions_ouvertes", "twap_actifs", "candidats_anticipation", "cross_venue_liquides")


def _coins(items: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for it in items or ():
        c = it.get("coin") if isinstance(it, dict) else it
        if c not in (None, ""):
            out.append(str(c).upper())
    return out


def _prioriser_uniques(sources: list[tuple[str, list[str]]]) -> list[tuple[str, str]]:
    """Aplati les sources en (item, tag) en gardant la PREMIÈRE apparition (priorité la plus haute)."""
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
                       quota_user_slots: int = 10) -> dict[str, Any]:
    """8 CORE + 2 CHALLENGERS, dédupliqués, priorité CORE ; le surplus est ABANDONNÉ nommément."""
    core = list(dict.fromkeys(str(w) for w in (core_wallets or ()) if w not in (None, "")))
    chall = list(dict.fromkeys(str(w) for w in (challengers or ()) if w not in (None, "")))
    chall = [w for w in chall if w not in set(core)]           # un CORE n'est pas aussi challenger

    core_ret = core[:core_slots]
    core_drop = core[core_slots:]
    reste = max(0, quota_user_slots - len(core_ret))
    chall_slots_eff = min(challenger_slots, reste)
    chall_ret = chall[:chall_slots_eff]
    chall_drop = chall[chall_slots_eff:]
    return {
        "core": core_ret, "challengers": chall_ret,
        "abandons": {"core": core_drop, "challengers": chall_drop},
        "slots_utilises": len(core_ret) + len(chall_ret),
    }


def construire_univers(
    *,
    positions_ouvertes: Iterable[Any] = (),
    twap_actifs: Iterable[Any] = (),
    candidats_anticipation: Iterable[Any] = (),
    cross_venue_liquides: Iterable[Any] = (),
    core_wallets: Iterable[Any] = (),
    challengers: Iterable[Any] = (),
    quota_coins: int = 1000,
    quota_user_slots: int = 10,
    core_slots: int = 8,
    challenger_slots: int = 2,
) -> dict[str, Any]:
    """Construit l'univers de souscription priorisé et borné. Renvoie aussi ce qui est ABANDONNÉ."""
    sources = [
        ("positions_ouvertes", _coins(positions_ouvertes)),
        ("twap_actifs", _coins(twap_actifs)),
        ("candidats_anticipation", _coins(candidats_anticipation)),
        ("cross_venue_liquides", _coins(cross_venue_liquides)),
    ]
    coins_pri = _prioriser_uniques(sources)
    retenus = coins_pri[:max(0, int(quota_coins))]
    abandonnes = coins_pri[max(0, int(quota_coins)):]

    users = selectionner_users(core_wallets, challengers, core_slots=core_slots,
                               challenger_slots=challenger_slots, quota_user_slots=quota_user_slots)

    return {
        "schema_version": SCHEMA_VERSION,
        "coins": [{"coin": c, "priorite": tag} for c, tag in retenus],
        "users_core": users["core"],
        "users_challengers": users["challengers"],
        "abandons": {
            "coins": [{"coin": c, "priorite": tag} for c, tag in abandonnes],
            "users": users["abandons"],
        },
        "quotas": {
            "coins_utilises": len(retenus), "quota_coins": int(quota_coins),
            "user_slots_utilises": users["slots_utilises"], "quota_user_slots": int(quota_user_slots),
            "core_slots": int(core_slots), "challenger_slots": int(challenger_slots),
        },
        "real_execution": False,
    }


__all__ = ["SCHEMA_VERSION", "PRIORITE_COINS", "selectionner_users", "construire_univers"]
