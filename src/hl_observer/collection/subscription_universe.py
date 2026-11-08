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
from collections.abc import Iterable, Mapping
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


# --------------------------------------------------------------------------- #
# Lot 1 — Allocation intelligente des slots WS userFills (PUR, testable)
#
# Le cap dur = QUOTA_USERS (10) subscriptions userFills simultanees. Pour collecter
# un MAXIMUM de fills live avec ces slots rares, on attribue les slots aux leaders
# les plus susceptibles de trader MAINTENANT (debit recent, TWAP en cours, position
# ouverte, profil horaire), on explore via un bandit UCB sur les challengers, et on
# bascule le reste sur le POLL REST (qui n'a pas le cap). Deterministe, 0 reseau.
# --------------------------------------------------------------------------- #

#: poids par defaut du score d'activite (somme ponderee des signaux normalises).
POIDS_ACTIVITE_DEFAUT = {
    "taux": 3.0,       # fills/min recents (signal le plus fort)
    "recence": 2.0,    # a tradé il y a peu -> va probablement retrader
    "twap": 1.5,       # TWAP/metaorder en cours -> fills imminents garantis
    "notional": 1.0,   # grosse position ouverte -> gestion active probable
    "volatilite": 1.0, # coins volatils -> plus de trades
    "horaire": 1.0,    # actif a l'heure courante (profil horaire)
}
_RECENCE_DEMIVIE_MS = 120_000.0   # un fill vieux de 2 min vaut la moitie
_NOTIONAL_REF_USD = 100_000.0     # normalisation log du notional ouvert


def _taux_fills_par_min(stat: Mapping[str, Any]) -> float:
    taux = stat.get("fills_par_min")
    if isinstance(taux, (int, float)) and taux >= 0:
        return float(taux)
    recents = stat.get("fills_recents")
    fenetre = stat.get("fenetre_min")
    if isinstance(recents, (int, float)) and isinstance(fenetre, (int, float)) and fenetre > 0:
        return max(0.0, float(recents) / float(fenetre))
    return 0.0


def _activite_horaire(stat: Mapping[str, Any], now_ms: int) -> float:
    val = stat.get("activite_horaire_courante")
    if isinstance(val, (int, float)):
        return max(0.0, min(1.0, float(val)))
    profil = stat.get("profil_horaire")
    if isinstance(profil, Mapping):
        import time as _t
        heure = _t.gmtime(now_ms / 1000.0).tm_hour
        for cle in (heure, str(heure)):
            if cle in profil and isinstance(profil[cle], (int, float)):
                return max(0.0, min(1.0, float(profil[cle])))
    return 0.0


def score_activite_leader(
    stat: Mapping[str, Any], *, now_ms: int, poids: Mapping[str, float] | None = None,
) -> float:
    """Score d'activite d'un leader (plus haut = merite un slot WS userFills).

    ``stat`` champs (tous optionnels) : ``fills_par_min`` ou (``fills_recents`` +
    ``fenetre_min``) ; ``dernier_fill_ms`` ; ``twap_actif`` ; ``notional_ouvert_usd`` ;
    ``volatilite`` (0..1) ; ``activite_horaire_courante`` (0..1) ou ``profil_horaire``.
    Un leader ``snapshot_only`` (jamais de fill forward) renvoie ``-inf`` : il ne doit
    JAMAIS consommer un slot WS (repli poll).
    """
    if not isinstance(stat, Mapping):
        return 0.0
    if stat.get("snapshot_only") is True:
        return float("-inf")
    w = dict(POIDS_ACTIVITE_DEFAUT)
    if poids:
        w.update({k: float(v) for k, v in poids.items()})

    taux = _taux_fills_par_min(stat)
    taux_n = taux / (taux + 1.0)  # saturation douce (0..1)

    dernier = stat.get("dernier_fill_ms")
    if isinstance(dernier, (int, float)) and dernier > 0:
        age = max(0.0, now_ms - float(dernier))
        recence = 0.5 ** (age / _RECENCE_DEMIVIE_MS)  # 1 juste apres, decroit
    else:
        recence = 0.0

    twap = 1.0 if stat.get("twap_actif") else 0.0

    notion = stat.get("notional_ouvert_usd")
    if isinstance(notion, (int, float)) and notion > 0:
        notion_n = min(1.0, math.log1p(float(notion)) / math.log1p(_NOTIONAL_REF_USD))
    else:
        notion_n = 0.0

    vol = stat.get("volatilite")
    vol_n = max(0.0, min(1.0, float(vol))) if isinstance(vol, (int, float)) else 0.0

    horaire = _activite_horaire(stat, now_ms)

    return (
        w["taux"] * taux_n + w["recence"] * recence + w["twap"] * twap
        + w["notional"] * notion_n + w["volatilite"] * vol_n + w["horaire"] * horaire
    )


def selectionner_challengers_ucb(
    candidats: Iterable[str], stats: Mapping[str, Mapping[str, Any]], *,
    slots: int = 2, c: float = 1.4,
) -> list[str]:
    """Choisit ``slots`` challengers par bandit UCB1 sur le debit de fills observe.

    Reward d'un leader = fills observes / fois ou il a eu un slot (``fills_observes`` /
    ``essais``). Un leader jamais essaye (``essais`` absent/0) a une priorite infinie
    (exploration). Deterministe a stats egales (tri par (-ucb, leader)).
    """
    cands = [str(x) for x in candidats if x not in (None, "")]
    if slots <= 0 or not cands:
        return []
    total = sum(max(0, int((stats.get(x) or {}).get("essais", 0) or 0)) for x in cands)
    total = max(1, total)
    ln_total = math.log(total + 1.0)

    def ucb(leader: str) -> float:
        st = stats.get(leader) or {}
        essais = int(st.get("essais", 0) or 0)
        if essais <= 0:
            return float("inf")  # jamais essaye -> explorer en priorite
        reward = float(st.get("fills_observes", 0) or 0) / essais
        return reward + c * math.sqrt(ln_total / essais)

    ordonnes = sorted(cands, key=lambda l: (-ucb(l), l))
    return ordonnes[:slots]


def allouer_slots_ws(
    leaders: Iterable[str], stats: Mapping[str, Mapping[str, Any]] | None = None, *,
    now_ms: int, user_slots: int = QUOTA_USERS, core_slots: int = 8,
    challenger_slots: int = 2, poids: Mapping[str, float] | None = None, c_ucb: float = 1.4,
) -> dict[str, Any]:
    """Repartit les leaders entre WS (slots rares) et POLL (reste), pour MAXIMISER les
    fills live captes.

    - exclut les ``snapshot_only`` du WS (repli poll) ;
    - CORE = les ``core_slots`` meilleurs scores d'activite ;
    - CHALLENGERS = ``challenger_slots`` via UCB parmi le reste eligible (exploration) ;
    - POLL = tous les autres + les snapshot_only.
    Respecte ``user_slots`` (= core+challengers <= QUOTA_USERS). Renvoie aussi les
    slots a LIBERER (leaders WS precedents devenus non retenus) via ``diff`` cote appelant.
    """
    stats = stats or {}
    core_slots = max(0, min(int(core_slots), int(user_slots)))
    challenger_slots = max(0, min(int(challenger_slots), int(user_slots) - core_slots))
    vus: dict[str, None] = {}
    for lead in leaders:
        s = str(lead).strip()
        if s:
            vus.setdefault(s, None)
    uniques = list(vus)

    snapshot_only = [l for l in uniques if (stats.get(l) or {}).get("snapshot_only") is True]
    eligibles = [l for l in uniques if l not in set(snapshot_only)]

    scores = {l: score_activite_leader(stats.get(l) or {}, now_ms=now_ms, poids=poids)
              for l in eligibles}
    par_score = sorted(eligibles, key=lambda l: (-scores[l], l))
    ws_core = par_score[:core_slots]
    reste_eligible = par_score[core_slots:]
    ws_chall = selectionner_challengers_ucb(reste_eligible, stats, slots=challenger_slots, c=c_ucb)
    ws = ws_core + ws_chall
    poll = [l for l in uniques if l not in set(ws)]
    return {
        "schema_version": SCHEMA_VERSION,
        "ws_core": ws_core,
        "ws_challengers": ws_chall,
        "ws": ws,
        "poll": poll,
        "snapshot_only": snapshot_only,
        "scores": {l: (None if scores[l] == float("-inf") else round(scores[l], 6))
                   for l in eligibles},
        "slots_ws_utilises": len(ws),
        "quota_users": int(user_slots),
        "real_execution": False,
    }


def slots_a_liberer(ws_precedent: Iterable[str], allocation: Mapping[str, Any]) -> list[str]:
    """Leaders qui avaient un slot WS et ne le gardent pas -> a desouscrire (A12)."""
    nouveaux = set(allocation.get("ws", []))
    return sorted(set(str(x) for x in ws_precedent if x) - nouveaux)


__all__ = [
    "SCHEMA_VERSION", "PRIORITE_COINS", "STREAMS_COIN_DEFAUT", "STREAMS_USER_DEFAUT",
    "QUOTA_SUBSCRIPTIONS", "QUOTA_USERS", "QUOTA_CONNEXIONS",
    "selectionner_users", "construire_univers", "diff_souscriptions",
    "POIDS_ACTIVITE_DEFAUT", "score_activite_leader", "selectionner_challengers_ucb",
    "allouer_slots_ws", "slots_a_liberer",
]
