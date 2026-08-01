"""[CABLAGE amont] FEED ADAPTER : alimente le pipeline avec les VRAIS flux Hyperliquid — userFills, L2 book, BBO
et trades — en composant les parsers déjà présents dans src :
  - collection.userfills_live.parser_message_userfills : fills leader normalisés {coin,px,sz,signe,ts_ms,vault,...} ;
  - features.market.extract_l2_levels : niveaux L2 en tuples (px,sz), best_bid/ask ;
  - features.market.derive_market_mid : mid (book > allMids > dernier trade).
Le rôle de l'adaptateur est de JOINDRE chaque fill leader au carnet et au mid de son coin, pour produire les
événements que MegaCablage.traiter_tick consomme (avec `book` pour l'admission/le fill et `mid` pour le prix).
Les fills de SNAPSHOT (rejeu d'historique à la connexion) sont ignorés par défaut (pas du flux live tradable).
0 réseau (on parse des messages déjà reçus), 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

from hl_observer.features.market import extract_l2_levels, derive_market_mid
from hl_observer.collection.userfills_live import parser_message_userfills


def book_depuis_l2(l2_data: dict[str, Any] | None) -> dict[str, Any]:
    """Frame l2Book {coin,time,levels:[[bids],[asks]]} → {bids:[(px,sz)], asks:[(px,sz)], ts_ex, coin}."""
    l2_data = l2_data or {}
    bids, asks = extract_l2_levels(l2_data)
    return {"bids": bids, "asks": asks, "ts_ex": l2_data.get("time"), "coin": l2_data.get("coin")}


def book_depuis_bbo(bbo_data: dict[str, Any] | None) -> dict[str, Any]:
    """Frame bbo {coin,time,bbo:[{px,sz}(bid),{px,sz}(ask)]} → carnet à un niveau {bids,asks}."""
    bbo = (bbo_data or {}).get("bbo") or []
    if len(bbo) < 2:
        return {"bids": [], "asks": []}
    try:
        bid = (float(bbo[0]["px"]), float(bbo[0].get("sz", 0.0) or 0.0))
        ask = (float(bbo[1]["px"]), float(bbo[1].get("sz", 0.0) or 0.0))
    except (TypeError, ValueError, KeyError, IndexError):
        return {"bids": [], "asks": []}
    return {"bids": [bid], "asks": [ask], "ts_ex": (bbo_data or {}).get("time")}


def derniers_prix_trades(trades_data: Any) -> dict[str, float]:
    """Frame trades {channel,data:[{coin,px,...}]} (ou liste) → {COIN: dernier px} (fallback de mid)."""
    data = trades_data.get("data") if isinstance(trades_data, dict) else trades_data
    out: dict[str, float] = {}
    for t in (data or []):
        try:
            out[str(t["coin"]).upper()] = float(t["px"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _mid(book: dict[str, Any], *, coin: str, allmids: dict[str, Any] | None,
         dernier_trade: Any) -> Any:
    bids, asks = book.get("bids"), book.get("asks")
    bb = bids[0][0] if bids else None
    ba = asks[0][0] if asks else None
    return derive_market_mid(coin, best_bid=bb, best_ask=ba, all_mids=allmids,
                             last_trade_price=dernier_trade).mid


def construire_evenements(*, userfills_msg: Any = None, l2_par_coin: dict[str, Any] | None = None,
                          bbo_par_coin: dict[str, Any] | None = None, trades_msg: Any = None,
                          allmids: dict[str, Any] | None = None, vault: str = "",
                          inclure_snapshot: bool = False) -> dict[str, Any]:
    """Joint les 4 canaux en événements pipeline. Chaque fill leader (hors snapshot) est enrichi du carnet et du
    mid de son coin. Retourne {evenements:[...], books, mids} — `evenements` prêt pour MegaCablage.traiter_tick."""
    books: dict[str, Any] = {}
    for coin, l2 in (l2_par_coin or {}).items():
        books[str(coin).upper()] = book_depuis_l2(l2)
    for coin, bbo in (bbo_par_coin or {}).items():
        c = str(coin).upper()
        if c not in books or not books[c].get("bids"):
            books[c] = book_depuis_bbo(bbo)
    derniers = derniers_prix_trades(trades_msg) if trades_msg else {}
    mids: dict[str, Any] = {}
    for coin, book in books.items():
        m = _mid(book, coin=coin, allmids=allmids, dernier_trade=derniers.get(coin))
        if m is not None:
            mids[coin] = m
    for coin, px in (allmids or {}).items():
        mids.setdefault(str(coin).upper(), px)
    evenements: list[dict[str, Any]] = []
    fills = parser_message_userfills(userfills_msg, vault=vault) if userfills_msg else []
    for f in fills:
        if f.get("isSnapshot") and not inclure_snapshot:
            continue
        coin = str(f.get("coin", "")).upper()
        evenements.append({"coin": coin, "px": f.get("px"), "sz": f.get("sz"), "signe": f.get("signe"),
                           "ts_ms": f.get("ts_ms"), "vault": f.get("vault", vault),
                           "book": books.get(coin), "mid": mids.get(coin, f.get("px"))})
    return {"evenements": evenements, "books": books, "mids": mids}


__all__ = ["book_depuis_l2", "book_depuis_bbo", "derniers_prix_trades", "construire_evenements"]
