"""[DATA-049..061 / AUD-269] Adaptateur OKX v5 (perp SWAP) — OFFLINE : normalisation du schema PUBLIC
documente v5 (books/books5/bbo-tbt, trades, funding-rate, open-interest, mark/index, liquidation,
instruments) vers le schema canonique, sequencage via seqId/prevSeqId, reconnexion sur service-upgrade.
Le pull LIVE reste derriere une frontiere REQUIRES_NETWORK (jamais de faux succes). Schema conforme a la
doc publique OKX v5. stdlib pure, 0 reseau, 0 cle, 0 ordre reel."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from ._canon import (ClientLiveBase, DetecteurSequence, OFFLINE_READY, REQUIRES_NETWORK,
                     ligne, nbbo, niveaux, to_float)

VENUE = "okx"
ENDPOINTS = {
    "rest_base": "https://www.okx.com",
    "ws_public": "wss://ws.okx.com:8443/ws/v5/public",
    "channels": ("books", "books5", "bbo-tbt", "books-l2-tbt", "trades",
                 "funding-rate", "open-interest", "mark-price", "index-tickers",
                 "liquidation-orders", "instruments"),
}


def _instId(msg: Mapping):
    arg = msg.get("arg") or {}
    return arg.get("instId")


def normalize_books(msg: Mapping) -> dict:
    """books/books5 — action snapshot|update. data[0] porte seqId/prevSeqId (DATA-053) et checksum.
    OKX niveaux = [prix, taille, liqOrders, numOrders] : on ne garde que prix/taille."""
    data = (msg.get("data") or [{}])[0]
    return {"venue": VENUE, "symbole": _instId(msg), "action": msg.get("action"),
            "seqId": data.get("seqId"), "prevSeqId": data.get("prevSeqId"),
            "checksum": data.get("checksum"), "ts": data.get("ts"),
            "bids": niveaux(data.get("bids")), "asks": niveaux(data.get("asks"))}


def normalize_trade(t: Mapping) -> dict:
    """trades data : instId, tradeId, px, sz, side (buy/sell taker), ts."""
    return ligne(ts=t.get("ts"), venue=VENUE, symbole=t.get("instId"), type_="trade",
                 prix=t.get("px"), taille=t.get("sz"), side=t.get("side"))


def normalize_funding(f: Mapping) -> dict:
    """funding-rate data : instId, fundingRate, nextFundingTime, fundingTime."""
    return {"venue": VENUE, "symbole": f.get("instId"), "funding": to_float(f.get("fundingRate")),
            "ts": f.get("fundingTime"), "next_funding": f.get("nextFundingTime")}


def normalize_oi(o: Mapping) -> dict:
    """open-interest data : instId, oi (contrats), oiCcy (en devise), ts (AUD-345)."""
    return {"venue": VENUE, "symbole": o.get("instId"), "oi_contrats": to_float(o.get("oi")),
            "oi_devise": to_float(o.get("oiCcy")), "ts": o.get("ts")}


def normalize_mark(m: Mapping) -> dict:
    """mark-price data : instId, markPx, ts."""
    return {"venue": VENUE, "symbole": m.get("instId"), "mark": to_float(m.get("markPx")), "ts": m.get("ts")}


def normalize_liquidation(l: Mapping) -> dict:
    """liquidation-orders : details[] {side, sz, bkPx/px, ts}. side = sens de l'ordre force (AUD-346)."""
    d = l
    if l.get("details"):
        d = (l.get("details") or [{}])[0]
    return ligne(ts=d.get("ts"), venue=VENUE, symbole=l.get("instId") or d.get("instId"),
                 type_="liquidation", prix=d.get("bkPx") or d.get("px"), taille=d.get("sz"),
                 side=d.get("side"))


def normalize_instrument(i: Mapping) -> dict:
    """instruments data : instId, state (live/suspend/expired), ctVal, ctMult (DATA-059 / AUD-342)."""
    return {"venue": VENUE, "symbole": i.get("instId"), "etat": i.get("state"),
            "ct_val": to_float(i.get("ctVal")), "ct_mult": to_float(i.get("ctMult")),
            "type_contrat": i.get("ctType")}


def best_bid_ask(book: Mapping) -> dict:
    """bbo-tbt / books5 -> meilleur bid/ask (DATA-050/051)."""
    d = nbbo(book.get("bids"), book.get("asks"))
    d.update({"venue": VENUE, "symbole": book.get("symbole")})
    return d


def reconnect_sur_service_upgrade(evt: Mapping) -> dict:
    """DATA-060 : sur un evenement de type service-upgrade / connexion fermee, il FAUT re-souscrire et
    re-synchroniser (resync=True). Aucun autre evenement ne declenche de resync silencieux."""
    ev = str(evt.get("event") or evt.get("type") or "").lower()
    besoin = ("service-upgrade" in ev) or ("close" in ev) or (str(evt.get("code")) in ("60004", "60006"))
    return {"resync": bool(besoin), "re_souscrire": bool(besoin), "event": ev or None}


def mapping_silver() -> dict:
    return {"ts": "ts", "symbole": "instId", "prix": "px", "taille": "sz", "side": "side"}


def replay(msgs: Sequence[Mapping]) -> list:
    return [normalize_trade(m) for m in msgs]


def capacites() -> dict:
    return {"venue": VENUE, "flux": ("book", "trades", "funding", "oi", "liquidations"),
            "adaptateur": OFFLINE_READY, "pull_live": REQUIRES_NETWORK}


def venue_capability_safety_receipt(result: object) -> dict[str, object]:
    """Validate OKX public capabilities without creating a live client."""
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
        "verdict": "OKX_CAPABILITY_SAFE" if valid else "OKX_CAPABILITY_UNSAFE",
        "paper_read_only": True,
        "real_execution": False,
        "network_execution": False,
        "execution_surface": "READ_ONLY_ONLY",
        "fail_closed": not valid,
    }


def appliquer_flux_books(messages: Sequence[Mapping]) -> dict:
    """Applique snapshot->update via seqId/prevSeqId. prevSeqId != dernier seqId -> resync (DATA-053)."""
    det = DetecteurSequence()
    resyncs = []
    applique = 0
    for m in messages:
        b = normalize_books(m)
        if b["action"] == "snapshot":
            det.snapshot(b["seqId"])
            applique += 1
        else:
            r = det.delta(b["seqId"], b["prevSeqId"])
            if r["resync"]:
                resyncs.append({"seqId": b["seqId"], "raison": r["raison"]})
            else:
                applique += 1
    return {"applique": applique, "resyncs": resyncs, "synchronise": det.synchronise}


class LiveClientOKX(ClientLiveBase):
    statut = REQUIRES_NETWORK

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def souscrire_books(self, instId, canal="books"):
        self._refuser("%s %s" % (canal, instId))

    def souscrire_trades(self, instId):
        self._refuser("trades %s" % instId)

    def souscrire_orderbook(self, instId, profondeur=50):
        self._refuser("orderbook %s %s" % (instId, profondeur))


def _okx_truth_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        "mutation": False,
        "closure_allowed": False,
        **values,
    }


def _okx_truth_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _okx_truth_finite(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _okx_truth_event_valid(event: Mapping[str, Any]) -> bool:
    required = ("native_id", "source", "sequence", "exchange_ts_ms", "received_ts_ms", "payload_hash", "payload")
    return (
        isinstance(event, Mapping)
        and all(event.get(field) not in (None, "") for field in required)
        and isinstance(event["native_id"], str)
        and isinstance(event["source"], str)
        and _okx_truth_int(event["sequence"])
        and event["sequence"] > 0
        and _okx_truth_int(event["exchange_ts_ms"])
        and _okx_truth_int(event["received_ts_ms"])
        and isinstance(event["payload_hash"], str)
        and len(event["payload_hash"]) == 64
        and all(character in "0123456789abcdef" for character in event["payload_hash"])
        and isinstance(event["payload"], Mapping)
    )


def okx_truth_fixture_receipt(*, events: Sequence[Mapping[str, Any]], causal_outputs: Any) -> dict[str, Any]:
    valid = bool(events) and all(_okx_truth_event_valid(event) for event in events) and causal_outputs == 1
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_CAUSAL_FIXTURE" if valid else "OKX_TRUTH_FIXTURE_INVALID", fail_closed=not valid)


def okx_truth_required_field_receipt(event: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(event, Mapping) and isinstance(field, str) and bool(field) and event.get(field) not in (None, "")
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_FIELD_PRESENT" if valid else "OKX_TRUTH_FIELD_MISSING", fail_closed=not valid)


def okx_truth_field_type_receipt(event: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    value = event.get(field) if isinstance(event, Mapping) else None
    valid = isinstance(event, Mapping) and isinstance(field, str) and isinstance(expected_type, type) and isinstance(value, expected_type) and not (expected_type is int and isinstance(value, bool))
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_FIELD_TYPE_VALID" if valid else "OKX_TRUTH_FIELD_TYPE_INVALID", fail_closed=not valid)


def okx_truth_finite_receipt(*, quantity: Any) -> dict[str, Any]:
    valid = _okx_truth_finite(quantity) and float(quantity) > 0
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_QUANTITY_FINITE" if valid else "OKX_TRUTH_QUANTITY_INVALID", fail_closed=not valid)


def okx_truth_lateness_receipt(*, exchange_ts_ms: Any, received_ts_ms: Any, max_delay_ms: Any) -> dict[str, Any]:
    valid = all(_okx_truth_int(value) for value in (exchange_ts_ms, received_ts_ms, max_delay_ms)) and 0 <= received_ts_ms - exchange_ts_ms <= max_delay_ms
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_TIMESTAMP_FRESH" if valid else "OKX_TRUTH_TIMESTAMP_LATE", fail_closed=not valid)


def okx_truth_future_receipt(*, event_ts_ms: Any, decision_cutoff_ms: Any) -> dict[str, Any]:
    valid = _okx_truth_int(event_ts_ms) and _okx_truth_int(decision_cutoff_ms) and event_ts_ms <= decision_cutoff_ms
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_NO_LOOKAHEAD" if valid else "OKX_TRUTH_FUTURE_EVENT", fail_closed=not valid)


def okx_truth_order_receipt(*, sequences: Sequence[Any]) -> dict[str, Any]:
    values = list(sequences)
    valid = bool(values) and all(_okx_truth_int(value) for value in values) and values == sorted(values) and len(values) == len(set(values))
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_SEQUENCE_ORDERED" if valid else "OKX_TRUTH_SEQUENCE_REVERSED", fail_closed=not valid)


def okx_truth_duplicate_receipt(*, native_ids: Sequence[Any]) -> dict[str, Any]:
    values = list(native_ids)
    valid = bool(values) and all(isinstance(value, str) and value.strip() for value in values) and len(values) == len(set(values))
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_IDENTITIES_UNIQUE" if valid else "OKX_TRUTH_DUPLICATE_IDENTITY", fail_closed=not valid)


def okx_truth_conflict_receipt(*, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_id: dict[str, str] = {}
    valid = bool(events)
    for event in events:
        if not _okx_truth_event_valid(event):
            valid = False
            break
        native_id = str(event["native_id"])
        digest = str(event["payload_hash"])
        if native_id in by_id and by_id[native_id] != digest:
            valid = False
            break
        by_id[native_id] = digest
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_CONFLICT_FREE" if valid else "OKX_TRUTH_PAYLOAD_CONFLICT", quarantine=not valid, fail_closed=not valid)


def okx_truth_overlap_receipt(*, first: Sequence[Mapping[str, Any]], second: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = okx_truth_conflict_receipt(events=[*first, *second])
    valid = result["status"] == "PROVEN"
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_OVERLAP_DEDUPLICABLE" if valid else "OKX_TRUTH_OVERLAP_CONFLICT", deduplicated=valid, fail_closed=not valid)


def okx_truth_gap_receipt(*, sequences: Sequence[Any]) -> dict[str, Any]:
    values = list(sequences)
    valid = bool(values) and all(_okx_truth_int(value) for value in values) and all(right == left + 1 for left, right in zip(values, values[1:]))
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_SEQUENCE_CONTIGUOUS" if valid else "OKX_TRUTH_SEQUENCE_GAP", fail_closed=not valid)


def okx_truth_clock_receipt(*, exchange_ts_ms: Any, received_ts_ms: Any, now_ms: Any) -> dict[str, Any]:
    valid = all(_okx_truth_int(value) for value in (exchange_ts_ms, received_ts_ms, now_ms)) and exchange_ts_ms <= received_ts_ms <= now_ms
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_CLOCK_CAUSAL" if valid else "OKX_TRUTH_CLOCK_INCONSISTENT", fail_closed=not valid)


def okx_truth_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _okx_truth_int(attempts) and _okx_truth_int(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_RETRY_EXACTLY_ONCE" if valid else "OKX_TRUTH_RETRY_UNSAFE", fail_closed=not valid)


def okx_truth_checkpoint_receipt(*, checkpoint: Mapping[str, Any], required_fields: Sequence[str]) -> dict[str, Any]:
    valid = isinstance(checkpoint, Mapping) and bool(required_fields) and checkpoint.get("saved") is True and all(isinstance(field, str) and checkpoint.get(field) not in (None, "") for field in required_fields)
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_CHECKPOINT_COMPLETE" if valid else "OKX_TRUTH_CHECKPOINT_PARTIAL", fail_closed=not valid)


def okx_truth_manifest_receipt(*, expected_sha: Any, actual_sha: Any) -> dict[str, Any]:
    valid = isinstance(expected_sha, str) and isinstance(actual_sha, str) and len(expected_sha) == 64 and len(actual_sha) == 64 and expected_sha == actual_sha and all(character in "0123456789abcdef" for character in expected_sha)
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_MANIFEST_MATCH" if valid else "OKX_TRUTH_MANIFEST_CONFLICT", fail_closed=not valid)


def okx_truth_asset_receipt(*, available: bool, complete: bool) -> dict[str, Any]:
    valid = available is True and complete is True
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_ASSET_COMPLETE" if valid else "OKX_TRUTH_ASSET_INCOMPLETE", fail_closed=not valid)


def okx_truth_capacity_receipt(*, requested_quantity: Any, visible_depth: Any) -> dict[str, Any]:
    valid = _okx_truth_finite(requested_quantity) and _okx_truth_finite(visible_depth) and 0 < float(requested_quantity) <= float(visible_depth)
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_CAPACITY_SUFFICIENT" if valid else "OKX_TRUTH_CAPACITY_MISSING", fail_closed=not valid)


def okx_truth_position_receipt(*, fees: Any, margin: Any, mark: Any) -> dict[str, Any]:
    valid = all(_okx_truth_finite(value) for value in (fees, margin, mark)) and float(fees) >= 0 and float(margin) >= 0 and float(mark) > 0
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_POSITION_COSTS_COMPLETE" if valid else "OKX_TRUTH_POSITION_COSTS_MISSING", fail_closed=not valid)


def okx_truth_scope_receipt(*, family: Any, execution_requested: bool) -> dict[str, Any]:
    valid = family == "Copy-Vault" and execution_requested is False
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_SCOPE_READ_ONLY" if valid else "OKX_TRUTH_SCOPE_OR_EXECUTION_FORBIDDEN", fail_closed=not valid)


def okx_truth_done_receipt(*, status: Any, coverage_status: Any, proof_ids: Sequence[Any], replay_verified: bool) -> dict[str, Any]:
    valid = status == "PROVEN" and coverage_status == "PROVEN" and bool(proof_ids) and replay_verified is True
    return _okx_truth_base("PROVEN" if valid else "REJECTED", verdict="OKX_TRUTH_DONE_COVERED" if valid else "OKX_TRUTH_DONE_UNPROVEN", fail_closed=not valid)
