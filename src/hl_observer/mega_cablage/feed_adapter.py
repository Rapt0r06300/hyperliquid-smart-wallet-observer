"""[CABLAGE amont] FEED ADAPTER : alimente le pipeline avec les VRAIS flux Hyperliquid — userFills, L2 book, BBO
et trades — en composant les parsers déjà présents dans src :
  - collection.userfills_live.parser_message_userfills : fills leader normalisés {coin,px,sz,signe,ts_ms,vault,...} ;
  - features.market.extract_l2_levels : niveaux L2 en tuples (px,sz), best_bid/ask ;
  - features.market.derive_market_mid : mid (book > allMids > dernier trade).
Le rôle de l'adaptateur est de JOINDRE chaque fill leader au carnet et au mid de son coin, pour produire les
événements que MegaCablage.traiter_tick consomme (avec `book` pour l'admission/le fill et `mid` pour le prix).
Quand un carnet de venue de couverture (hedge) et un edge cross-venue sont fournis, l'événement porte en plus un
`cross_venue` complet → le pipeline exécute alors les DEUX jambes en paper (au lieu de tracer).
`evenements_depuis_bundles` est le point d'entrée UNIQUE : chaque bundle de messages bruts (par tick) devient des
événements pipeline. Les fills de SNAPSHOT (rejeu d'historique) sont ignorés par défaut. 0 réseau, 0 ordre réel.
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
                          inclure_snapshot: bool = False,
                          l2_hedge_par_coin: dict[str, Any] | None = None,
                          edge_cross_venue_par_coin: dict[str, Any] | None = None,
                          venue_hedge: str = "BINANCE",
                          latences_cross_venue: tuple[float, ...] | None = None) -> dict[str, Any]:
    """Joint les canaux en événements pipeline. Chaque fill leader (hors snapshot) est enrichi du carnet et du mid
    de son coin. Si un carnet hedge + un edge cross-venue existent pour le coin, l'événement porte un `cross_venue`
    complet (→ exécution 2 jambes). Retourne {evenements, books, mids}."""
    books: dict[str, Any] = {}
    for coin, l2 in (l2_par_coin or {}).items():
        books[str(coin).upper()] = book_depuis_l2(l2)
    for coin, bbo in (bbo_par_coin or {}).items():
        c = str(coin).upper()
        if c not in books or not books[c].get("bids"):
            books[c] = book_depuis_bbo(bbo)
    hedge_books: dict[str, Any] = {}
    for coin, l2 in (l2_hedge_par_coin or {}).items():
        hedge_books[str(coin).upper()] = book_depuis_l2(l2)
    derniers = derniers_prix_trades(trades_msg) if trades_msg else {}
    mids: dict[str, Any] = {}
    for coin, book in books.items():
        m = _mid(book, coin=coin, allmids=allmids, dernier_trade=derniers.get(coin))
        if m is not None:
            mids[coin] = m
    for coin, px in (allmids or {}).items():
        mids.setdefault(str(coin).upper(), px)
    edges = {str(k).upper(): v for k, v in (edge_cross_venue_par_coin or {}).items()}
    latences = latences_cross_venue or (10.0, 20.0, 30.0, 40.0, 50.0)
    evenements: list[dict[str, Any]] = []
    fills = parser_message_userfills(userfills_msg, vault=vault) if userfills_msg else []
    for f in fills:
        if f.get("isSnapshot") and not inclure_snapshot:
            continue
        coin = str(f.get("coin", "")).upper()
        ev = {"coin": coin, "px": f.get("px"), "sz": f.get("sz"), "signe": f.get("signe"),
              "ts_ms": f.get("ts_ms"), "vault": f.get("vault", vault),
              "book": books.get(coin), "mid": mids.get(coin, f.get("px"))}
        edge = edges.get(coin)
        if edge is not None:
            ev["cross_venue_edge_bps"] = edge          # signal scalaire (→ MORE_DATA si pas de carnet hedge)
            hb = hedge_books.get(coin)
            if hb and hb.get("bids") and hb.get("asks"):
                ev["cross_venue"] = {"edge_bps": edge, "venue_hedge": str(venue_hedge).upper(),
                                     "carnet_hedge": hb, "latences_ms": tuple(latences)}
        evenements.append(ev)
    return {"evenements": evenements, "books": books, "mids": mids}


def evenements_depuis_bundles(bundles: list[dict[str, Any]] | None, *, vault_defaut: str = "") -> list[dict[str, Any]]:
    """Point d'entrée UNIQUE. Chaque bundle = messages bruts d'un tick (userfills_msg, l2_par_coin, bbo_par_coin,
    trades_msg, allmids, l2_hedge_par_coin, edge_cross_venue_par_coin, ...) OU un passe-plat {evenements:[...]}.
    Rend la liste plate d'événements pipeline — tout flux brut passe donc par le feed_adapter."""
    out: list[dict[str, Any]] = []
    for b in (bundles or []):
        if not isinstance(b, dict):
            continue
        if "evenements" in b:
            out.extend(b.get("evenements") or [])
            continue
        res = construire_evenements(
            userfills_msg=b.get("userfills_msg"), l2_par_coin=b.get("l2_par_coin"),
            bbo_par_coin=b.get("bbo_par_coin"), trades_msg=b.get("trades_msg"), allmids=b.get("allmids"),
            vault=b.get("vault", vault_defaut), inclure_snapshot=b.get("inclure_snapshot", False),
            l2_hedge_par_coin=b.get("l2_hedge_par_coin"),
            edge_cross_venue_par_coin=b.get("edge_cross_venue_par_coin"),
            venue_hedge=b.get("venue_hedge", "BINANCE"),
            latences_cross_venue=b.get("latences_cross_venue"))
        out.extend(res["evenements"])
    return out


__all__ = ["book_depuis_l2", "book_depuis_bbo", "derniers_prix_trades", "construire_evenements",
           "evenements_depuis_bundles"]
