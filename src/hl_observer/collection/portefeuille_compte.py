"""Portefeuille complet d'un compte Hyperliquid depuis son ``clearinghouseState`` (PUR, sans E/S).

Deux sources donnent le même état, sous deux formes :

* WebSocket (vérifié le 2026-11-11) : ``{"clearinghouseState": {...}, "dex": "", "user": "0x…"}`` —
  l'état est IMBRIQUÉ ;
* REST ``/info`` : l'état lui-même, à plat (``assetPositions``, ``marginSummary``, ``time``).

Un compte a UN ÉTAT PAR DEX : les positions prises sur un dex HIP-3 (``xyz``…) n'apparaissent pas
dans l'état du dex principal. Chaque instantané porte donc sa portée (``portfolio_scope``) ; le
portefeuille d'un dex n'est jamais lu comme le portefeuille entier du compte.

L'instantané suit le format des instantanés de vault (``vault``, ``ts_ms``, ``nav_usd``,
``positions``) : c'est la cible d'une réplication d'inventaire. Un compte sans position donne une
liste vide (à plat), jamais une absence de ligne ; une position illisible invalide tout
l'instantané. Lecture seule : aucun ordre, aucune clé.
"""
from __future__ import annotations

import math
from typing import Any

SCHEMA_PORTEFEUILLE = "hypersmart.copy_vault_portfolio_snapshot.v1"


def nombre(value: Any) -> float | None:
    """Nombre fini, ou ``None`` (absent, illisible, infini, booléen)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def etat_du_compte(data: Any) -> dict[str, Any] | None:
    """État du compte porté par un message ``clearinghouseState`` (imbriqué ou à plat)."""
    if not isinstance(data, dict):
        return None
    imbrique = data.get("clearinghouseState")
    if isinstance(imbrique, dict):
        return imbrique
    return data if isinstance(data.get("assetPositions"), list) else None


def construire_portefeuille(data: Any, *, user: str, recv_ms: int, dex: str | None = None,
                            source: str = "CLEARINGHOUSE_WS") -> dict[str, Any] | None:
    """Instantané COMPLET du portefeuille (toutes les positions + valeur du compte).

    ``dex`` : portée explicite quand l'appelant la connaît (requête REST) ; sinon celle du message.
    ``None`` si le message est illisible ou si une position l'est.
    """
    etat = etat_du_compte(data)
    user = str(user or "").strip().lower()
    if etat is None or not user:
        return None
    positions: list[dict[str, Any]] = []
    brute = nette = latent = 0.0
    for item in etat.get("assetPositions") or []:
        pos = item.get("position") if isinstance(item, dict) else None
        if not isinstance(pos, dict):
            return None
        coin, szi = str(pos.get("coin") or ""), nombre(pos.get("szi"))
        if not coin or szi is None:
            return None
        if szi == 0:
            continue
        valeur, upnl = nombre(pos.get("positionValue")), nombre(pos.get("unrealizedPnl"))
        levier = pos.get("leverage")
        positions.append({"coin": coin, "szi": szi, "entryPx": nombre(pos.get("entryPx")),
                          "levier": nombre(levier.get("value")) if isinstance(levier, dict) else None,
                          "uPnl": upnl})
        if valeur is not None:
            brute += abs(valeur)
            nette += valeur if szi > 0 else -valeur
        latent += upnl or 0.0
    marge = etat.get("marginSummary")
    nav = nombre(marge.get("accountValue")) if isinstance(marge, dict) else None
    if dex is None:
        dex = str(data.get("dex") or "") if isinstance(data, dict) else ""
    return {
        "schema_version": SCHEMA_PORTEFEUILLE,
        "vault": user, "ts_ms": int(recv_ms), "exchange_ts_ms": nombre(etat.get("time")),
        "nav_usd": nav, "expo_brute_usd": round(brute, 2), "expo_nette_usd": round(nette, 2),
        "levier": round(brute / nav, 3) if nav and nav > 0 else None,
        "pnl_latent_usd": round(latent, 2), "n_positions": len(positions), "positions": positions,
        "dex": dex, "portfolio_scope": f"DEX:{dex}" if dex else "DEX_PRINCIPAL",
        "source": source, "data_origin": "REAL_OBSERVED",
        "read_only": True, "real_execution": False,
    }


__all__ = ["SCHEMA_PORTEFEUILLE", "construire_portefeuille", "etat_du_compte", "nombre"]
