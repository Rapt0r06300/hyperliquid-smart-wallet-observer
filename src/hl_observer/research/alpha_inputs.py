"""ALPHA FACTORY — couche d'ENTRÉES réutilisables : adaptateurs DATA, détecteurs d'ÉVÉNEMENTS, featurizers d'ÉTAT.

C'est la brique P2 : normaliser chaque source en un format commun que la factory consomme, détecter des
événements horodatés, et étiqueter l'état du marché (buckets). Tout est causal (état ≤ t). Ce qui n'a pas de
donnée sort en `BLOCKED_EXTERNAL`/`UNMEASURABLE` — jamais inventé.

Couverture réelle (2026-07-31) :
  * DATA : l2_book HL (OK), wallet fills (OK, SANS taille), metaorder (OK, 24 min), bbo_synchro (OK) ; L4 = ABSENT.
  * EVENTS : Binance shock, OFI shock, microprice displacement, queue depletion, spread transition, TWAP slice (OK) ;
    wallet OPEN/ADD/REDUCE/CLOSE/FLIP = direction seulement (action réelle UNMEASURABLE sans taille).
  * STATES : spread/depth/imbalance/vol/coin/hour/twap_stage/crowding (OK selon la source).

Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.collection import l4_capture as _l4
from hl_observer.research import ofi_microprice as _ofi

UNMEASURABLE = "UNMEASURABLE"
BLOCKED = "BLOCKED_EXTERNAL"


# ════════════════════════ DATA adapters ════════════════════════
def adapter_l2book(path: str) -> dict[str, list[dict[str, float]]]:
    """HL L2 (l2_book) → {coin: [snapshots]}. Profondeur AGRÉGÉE seulement (pas L3/L5/L10/L20 par niveau)."""
    return _ofi.charger_book_csv(path)


def adapter_wallet(path: str, adresse: str | None = None) -> list[dict[str, Any]]:
    """Wallet fills (leader_fills_forward) → événements. SANS taille → action réelle non reconstructible."""
    out: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if adresse and adresse.lower() not in str(r.get("adresse", "")).lower():
                continue
            out.append(r)
    out.sort(key=lambda r: r.get("ts_ms", 0))
    return out


def adapter_metaorder(path: str) -> list[dict[str, Any]]:
    """Metaorder/TWAP tape → records (phase, stade, sens, metaorder_id, top5, ofi_top5…)."""
    out: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    out.sort(key=lambda r: r.get("fill_time") or 0)
    return out


def adapter_bbo_synchro(path: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    """BBO synchronisé HL+Binance → records (hl_bid/ask/mid, bin_bid/ask/mid, desync_ms)."""
    out: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _load_provenance_bound_l4(path: str | None) -> dict[str, Any]:
    missing = "flux node/L4 (ORDER/MODIFY/CANCEL/PARTIAL/FILL) indisponible"
    if not path:
        return {"statut": BLOCKED, "events": [], "manque": missing}
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        return {"statut": BLOCKED, "events": [], "manque": "capture L4 absente ou non vérifiable"}

    events: list[dict[str, Any]] = []
    quarantined = 0
    required_provenance = ("provider", "capture_run_id", "native_event_id")
    try:
        with source.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    quarantined += 1
                    continue
                if not isinstance(raw, Mapping):
                    quarantined += 1
                    continue
                event = _l4.event_canonique(raw)
                provenance = raw.get("provenance")
                received_at_ms = (
                    provenance.get("received_at_ms")
                    if isinstance(provenance, Mapping) else None
                )
                if (
                    event is None
                    or not isinstance(provenance, Mapping)
                    or any(
                        not str(provenance.get(key) or "").strip()
                        for key in required_provenance
                    )
                    or isinstance(received_at_ms, bool)
                    or not isinstance(received_at_ms, (int, float))
                    or float(received_at_ms) < 0
                    or raw.get("paper_read_only") is not True
                    or raw.get("real_execution") is not False
                ):
                    quarantined += 1
                    continue
                events.append({
                    **event,
                    "provenance": dict(provenance),
                    "native_event_id": str(provenance["native_event_id"]),
                })
    except (OSError, UnicodeError):
        return {"statut": BLOCKED, "events": [], "manque": "capture L4 illisible ou non vérifiable"}

    coverage = {event_type: sum(event["type"] == event_type for event in events)
                for event_type in sorted(_l4.TYPES)}
    complete_cycle = all(coverage.get(event_type, 0) > 0 for event_type in _l4.TYPES)
    providers = {event["provenance"]["provider"] for event in events}
    coins = {event["coin"] for event in events}
    return {
        "statut": "READY_FOR_PAIRING" if complete_cycle else UNMEASURABLE,
        "events": events,
        "source": str(source),
        "quarantaine": quarantined,
        "coverage": coverage,
        "provenance_by_provider_coin": bool(providers and coins),
        "timestamps_present": bool(events) and all(
            isinstance(event.get("ts_ms"), (int, float))
            and isinstance(event["provenance"].get("received_at_ms"), (int, float))
            for event in events
        ),
        "real_l4_session": bool(events),
        "paired_public_fills": False,
        "paired_safe_l2": False,
        "point_in_time": False,
        "error_rates_present": False,
        "incremental_value": False,
        "paper_read_only": True,
        "real_execution": False,
        "manque": "appariement fills publics + L2 SAFE point-in-time requis",
    }


def adapter_l4(path: str | None = None) -> dict[str, Any]:
    """Load a strict provenance-bound capture; pairing remains a separate proof."""
    return _load_provenance_bound_l4(path)


# ════════════════════════ EVENT detectors ════════════════════════
def event_binance_shock(bbo: Sequence[Mapping[str, Any]], *, seuil_bps: float) -> list[int]:
    """Indices où |rendement Binance pas-à-pas| ≥ seuil (choc de prix Binance, meneur présumé)."""
    idx: list[int] = []
    for i in range(1, len(bbo)):
        b0, b1 = bbo[i - 1].get("bin_mid"), bbo[i].get("bin_mid")
        if isinstance(b0, (int, float)) and isinstance(b1, (int, float)) and b0 > 0:
            if abs((b1 / b0 - 1.0) * 1e4) >= seuil_bps:
                idx.append(i)
    return idx


def event_ofi_shock(feats: Sequence[Mapping[str, Any]], *, seuil: float) -> list[int]:
    return [i for i, f in enumerate(feats)
            if isinstance(f.get("ofi_l1"), (int, float)) and not math.isnan(f["ofi_l1"]) and abs(f["ofi_l1"]) >= seuil]


def event_microprice_displacement(feats: Sequence[Mapping[str, Any]], *, seuil_bps: float) -> list[int]:
    return [i for i, f in enumerate(feats)
            if isinstance(f.get("micro_tilt_bps"), (int, float)) and not math.isnan(f["micro_tilt_bps"])
            and abs(f["micro_tilt_bps"]) >= seuil_bps]


def event_queue_depletion(quotes: Sequence[Mapping[str, float]], *, drop_frac: float = 0.5) -> list[int]:
    """Indices où la taille bid OU ask chute d'au moins `drop_frac` vs le snapshot précédent (épuisement de file)."""
    idx: list[int] = []
    for i in range(1, len(quotes)):
        for cle in ("bid_size", "ask_size"):
            p, c = quotes[i - 1].get(cle), quotes[i].get(cle)
            if isinstance(p, (int, float)) and isinstance(c, (int, float)) and p > 0 and (p - c) / p >= drop_frac:
                idx.append(i)
                break
    return idx


def event_spread_transition(quotes: Sequence[Mapping[str, float]], *, mult: float = 2.0, fenetre: int = 20) -> list[int]:
    """Indices où le spread saute d'au moins `mult`× la médiane glissante (transition de régime de spread)."""
    def sp(q: Mapping[str, float]) -> float | None:
        b, a, m = q.get("bid"), q.get("ask"), q.get("mid")
        return (a - b) / m * 1e4 if (isinstance(b, (int, float)) and isinstance(a, (int, float)) and m) else None
    spreads = [sp(q) for q in quotes]
    idx: list[int] = []
    for i in range(fenetre, len(spreads)):
        cur = spreads[i]
        base = [x for x in spreads[i - fenetre:i] if x is not None]
        if cur is not None and base:
            med = sorted(base)[len(base) // 2]
            if med > 0 and cur >= mult * med:
                idx.append(i)
    return idx


def event_twap_slice(metaorder: Sequence[Mapping[str, Any]], *, stade: str = "FIRST_SLICE") -> list[int]:
    """Indices des tranches TWAP au stade demandé (FIRST_SLICE = début de métaordre = flux résiduel max)."""
    return [i for i, r in enumerate(metaorder) if r.get("stade") == stade]


def event_wallet_action(fills: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Événements wallet : direction seulement. L'ACTION (OPEN/ADD/REDUCE/CLOSE/FLIP) est UNMEASURABLE sans taille."""
    return [{"ts_ms": r.get("ts_ms"), "coin": r.get("coin"),
             "direction": r.get("side"), "action": UNMEASURABLE} for r in fills]


# ════════════════════════ STATE featurizers ════════════════════════
def _nombre_fini(x: Any) -> bool:
    return type(x) in (int, float) and math.isfinite(float(x))


def _bucket(x: float | None, bornes: Sequence[float]) -> str:
    if not _nombre_fini(x):
        return UNMEASURABLE
    for i, b in enumerate(bornes):
        if x < b:
            return "b%d" % i
    return "b%d" % len(bornes)


def _crowding_bucket(
    quote: Mapping[str, Any],
    metaorders: Sequence[Mapping[str, Any]] | None,
    *,
    window_ms: int = 60_000,
) -> str:
    """Return a causal crowding bucket, or ``UNMEASURABLE`` without a full tape."""

    if metaorders is None or type(window_ms) is not int or window_ms <= 0:
        return UNMEASURABLE
    quote_ts = quote.get("ts_ms")
    direction = quote.get("direction", quote.get("sens"))
    coin = quote.get("coin")
    quote_id = quote.get("metaorder_id", quote.get("event_id"))
    if (
        type(quote_ts) is not int or quote_ts <= 0
        or type(direction) is not int or direction not in (-1, 1)
        or not isinstance(coin, str) or not coin.strip()
        or not isinstance(quote_id, (str, int)) or isinstance(quote_id, bool)
        or not str(quote_id).strip()
    ):
        return UNMEASURABLE

    seen_ids: set[str] = set()
    concurrent = 0
    normalized_coin = coin.strip()
    for row in metaorders:
        if not isinstance(row, Mapping):
            return UNMEASURABLE
        row_id = row.get("metaorder_id", row.get("event_id"))
        if not isinstance(row_id, (str, int)) or isinstance(row_id, bool) or not str(row_id).strip():
            return UNMEASURABLE
        row_id_text = str(row_id).strip()
        if row_id_text in seen_ids:
            return UNMEASURABLE
        seen_ids.add(row_id_text)
        row_coin = row.get("coin")
        start = row.get("t0", row.get("start_ts_ms"))
        end = row.get("t1", row.get("end_ts_ms"))
        row_direction = row.get("sens", row.get("direction"))
        if (
            not isinstance(row_coin, str) or not row_coin.strip()
            or type(start) is not int or start <= 0
            or type(end) is not int or end < start
            or type(row_direction) is not int or row_direction not in (-1, 1)
        ):
            return UNMEASURABLE
        if row_id_text == str(quote_id).strip() or row_coin.strip() != normalized_coin:
            continue
        if row_direction == direction and start <= quote_ts <= end + window_ms:
            concurrent += 1
    return "b0" if concurrent == 0 else "b1" if concurrent == 1 else "b2+"


def state_buckets(
    quote: Mapping[str, Any], *, vol_bps: float | None = None,
    metaorders: Sequence[Mapping[str, Any]] | None = None,
    crowding_window_ms: int = 60_000,
) -> dict[str, str]:
    """Étiquette l'état marché d'un snapshot : spread / depth / imbalance / vol / coin / hour / (twap_stage, crowding)."""
    b, a, m = quote.get("bid"), quote.get("ask"), quote.get("mid")
    spread_bps = (
        (a - b) / m * 1e4
        if _nombre_fini(b) and _nombre_fini(a) and _nombre_fini(m)
        and m > 0 and a > b
        else None
    )
    bd, ad = quote.get("bid_depth"), quote.get("ask_depth")
    depth = (
        bd + ad
        if _nombre_fini(bd) and _nombre_fini(ad) and bd >= 0 and ad >= 0
        else None
    )
    imb = quote.get("imbalance")
    if not _nombre_fini(imb):
        bs, as_ = quote.get("bid_size"), quote.get("ask_size")
        imb = (
            (bs - as_) / (bs + as_)
            if _nombre_fini(bs) and _nombre_fini(as_) and bs >= 0 and as_ >= 0
            and (bs + as_) > 0
            else None
        )
    ts = quote.get("ts")
    if ts is None:
        ts = quote.get("ts_ms")
    hour = None
    if _nombre_fini(ts) and ts > 0:
        hour = int((float(ts) / (3600 if ts < 1e12 else 3_600_000)) % 24)
    return {
        "spread_bucket": _bucket(spread_bps, (0.5, 1.0, 2.0, 5.0)),
        "depth_bucket": _bucket(depth, (5e3, 5e4, 5e5, 5e6)),
        "imbalance_bucket": _bucket(imb, (-0.3, -0.1, 0.1, 0.3)),
        "vol_bucket": _bucket(vol_bps, (2.0, 5.0, 10.0, 20.0)),
        "coin": str(quote.get("coin", "?")),
        "hour_bucket": ("h%02d" % hour) if hour is not None else UNMEASURABLE,
        "twap_stage": str(quote.get("stade")) if quote.get("stade") else UNMEASURABLE,
        "crowding": _crowding_bucket(
            quote, metaorders, window_ms=crowding_window_ms,
        ),
    }


__all__ = [
    "UNMEASURABLE", "BLOCKED",
    "adapter_l2book", "adapter_wallet", "adapter_metaorder", "adapter_bbo_synchro", "adapter_l4",
    "event_binance_shock", "event_ofi_shock", "event_microprice_displacement", "event_queue_depletion",
    "event_spread_transition", "event_twap_slice", "event_wallet_action", "state_buckets",
]
