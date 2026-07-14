"""Enregistreur CARNET L2 + FUNDING — la donnee qui manque pour tester les seules strategies
dont l'esperance ne depend PAS d'un pouvoir predictif.

POURQUOI CE MODULE EXISTE (mesure du 2026-07-11, 24 133 signaux reels, prix a la seconde) :
le signal de copy-trading n'a **aucun** pouvoir predictif exploitable. Apres un ordre de whale,
le prix bouge de -0.7 a +0.8 bps en moyenne, dans un bruit de 50-100 bps. Meme a **cout zero**
l'esperance reste NEGATIVE. Aucun TP/SL, aucun horizon, aucun filtre, aucun hedge, aucune
inversion ne rend cela positif hors echantillon. On ne peut donc pas gagner en PREDISANT.

Restent trois familles dont l'esperance ne repose PAS sur une prediction :
  1. MARKET MAKING  : on ENCAISSE le spread au lieu de le payer.
                      esperance = spread capture x taux de fill - selection adverse - inventaire
  2. FUNDING (delta-neutre) : on encaisse le taux de financement, sans pari directionnel.
                      esperance = funding percu - couts des deux jambes
  3. ARBITRAGE      : on capture un ecart de prix constate, pas anticipe.

Ces trois familles sont **intestables aujourd'hui** : on n'enregistre ni le carnet, ni le funding.
Ce module comble exactement ce trou. Il n'ouvre aucune position, n'emet aucun ordre : il OBSERVE
et il ECRIT. C'est un instrument de mesure, pas une strategie.

READ-ONLY. PAPER-ONLY. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import os
import time
from typing import Any, Iterable

from hl_observer.collection.research_recorder import record

STREAM_L2 = "l2_book"
STREAM_FUNDING = "funding"

# Bornes dures : un run de 48 h ne doit jamais saturer le disque (cf. le crash DB de 29 Go).
MAX_BYTES_L2 = 200_000_000
MAX_BYTES_FUNDING = 20_000_000


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def summarize_l2(coin: str, book: dict, *, depth_levels: int = 5, now_ms: int | None = None) -> dict | None:
    """Reduit un carnet L2 brut a ce qui sert VRAIMENT au market making.

    On ne stocke pas le carnet entier (trop volumineux sur 48 h) mais les grandeurs qui
    determinent l'esperance d'un market maker : le spread qu'on encaisserait, la profondeur
    disponible de chaque cote, et le desequilibre (qui predit le sens du prochain tick).

    Retourne None si le carnet est vide ou incoherent -- jamais de donnee fabriquee.
    """
    levels = book.get("levels") if isinstance(book, dict) else None
    if not isinstance(levels, list) or len(levels) < 2:
        return None
    bids, asks = levels[0], levels[1]
    if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
        return None

    def _side(rows: Iterable[Any]) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            px, sz = _f(row.get("px")), _f(row.get("sz"))
            if px > 0 and sz > 0:
                out.append((px, sz))
        return out

    b, a = _side(bids), _side(asks)
    if not b or not a:
        return None

    best_bid, best_ask = b[0][0], a[0][0]
    if best_ask <= best_bid:          # carnet croise = donnee incoherente -> on jette
        return None
    mid = (best_bid + best_ask) / 2.0
    spread_bps = (best_ask - best_bid) / mid * 10_000.0

    bid_depth = sum(px * sz for px, sz in b[:depth_levels])
    ask_depth = sum(px * sz for px, sz in a[:depth_levels])
    total = bid_depth + ask_depth
    imbalance = (bid_depth - ask_depth) / total if total > 0 else 0.0

    # micro-prix : le vrai "juste prix" pondere par la profondeur (predit le prochain tick
    # bien mieux que le mid ; c'est la grandeur cle de l'anti-selection-adverse).
    bs, asz = b[0][1], a[0][1]
    micro = (best_bid * asz + best_ask * bs) / (bs + asz) if (bs + asz) > 0 else mid

    return {
        "ts": (now_ms if now_ms is not None else int(time.time() * 1000)) / 1000.0,
        "coin": str(coin).upper(),
        "bid": best_bid,
        "ask": best_ask,
        "mid": mid,
        "micro_price": micro,
        "spread_bps": spread_bps,
        "bid_depth_usd": bid_depth,
        "ask_depth_usd": ask_depth,
        "imbalance": imbalance,
        "bid_size": bs,
        "ask_size": asz,
    }


def summarize_funding(coin: str, ctx: dict, *, now_ms: int | None = None) -> dict | None:
    """Extrait le taux de financement courant d'un contexte d'actif Hyperliquid.

    `funding` est le taux HORAIRE sur Hyperliquid. On enregistre aussi l'open interest et le
    prix oracle : sans eux on ne peut pas juger si le funding est capturable (liquidite) ni
    reconstruire le PnL d'une position delta-neutre.
    """
    if not isinstance(ctx, dict):
        return None
    funding = ctx.get("funding")
    if funding is None:
        return None                    # donnee absente -> on n'invente rien
    rate = _f(funding, float("nan"))
    if rate != rate:                   # NaN
        return None
    mark = _f(ctx.get("markPx"))
    oracle = _f(ctx.get("oraclePx"))
    oi = _f(ctx.get("openInterest"))
    # VOLUME 24 h -- LA DONNEE QUI MANQUAIT (2026-07-12).
    # Hyperliquid la renvoie DEJA dans `metaAndAssetCtxs` (`dayNtlVlm`) : on la jetait.
    # Sans elle, on ne peut pas juger un market maker. Un spread de 49 bps sur un marche que
    # PERSONNE ne traverse ne rapporte RIEN : un MM gagne = spread x volume echange CONTRE LUI.
    # On portait juste l'inventaire d'un coin illiquide. Zero requete de plus : c'etait dans la
    # reponse depuis le debut.
    vol24 = _f(ctx.get("dayNtlVlm"))
    prev = _f(ctx.get("prevDayPx"))
    return {
        "ts": (now_ms if now_ms is not None else int(time.time() * 1000)) / 1000.0,
        "coin": str(coin).upper(),
        "funding_hourly": rate,
        "funding_bps_hourly": rate * 10_000.0,
        "funding_apr_pct": rate * 24.0 * 365.0 * 100.0,
        "mark_px": mark,
        "oracle_px": oracle,
        "open_interest": oi,
        "day_ntl_volume_usd": vol24,
        "prev_day_px": prev,
        # base = ecart mark/oracle : c'est ce qui fait DERIVER le funding a l'heure suivante
        "basis_bps": ((mark - oracle) / oracle * 10_000.0) if oracle > 0 else 0.0,
    }


def enabled() -> bool:
    """OFF par defaut : aucun comportement n'est modifie tant que Flo ne l'active pas."""
    return str(os.environ.get("HYPERSMART_RECORD_MICROSTRUCTURE", "0")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def record_l2(base_dir: str, coin: str, book: dict, *, now_ms: int | None = None) -> bool:
    row = summarize_l2(coin, book, now_ms=now_ms)
    if row is None:
        return False
    record(base_dir, STREAM_L2, row, max_bytes=MAX_BYTES_L2)
    return True


def record_funding(base_dir: str, coin: str, ctx: dict, *, now_ms: int | None = None) -> bool:
    row = summarize_funding(coin, ctx, now_ms=now_ms)
    if row is None:
        return False
    record(base_dir, STREAM_FUNDING, row, max_bytes=MAX_BYTES_FUNDING)
    return True


def record_funding_snapshot(base_dir: str, meta_and_ctxs: Any, *, now_ms: int | None = None) -> int:
    """Enregistre le funding de TOUS les marches d'un coup.

    `metaAndAssetCtxs` renvoie [meta, contextes] ou meta.universe[i] correspond a contextes[i].
    Un seul appel reseau donne le funding de tout le marche : c'est la facon la moins couteuse
    (et la plus polie envers la source) de constituer l'historique de funding qui nous manque.
    """
    if not isinstance(meta_and_ctxs, (list, tuple)) or len(meta_and_ctxs) < 2:
        return 0
    meta, ctxs = meta_and_ctxs[0], meta_and_ctxs[1]
    universe = meta.get("universe") if isinstance(meta, dict) else None
    if not isinstance(universe, list) or not isinstance(ctxs, list):
        return 0
    written = 0
    for asset, ctx in zip(universe, ctxs):
        name = asset.get("name") if isinstance(asset, dict) else None
        if not name:
            continue
        if record_funding(base_dir, str(name), ctx if isinstance(ctx, dict) else {}, now_ms=now_ms):
            written += 1
    return written


__all__ = [
    "STREAM_L2",
    "STREAM_FUNDING",
    "enabled",
    "summarize_l2",
    "summarize_funding",
    "record_l2",
    "record_funding",
    "record_funding_snapshot",
]
