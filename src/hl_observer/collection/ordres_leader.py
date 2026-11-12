"""Ordres en attente d'un leader : ce qu'il COMPTE faire, avant qu'il ne le fasse.

Hyperliquid publie, pour n'importe quelle adresse et sans signature, la liste de ses ordres en
attente (``openOrders`` en WebSocket, ``frontendOpenOrders`` en REST). Vérifié le 2026-11-11 sur
25 leaders suivis : 12 en avaient (1 742 ordres) — limites d'entrée, limites de sortie
« reduce only » (prises de profit), stops déclenchés.

Pour une copie, c'est une information d'une autre nature que les fills :

* une ENTRÉE en attente dit où le leader veut entrer, avant son exécution — copier un fill, c'est
  toujours arriver après ; lire son ordre, c'est pouvoir arriver en même temps ;
* une SORTIE en attente (prise de profit, stop) dit où il compte sortir — la copie n'a plus à
  deviner ses sorties ;
* une annulation dit qu'il a changé d'avis.

Ce module est PUR : il normalise un message en instantané et le résume. Il n'envoie rien.
Un carnet de plus de ``MAX_ORDRES_DETAILLES`` ordres est celui d'un teneur de marché : ses
centaines de cotations ne sont pas une intention copiable et pèseraient des gigaoctets ; on n'en
garde que le résumé, et l'instantané le dit (``tronque``). PAPER / lecture seule.
"""
from __future__ import annotations

import math
from typing import Any

from hl_observer.instrument_identity import preserve_native_instrument_symbol

SCHEMA_ORDRES = "hypersmart.copy_vault_leader_orders.v1"
MAX_ORDRES_DETAILLES = 200
MAX_COINS_RESUMES = 20

ENTREE_LIMITE = "ENTREE_LIMITE"          # limite qui ouvre ou renforce
SORTIE_LIMITE = "SORTIE_LIMITE"          # limite « reduce only » : prise de profit
STOP = "STOP"                            # ordre déclenché de type stop
PRISE_DE_PROFIT_DECLENCHEE = "PRISE_DE_PROFIT_DECLENCHEE"
AUTRE = "AUTRE"
GENRES = (ENTREE_LIMITE, SORTIE_LIMITE, STOP, PRISE_DE_PROFIT_DECLENCHEE, AUTRE)


def _nombre(valeur: Any) -> float | None:
    try:
        nombre = float(valeur)
    except (TypeError, ValueError):
        return None
    return nombre if math.isfinite(nombre) else None


def genre_ordre(ordre: dict[str, Any]) -> str:
    """Rôle économique d'un ordre normalisé."""
    type_ordre = str(ordre.get("type") or "").lower()
    if ordre.get("is_trigger"):
        if "stop" in type_ordre:
            return STOP
        if "take" in type_ordre or "profit" in type_ordre:
            return PRISE_DE_PROFIT_DECLENCHEE
        return AUTRE
    if "limit" in type_ordre:
        return SORTIE_LIMITE if ordre.get("reduce_only") else ENTREE_LIMITE
    return AUTRE


def normaliser_ordre(brut: Any) -> dict[str, Any] | None:
    """Un ordre de la réponse officielle -> forme normalisée ; ``None`` s'il n'est pas lisible (jamais deviné)."""
    if not isinstance(brut, dict):
        return None
    coin = preserve_native_instrument_symbol(brut.get("coin"))
    cote = str(brut.get("side") or "")
    prix, taille = _nombre(brut.get("limitPx")), _nombre(brut.get("sz"))
    oid = brut.get("oid")
    if not coin or cote not in ("B", "A") or type(oid) is not int or oid <= 0:
        return None
    if prix is None or prix <= 0 or taille is None or taille < 0:
        return None
    declencheur = _nombre(brut.get("triggerPx"))
    horodatage = brut.get("timestamp")
    ordre = {
        "coin": coin, "side": cote, "px": prix, "sz": taille, "orig_sz": _nombre(brut.get("origSz")), "oid": oid,
        "ts_ms": horodatage if type(horodatage) is int and horodatage > 0 else None,
        "type": str(brut.get("orderType") or ""), "tif": brut.get("tif") if isinstance(brut.get("tif"), str) else None,
        "reduce_only": bool(brut.get("reduceOnly")), "is_trigger": bool(brut.get("isTrigger")),
        "trigger_px": declencheur if declencheur and declencheur > 0 else None,
        "trigger_condition": brut.get("triggerCondition") if isinstance(brut.get("triggerCondition"), str) else None,
        "is_position_tpsl": bool(brut.get("isPositionTpsl")),
    }
    ordre["genre"] = genre_ordre(ordre)
    return ordre


def construire_instantane_ordres(
    data: Any, *, user: str, recv_ms: int, dex: str | None = None, source: str = "OPEN_ORDERS_WS",
    max_ordres: int = MAX_ORDRES_DETAILLES,
) -> dict[str, Any] | None:
    """Instantané des ordres en attente d'un compte. ``data`` : message ``openOrders`` (``{dex, user,
    orders}``) ou liste REST. ``None`` si le message n'est pas une liste d'ordres."""
    if isinstance(data, dict):
        liste = data.get("orders")
        dex = data.get("dex") if dex is None and isinstance(data.get("dex"), str) else dex
    else:
        liste = data
    compte = str(user or "").strip().lower()
    if not isinstance(liste, list) or not compte.startswith("0x") or type(recv_ms) is not int or recv_ms <= 0:
        return None
    ordres = [o for o in (normaliser_ordre(brut) for brut in liste) if o is not None]
    par_genre = {genre: 0 for genre in GENRES}
    par_coin: dict[str, dict[str, float]] = {}
    for ordre in ordres:
        par_genre[ordre["genre"]] += 1
        cellule = par_coin.setdefault(ordre["coin"], {"B": 0.0, "A": 0.0})
        cellule[ordre["side"]] += ordre["px"] * ordre["sz"]
    tronque = len(ordres) > max_ordres
    plus_gros = sorted(par_coin.items(), key=lambda kv: (-(kv[1]["B"] + kv[1]["A"]), kv[0]))[:MAX_COINS_RESUMES]
    return {
        "schema_version": SCHEMA_ORDRES, "vault": compte, "dex": str(dex or ""), "ts_ms": int(recv_ms),
        "n_orders": len(ordres), "n_ignores": len(liste) - len(ordres),
        "par_genre": {genre: n for genre, n in par_genre.items() if n},
        "notionnel_par_coin": {coin: {cote: round(valeur, 2) for cote, valeur in cotes.items()} for coin, cotes in plus_gros},
        # carnet de teneur de marché : résumé seulement, et l'instantané le dit
        "tronque": tronque, "orders": [] if tronque else sorted(ordres, key=lambda o: o["oid"]),
        "source": source, "data_origin": "REAL_OBSERVED", "paper_read_only": True,
    }


def signature_ordres(instantane: dict[str, Any]) -> tuple:
    """Ce qui fait qu'un carnet d'ordres a CHANGÉ : identité, prix et taille restante de chaque ordre."""
    if instantane.get("tronque"):
        return ("RESUME", instantane.get("n_orders"), tuple(sorted((instantane.get("par_genre") or {}).items())))
    return tuple((o["oid"], o["px"], o["sz"], o["trigger_px"]) for o in instantane.get("orders") or ())


__all__ = ["AUTRE", "ENTREE_LIMITE", "GENRES", "MAX_ORDRES_DETAILLES", "PRISE_DE_PROFIT_DECLENCHEE",
           "SCHEMA_ORDRES", "SORTIE_LIMITE", "STOP", "construire_instantane_ordres", "genre_ordre",
           "normaliser_ordre", "signature_ordres"]
