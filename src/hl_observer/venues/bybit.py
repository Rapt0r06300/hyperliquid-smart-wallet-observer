"""[DATA-036..048 / AUD-268] Adaptateur Bybit v5 (perp lineaire) — OFFLINE : normalisation du schema
PUBLIC documente v5 (orderbook.{1,50,200,500}, publicTrade, tickers, funding, open-interest,
liquidation) vers le schema canonique, snapshot/delta via u/seq + cts (matching-engine ts), NBBO.
Le pull LIVE (REST/WS) reste derriere une frontiere REQUIRES_NETWORK (jamais de faux succes).
Schema conforme a la doc publique Bybit v5 ; validation live = etape reseau (golden packets AUD-371).
stdlib pure, 0 reseau, 0 cle, 0 ordre reel."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from ._canon import (ClientLiveBase, DetecteurSequence, OFFLINE_READY, REQUIRES_NETWORK,
                     ligne, nbbo, niveaux, to_float)

VENUE = "bybit"
ENDPOINTS = {
    "rest_base": "https://api.bybit.com",
    "ws_public_linear": "wss://stream.bybit.com/v5/public/linear",
    "orderbook_depths": (1, 50, 200, 500),           # DATA-037/038/039/040
    "topics": ("orderbook.{depth}.{sym}", "publicTrade.{sym}", "tickers.{sym}",
               "liquidation.{sym}", "allLiquidation.{sym}"),
    "rest_funding": "/v5/market/funding/history",     # DATA-043
    "rest_oi": "/v5/market/open-interest",             # DATA-044
}


def normalize_orderbook(msg: Mapping) -> dict:
    """orderbook.{depth}.{sym} — type snapshot|delta. Porte data.u (updateId), data.seq et cts
    (matching-engine ts, DATA-046). taille 0 dans un delta = suppression de niveau (DATA-047)."""
    data = msg.get("data") or {}
    return {"venue": VENUE, "symbole": data.get("s"), "type_maj": msg.get("type"),
            "u": data.get("u"), "seq": data.get("seq"), "cts": msg.get("cts"), "ts": msg.get("ts"),
            "bids": niveaux(data.get("b")), "asks": niveaux(data.get("a"))}


def normalize_trade(t: Mapping) -> dict:
    """publicTrade : T=ts(ms), s=symbole, S=Buy/Sell (agressor), v=taille, p=prix."""
    return ligne(ts=t.get("T"), venue=VENUE, symbole=t.get("s"), type_="trade",
                 prix=t.get("p"), taille=t.get("v"), side=t.get("S"))


def normalize_liquidation(l: Mapping) -> dict:
    """liquidation.{sym} : S/side = sens de l'ordre de liquidation (agressor). p/price, v/size, T (AUD-346)."""
    return ligne(ts=l.get("T") or l.get("updatedTime"), venue=VENUE,
                 symbole=l.get("s") or l.get("symbol"), type_="liquidation",
                 prix=l.get("p") or l.get("price"), taille=l.get("v") or l.get("size"),
                 side=l.get("S") or l.get("side"))


def normalize_ticker(tk: Mapping) -> dict:
    """tickers.{sym} : last/mark/index/funding/oi (DATA-042/043/044). oi en CONTRATS (AUD-345)."""
    return {"venue": VENUE, "symbole": tk.get("symbol"),
            "last": to_float(tk.get("lastPrice")), "mark": to_float(tk.get("markPrice")),
            "index": to_float(tk.get("indexPrice")), "funding": to_float(tk.get("fundingRate")),
            "next_funding": tk.get("nextFundingTime"),
            "oi_contrats": to_float(tk.get("openInterest")),
            "oi_valeur": to_float(tk.get("openInterestValue"))}


def normalize_funding(row: Mapping) -> dict:
    """/v5/market/funding/history : fundingRate, fundingRateTimestamp."""
    return {"venue": VENUE, "symbole": row.get("symbol"), "funding": to_float(row.get("fundingRate")),
            "ts": row.get("fundingRateTimestamp")}


def normalize_oi(row: Mapping) -> dict:
    """/v5/market/open-interest : openInterest (contrats), timestamp."""
    return {"venue": VENUE, "symbole": row.get("symbol"),
            "oi_contrats": to_float(row.get("openInterest")), "ts": row.get("timestamp")}


def best_bid_ask(book: Mapping) -> dict:
    """Meilleur bid/ask depuis un book normalise (DATA-037 L1 / DATA-048 NBBO)."""
    d = nbbo(book.get("bids"), book.get("asks"))
    d.update({"venue": VENUE, "symbole": book.get("symbole")})
    return d


def mapping_silver() -> dict:
    """Mapping {canonique: champ_source_trade} pour medallion.to_silver (flux trades)."""
    return {"ts": "T", "symbole": "s", "prix": "p", "taille": "v", "side": "S"}


def replay(msgs: Sequence[Mapping]) -> list:
    """Rejoue une capture brute de trades -> lignes canoniques (offline, deterministe)."""
    return [normalize_trade(m) for m in msgs]


def capacites() -> dict:
    return {"venue": VENUE, "flux": ("book", "trades", "funding", "oi", "liquidations"),
            "adaptateur": OFFLINE_READY, "pull_live": REQUIRES_NETWORK}


def venue_capability_safety_receipt(result: object) -> dict[str, object]:
    """Validate Bybit public capabilities while keeping network access explicit."""
    required_flux = {"book", "trades", "funding", "oi", "liquidations"}
    flux = result.get("flux") if isinstance(result, Mapping) else None
    valid = (
        isinstance(result, Mapping)
        and isinstance(flux, (tuple, list, set, frozenset))
        and result.get("venue") == VENUE
        and required_flux.issubset(set(flux))
        and result.get("adaptateur") == OFFLINE_READY
        and result.get("pull_live") == REQUIRES_NETWORK
        and "orders" not in set(flux)
    )
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "verdict": "BYBIT_CAPABILITY_SAFE" if valid else "BYBIT_CAPABILITY_UNSAFE",
        "paper_read_only": True,
        "real_execution": False,
        "network_execution": False,
        "execution_surface": "READ_ONLY_ONLY",
        "fail_closed": not valid,
    }


class LiveClientBybit(ClientLiveBase):
    """Live-gate Bybit : chaque souscription/pull LEVE (jamais de faux succes)."""

    statut = REQUIRES_NETWORK

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def souscrire_trades(self, symbole: str) -> None:
        """Keep the live boundary explicit: paper mode never opens a stream."""
        self._refuser(f"trades:{symbole}")

    def souscrire_orderbook(self, symbole: str, profondeur: int = 50) -> None:
        """Keep the live boundary explicit: no local/network side effect is allowed."""
        self._refuser(f"orderbook:{symbole}:{profondeur}")


def _bybit_base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", "mutation": False, "closure_allowed": False, **values}


def _bybit_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bybit_finite(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _bybit_event_valid(event: Mapping[str, Any]) -> bool:
    required = ("native_id", "source", "sequence", "exchange_ts_ms", "received_ts_ms", "payload_hash", "payload")
    return isinstance(event, Mapping) and all(event.get(field) not in (None, "") for field in required) and isinstance(event["native_id"], str) and isinstance(event["source"], str) and _bybit_int(event["sequence"]) and event["sequence"] > 0 and _bybit_int(event["exchange_ts_ms"]) and _bybit_int(event["received_ts_ms"]) and isinstance(event["payload_hash"], str) and len(event["payload_hash"]) == 64 and all(character in "0123456789abcdef" for character in event["payload_hash"]) and isinstance(event["payload"], Mapping)


def bybit_truth_fixture_receipt(*, events: Sequence[Mapping[str, Any]], causal_outputs: Any) -> dict[str, Any]:
    valid = bool(events) and all(_bybit_event_valid(event) for event in events) and causal_outputs == 1
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_CAUSAL_FIXTURE" if valid else "BYBIT_TRUTH_FIXTURE_INVALID", fail_closed=not valid)


def bybit_truth_required_field_receipt(event: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(event, Mapping) and isinstance(field, str) and bool(field) and event.get(field) not in (None, "")
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_FIELD_PRESENT" if valid else "BYBIT_TRUTH_FIELD_MISSING", fail_closed=not valid)


def bybit_truth_field_type_receipt(event: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    value = event.get(field) if isinstance(event, Mapping) else None
    valid = isinstance(event, Mapping) and isinstance(field, str) and isinstance(expected_type, type) and isinstance(value, expected_type) and not (expected_type is int and isinstance(value, bool))
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_FIELD_TYPE_VALID" if valid else "BYBIT_TRUTH_FIELD_TYPE_INVALID", fail_closed=not valid)


def bybit_truth_finite_receipt(*, quantity: Any) -> dict[str, Any]:
    valid = _bybit_finite(quantity) and float(quantity) > 0
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_QUANTITY_FINITE" if valid else "BYBIT_TRUTH_QUANTITY_INVALID", fail_closed=not valid)


def bybit_truth_lateness_receipt(*, exchange_ts_ms: Any, received_ts_ms: Any, max_delay_ms: Any) -> dict[str, Any]:
    valid = all(_bybit_int(value) for value in (exchange_ts_ms, received_ts_ms, max_delay_ms)) and 0 <= received_ts_ms - exchange_ts_ms <= max_delay_ms
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_TIMESTAMP_FRESH" if valid else "BYBIT_TRUTH_TIMESTAMP_LATE", fail_closed=not valid)


def bybit_truth_future_receipt(*, event_ts_ms: Any, decision_cutoff_ms: Any) -> dict[str, Any]:
    valid = _bybit_int(event_ts_ms) and _bybit_int(decision_cutoff_ms) and event_ts_ms <= decision_cutoff_ms
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_NO_LOOKAHEAD" if valid else "BYBIT_TRUTH_FUTURE_EVENT", fail_closed=not valid)


def bybit_truth_order_receipt(*, sequences: Sequence[Any]) -> dict[str, Any]:
    values = list(sequences)
    valid = bool(values) and all(_bybit_int(value) for value in values) and values == sorted(values) and len(values) == len(set(values))
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_SEQUENCE_ORDERED" if valid else "BYBIT_TRUTH_SEQUENCE_REVERSED", fail_closed=not valid)


def bybit_truth_duplicate_receipt(*, native_ids: Sequence[Any]) -> dict[str, Any]:
    values = list(native_ids)
    valid = bool(values) and all(isinstance(value, str) and value.strip() for value in values) and len(values) == len(set(values))
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_IDENTITIES_UNIQUE" if valid else "BYBIT_TRUTH_DUPLICATE_IDENTITY", fail_closed=not valid)


def bybit_truth_conflict_receipt(*, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_id: dict[str, str] = {}
    valid = bool(events)
    for event in events:
        if not _bybit_event_valid(event):
            valid = False
            break
        native_id = str(event["native_id"])
        digest = str(event["payload_hash"])
        if native_id in by_id and by_id[native_id] != digest:
            valid = False
            break
        by_id[native_id] = digest
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_CONFLICT_FREE" if valid else "BYBIT_TRUTH_PAYLOAD_CONFLICT", quarantine=not valid, fail_closed=not valid)


def bybit_truth_overlap_receipt(*, first: Sequence[Mapping[str, Any]], second: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = bybit_truth_conflict_receipt(events=[*first, *second])
    valid = result["status"] == "PROVEN"
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_OVERLAP_DEDUPLICABLE" if valid else "BYBIT_TRUTH_OVERLAP_CONFLICT", deduplicated=valid, fail_closed=not valid)


def bybit_truth_gap_receipt(*, sequences: Sequence[Any]) -> dict[str, Any]:
    values = list(sequences)
    valid = bool(values) and all(_bybit_int(value) for value in values) and all(right == left + 1 for left, right in zip(values, values[1:]))
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_SEQUENCE_CONTIGUOUS" if valid else "BYBIT_TRUTH_SEQUENCE_GAP", fail_closed=not valid)


def bybit_truth_clock_receipt(*, exchange_ts_ms: Any, received_ts_ms: Any, now_ms: Any) -> dict[str, Any]:
    valid = all(_bybit_int(value) for value in (exchange_ts_ms, received_ts_ms, now_ms)) and exchange_ts_ms <= received_ts_ms <= now_ms
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_CLOCK_CAUSAL" if valid else "BYBIT_TRUTH_CLOCK_INCONSISTENT", fail_closed=not valid)


def bybit_truth_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _bybit_int(attempts) and _bybit_int(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_RETRY_EXACTLY_ONCE" if valid else "BYBIT_TRUTH_RETRY_UNSAFE", fail_closed=not valid)


def bybit_truth_checkpoint_receipt(*, checkpoint: Mapping[str, Any], required_fields: Sequence[str]) -> dict[str, Any]:
    valid = isinstance(checkpoint, Mapping) and bool(required_fields) and checkpoint.get("saved") is True and all(isinstance(field, str) and checkpoint.get(field) not in (None, "") for field in required_fields)
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_CHECKPOINT_COMPLETE" if valid else "BYBIT_TRUTH_CHECKPOINT_PARTIAL", fail_closed=not valid)


def bybit_truth_manifest_receipt(*, expected_sha: Any, actual_sha: Any) -> dict[str, Any]:
    valid = isinstance(expected_sha, str) and isinstance(actual_sha, str) and len(expected_sha) == 64 and len(actual_sha) == 64 and expected_sha == actual_sha and all(character in "0123456789abcdef" for character in expected_sha)
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_MANIFEST_MATCH" if valid else "BYBIT_TRUTH_MANIFEST_CONFLICT", fail_closed=not valid)


def bybit_truth_asset_receipt(*, available: bool, complete: bool) -> dict[str, Any]:
    valid = available is True and complete is True
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_ASSET_COMPLETE" if valid else "BYBIT_TRUTH_ASSET_INCOMPLETE", fail_closed=not valid)


def bybit_truth_capacity_receipt(*, requested_quantity: Any, visible_depth: Any) -> dict[str, Any]:
    valid = _bybit_finite(requested_quantity) and _bybit_finite(visible_depth) and 0 < float(requested_quantity) <= float(visible_depth)
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_CAPACITY_SUFFICIENT" if valid else "BYBIT_TRUTH_CAPACITY_MISSING", fail_closed=not valid)


def bybit_truth_position_receipt(*, fees: Any, margin: Any, mark: Any) -> dict[str, Any]:
    valid = all(_bybit_finite(value) for value in (fees, margin, mark)) and float(fees) >= 0 and float(margin) >= 0 and float(mark) > 0
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_POSITION_COSTS_COMPLETE" if valid else "BYBIT_TRUTH_POSITION_COSTS_MISSING", fail_closed=not valid)


def bybit_truth_scope_receipt(*, family: Any, execution_requested: bool) -> dict[str, Any]:
    valid = family == "Copy-Vault" and execution_requested is False
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_SCOPE_READ_ONLY" if valid else "BYBIT_TRUTH_SCOPE_OR_EXECUTION_FORBIDDEN", fail_closed=not valid)


def bybit_truth_done_receipt(*, status: Any, coverage_status: Any, proof_ids: Sequence[Any], replay_verified: bool) -> dict[str, Any]:
    valid = status == "PROVEN" and coverage_status == "PROVEN" and bool(proof_ids) and replay_verified is True
    return _bybit_base("PROVEN" if valid else "REJECTED", verdict="BYBIT_TRUTH_DONE_COVERED" if valid else "BYBIT_TRUTH_DONE_UNPROVEN", fail_closed=not valid)

    def souscrire_orderbook(self, symbole, depth=50):
        self._refuser("orderbook.%s.%s" % (depth, symbole))

    def souscrire_trades(self, symbole):
        self._refuser("publicTrade.%s" % symbole)

    def rest_open_interest(self, symbole):
        self._refuser("open-interest %s" % symbole)


def appliquer_flux_orderbook(messages: Sequence[Mapping]) -> dict:
    """Applique une sequence snapshot->deltas via DetecteurSequence : renvoie l'etat + les resync
    detectes. Un delta orphelin ou un trou d'updateId force un resync (n'est jamais masque)."""
    det = DetecteurSequence()
    resyncs = []
    applique = 0
    for m in messages:
        b = normalize_orderbook(m)
        if b["type_maj"] == "snapshot":
            det.snapshot(b["u"])
            applique += 1
        else:
            r = det.delta(b["u"])
            if r["resync"]:
                resyncs.append({"u": b["u"], "raison": r["raison"]})
            else:
                applique += 1
    return {"applique": applique, "resyncs": resyncs, "synchronise": det.synchronise}
