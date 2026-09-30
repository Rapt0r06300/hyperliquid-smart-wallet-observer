"""ÉVÉNEMENT CANONIQUE — schéma tick-by-tick + séparation RAW / CANONICAL / DERIVED (IDEA-1, 2, 4, 9).

Pourquoi : pour rejouer EXACTEMENT ce que HyperSmart savait à l'instant T, il ne suffit pas de garder
bid/ask. Il faut les trois horloges (exchange/recv/write), la provenance (source, channel, reconnect_id),
la nature du message (snapshot vs incrémental), les identifiants d'exchange (tid/oid/hash) et les drapeaux
qualité. Ce module NORMALISE un message brut en événement CANONICAL sans jamais modifier le RAW.

Trois couches strictement séparées (IDEA-2) :
  • RAW       : l'événement reçu tel quel (jamais muté ici — on travaille sur une copie) ;
  • CANONICAL : normalisé, horodaté, dédupliqué, causal (ce module) ;
  • DERIVED   : features/signaux/markouts (produits ailleurs, jamais réinjectés dans le RAW).

IDEA-4 : `isSnapshot=true` = snapshot initial/reprise, `false` = incrémental. Le premier tick n'est JAMAIS
jeté aveuglément : il est marqué SNAPSHOT et reste consommable.
IDEA-9 : identité stable par événement (timestamp + coin + tid/oid/hash + source/channel), reproductible
d'un process à l'autre — condition nécessaire d'une déduplication qui survit aux crashs (voir dedup_durable).

0 réseau, 0 ordre, paper-only / read-only.
"""
from __future__ import annotations

import hashlib
import json
import time

#: les 3 couches, dans l'ordre du flux.
COUCHES = ("RAW", "CANONICAL", "DERIVED")

#: champs OBLIGATOIRES d'un événement canonique (IDEA-1). Un champ inconnu vaut None — jamais 0 implicite.
SCHEMA_TICK = (
    "event_id", "couche", "data_origin",
    "exchange_ts", "recv_ts", "write_ts",          # les 3 horloges, jamais confondues
    "source", "channel", "coin", "reconnect_id",
    "is_snapshot",                                  # IDEA-4
    "bid", "ask", "bid_sz", "ask_sz", "bids", "asks",
    "trades", "side", "size",
    "tid", "oid", "hash",
    "latence_reception_ms", "gap_ms",
    "duplicate", "data_quality_flags",
)

#: origines possibles de la donnée. SYNTHETIC ne doit jamais être promouvable (voir IDEA-80).
ORIGINES = ("REAL", "SYNTHETIC", "REPLAY", "UNKNOWN")


def _f(x):
    """Float tolérant : rend None si la valeur est absente ou non numérique (jamais 0 par défaut)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _premier(d: dict, *cles):
    for c in cles:
        if d.get(c) is not None:
            return d[c]
    return None


def identite_evenement(*, coin, exchange_ts, source=None, channel=None,
                       tid=None, oid=None, hash_=None, payload=None) -> str:
    """IDEA-9 — identité STABLE et reproductible d'un événement.

    Priorité aux identifiants d'exchange (tid/oid/hash) qui survivent aux reconnexions et aux rotations
    de fichiers ; à défaut, empreinte déterministe du couple (coin, horloge exchange, source, channel,
    payload trié). Deux process qui voient le même message calculent le MÊME id."""
    fort = _premier({"tid": tid, "oid": oid, "hash": hash_}, "tid", "oid", "hash")
    if fort is not None:
        base = "%s|%s|%s" % (str(coin).upper(), "id", fort)
    else:
        corps = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) if payload is not None else ""
        base = "%s|%s|%s|%s|%s" % (str(coin).upper(), exchange_ts, source or "", channel or "", corps)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def normaliser_tick(raw: dict, *, source=None, channel=None, reconnect_id=None,
                    recv_ts=None, write_ts=None, data_origin: str = "REAL",
                    dernier_recv_ts=None, gap_max_ms: float = 5_000.0) -> dict:
    """RAW -> CANONICAL (IDEA-1/2/4/9). Ne modifie JAMAIS `raw` (lecture seule, on construit un nouveau dict).

    Remplit les 3 horloges, la provenance, la nature snapshot/incrémental, les identifiants d'exchange,
    la latence de réception et le gap depuis l'événement précédent, plus les drapeaux qualité.
    Champ absent = None explicite (deny-by-default) : aucune valeur n'est inventée."""
    if not isinstance(raw, dict):
        raise TypeError("evenement RAW invalide (dict attendu)")
    src = dict(raw)                                     # COPIE : le RAW reste intact (IDEA-2)
    maintenant = time.time() * 1000.0
    exchange_ts = _f(_premier(src, "exchange_ts", "time", "ts_ms", "T"))
    recv = _f(recv_ts) if recv_ts is not None else _f(src.get("recv_ts"))
    if recv is None:
        recv = _f(src.get("ts_wall_ms")) or maintenant
    write = _f(write_ts) if write_ts is not None else maintenant

    coin = str(_premier(src, "coin", "symbol", "s") or "").upper() or None
    is_snapshot = bool(_premier(src, "is_snapshot", "isSnapshot") or False)   # IDEA-4
    bid, ask = _f(_premier(src, "bid", "b")), _f(_premier(src, "ask", "a"))

    flags = []
    latence = (recv - exchange_ts) if (recv is not None and exchange_ts is not None) else None
    if latence is not None and latence < 0:
        flags.append("EXCHANGE_TS_DANS_LE_FUTUR")
    gap = None
    if dernier_recv_ts is not None and recv is not None:
        gap = recv - _f(dernier_recv_ts)
        if gap is not None and gap > gap_max_ms:
            flags.append("GAP")
        if gap is not None and gap < 0:
            flags.append("RECV_TS_NON_MONOTONE")
    if bid is not None and ask is not None and ask <= bid:
        flags.append("CARNET_CROISE")
    if exchange_ts is None:
        flags.append("EXCHANGE_TS_ABSENT")
    if coin is None:
        flags.append("COIN_ABSENT")
    if str(data_origin).upper() not in ORIGINES:
        raise ValueError("data_origin inconnue: %s" % data_origin)

    ev = {
        "couche": "CANONICAL",
        "data_origin": str(data_origin).upper(),
        "exchange_ts": exchange_ts, "recv_ts": recv, "write_ts": write,
        "source": source or src.get("source") or src.get("_source"),
        "channel": channel or src.get("channel"),
        "coin": coin,
        "reconnect_id": reconnect_id if reconnect_id is not None else src.get("reconnect_id"),
        "is_snapshot": is_snapshot,
        "bid": bid, "ask": ask,
        "bid_sz": _f(_premier(src, "bid_sz", "bidSz")), "ask_sz": _f(_premier(src, "ask_sz", "askSz")),
        "bids": src.get("bids"), "asks": src.get("asks"),
        "trades": src.get("trades"), "side": src.get("side"), "size": _f(src.get("size")),
        "tid": src.get("tid"), "oid": src.get("oid"), "hash": src.get("hash"),
        "latence_reception_ms": latence, "gap_ms": gap,
        "duplicate": False,                              # renseigné par la dédup durable (IDEA-9)
        "data_quality_flags": flags,
    }
    ev["event_id"] = identite_evenement(coin=coin, exchange_ts=exchange_ts, source=ev["source"],
                                        channel=ev["channel"], tid=ev["tid"], oid=ev["oid"],
                                        hash_=ev["hash"], payload=src)
    return ev


def champs_manquants(ev: dict) -> list:
    """Champs du schéma absents de l'événement (audit IDEA-1). `None` compte comme présent-mais-inconnu."""
    return [c for c in SCHEMA_TICK if c not in ev]


def est_canonique(ev: dict) -> bool:
    return isinstance(ev, dict) and ev.get("couche") == "CANONICAL" and not champs_manquants(ev)


def marquer_derive(ev_canonique: dict, features: dict) -> dict:
    """CANONICAL -> DERIVED (IDEA-2) : produit une NOUVELLE structure ; l'événement canonique reste intact.
    Aucune feature ne peut donc écraser une donnée de marché."""
    if not est_canonique(ev_canonique):
        raise ValueError("marquer_derive exige un evenement CANONICAL complet")
    return {"couche": "DERIVED", "event_id": ev_canonique["event_id"],
            "canonical": dict(ev_canonique), "features": dict(features or {})}


__all__ = ["COUCHES", "SCHEMA_TICK", "ORIGINES", "identite_evenement", "normaliser_tick",
           "champs_manquants", "est_canonique", "marquer_derive"]
