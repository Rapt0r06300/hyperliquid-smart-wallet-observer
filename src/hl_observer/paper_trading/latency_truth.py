"""P1B — VÉRITÉ de latence par exécution causale différée ; le coefficient scalaire n'est qu'un STRESS.

`latency_cost_bps_per_sec × age` ne doit plus être la vérité économique finale. La vérité :

  décision à T → exécution contre le PREMIER carnet causal observé à **T + délai** (délai MESURÉ si on
  l'a, sinon ASSUMED explicitement) ; le coût de latence AUTORITAIRE est le déplacement RÉEL du mid
  entre la décision et ce carnet d'exécution (réutilise `cost_components.latency_bps`).

Deny-by-default : aucun carnet causal à T+délai ⇒ `NO_FILL` ; premier carnet trop tardif (au-delà de la
tolérance) ⇒ `STALE_BOOK` ; un mid manquant ⇒ `UNMEASURABLE`. Le modèle scalaire reste disponible mais
**étiqueté STRESS_ONLY** : il ne peut jamais être promu comme PnL autoritaire. Le MÊME chemin sert en
replay et en forward (sélection déterministe du premier carnet causal). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.simulation.cost_components import latency_bps as _latency_bps

SCHEMA_VERSION = "hypersmart.latency_truth.v1"

MEASURED = "MEASURED"
ASSUMED = "ASSUMED"
NO_FILL = "NO_FILL"
STALE_BOOK = "STALE_BOOK"
UNMEASURABLE = "UNMEASURABLE"
STRESS_ONLY = "STRESS_ONLY"


def _num(x: object) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _mid(book: Mapping[str, Any]) -> float | None:
    m = _num(book.get("mid"))
    if m is not None and m > 0:
        return m
    bid, ask = _num(book.get("bid")), _num(book.get("ask"))
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return None


def selectionner_carnet_causal(
    books: Sequence[Mapping[str, Any]], *, decision_ts_ms: float, delay_ms: float, tol_ms: float | None = None
) -> dict[str, Any]:
    """PREMIER carnet observé à ou après `decision_ts_ms + delay_ms`. Déterministe (replay = forward).

    `NO_FILL` si aucun carnet causal ; `STALE_BOOK` si le premier dépasse la tolérance après la cible."""
    d = _num(decision_ts_ms)
    dl = _num(delay_ms)
    if d is None or dl is None:
        return {"statut": UNMEASURABLE, "raison": "decision_ts ou delay manquant"}
    cible = d + dl
    eligibles = sorted(
        (b for b in books if _num(b.get("observed_at_ms")) is not None and _num(b.get("observed_at_ms")) >= cible),
        key=lambda b: _num(b.get("observed_at_ms")),
    )
    if not eligibles:
        return {"statut": NO_FILL, "cible_ms": cible}
    premier = eligibles[0]
    obs = _num(premier.get("observed_at_ms"))
    if tol_ms is not None and (obs - cible) > float(tol_ms):
        return {"statut": STALE_BOOK, "cible_ms": cible, "observed_at_ms": obs, "retard_ms": round(obs - cible, 6)}
    return {"statut": "OK", "carnet": premier, "cible_ms": cible, "observed_at_ms": obs,
            "latency_ms_realise": round(obs - d, 6)}


def latence_scalaire_stress_bps(delay_sec: float, *, coeff_bps_per_sec: float = 0.20, cap_bps: float = 15.0) -> dict[str, Any]:
    """Le modèle scalaire, EXPLICITEMENT `STRESS_ONLY` — jamais un PnL autoritaire."""
    ds = _num(delay_sec)
    if ds is None or ds < 0:
        return {"statut": UNMEASURABLE, "usage": STRESS_ONLY}
    val = min(float(cap_bps), ds * float(coeff_bps_per_sec))
    return {"statut": STRESS_ONLY, "latency_stress_bps": round(val, 6), "usage": STRESS_ONLY,
            "note": "modele de stress, jamais la verite economique finale"}


def verite_latence(
    books: Sequence[Mapping[str, Any]],
    *,
    decision_ts_ms: float,
    mid_decision: float,
    side: object,
    delay_ms: float,
    delay_source: str = ASSUMED,
    tol_ms: float | None = None,
    coeff_stress_bps_per_sec: float = 0.20,
    cap_stress_bps: float = 15.0,
) -> dict[str, Any]:
    """Coût de latence AUTORITAIRE via exécution causale différée + le scalaire en STRESS (jamais promu)."""
    sel = selectionner_carnet_causal(books, decision_ts_ms=decision_ts_ms, delay_ms=delay_ms, tol_ms=tol_ms)
    scalaire = latence_scalaire_stress_bps(
        (_num(delay_ms) or 0.0) / 1000.0, coeff_bps_per_sec=coeff_stress_bps_per_sec, cap_bps=cap_stress_bps)

    base = {"schema_version": SCHEMA_VERSION, "delay_source": (ASSUMED if delay_source != MEASURED else MEASURED),
            "stress_scalaire": scalaire, "real_execution": False}

    if sel["statut"] != "OK":
        base.update({"statut": sel["statut"], "latency_bps_authoritative": None,
                     "execution_mid": None, "latency_ms_realise": sel.get("retard_ms")})
        return base

    carnet = sel["carnet"]
    mid_exec = _mid(carnet)
    lat = _latency_bps(mid_decision, mid_exec, side) if mid_exec is not None else None
    base.update({
        "statut": (MEASURED if lat is not None else UNMEASURABLE),
        "latency_bps_authoritative": lat,          # déplacement RÉEL du mid décision→exécution
        "execution_mid": mid_exec,
        "latency_ms_realise": sel["latency_ms_realise"],
        "execution_observed_at_ms": sel["observed_at_ms"],
    })
    return base


def _latency_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _latency_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _latency_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def latency_truth_safety_receipt(result: Mapping[str, Any]) -> dict[str, Any]:
    valid = (
        isinstance(result, Mapping)
        and result.get("schema_version") == SCHEMA_VERSION
        and result.get("statut") in {MEASURED, ASSUMED, NO_FILL, STALE_BOOK, UNMEASURABLE}
        and result.get("real_execution") is False
    )
    return _latency_base(
        "PROVEN" if valid else "REJECTED",
        verdict="LATENCY_TRUTH_SAFE" if valid else "LATENCY_TRUTH_UNSAFE",
        fail_closed=not valid,
    )


def latency_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_FIELD_PRESENT" if valid else "LATENCY_FIELD_MISSING", field=field, fail_closed=not valid)


def latency_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_FIELD_NON_NULL" if valid else "LATENCY_FIELD_NULL", field=field, fail_closed=not valid)


def latency_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_FIELD_TYPE_VALID" if valid else "LATENCY_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def latency_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _latency_finite(value)
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_VALUE_FINITE" if valid else "LATENCY_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def latency_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _latency_integer(event_ts_ms) and _latency_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_EVENT_WITHIN_CUTOFF" if valid else "LATENCY_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def latency_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _latency_integer(event_ts_ms) and _latency_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_EVENT_AGE_VALID" if valid else "LATENCY_EVENT_TOO_OLD", fail_closed=not valid)


def latency_duplicate_receipt(*, event_ids: list[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_EVENTS_UNIQUE" if valid else "LATENCY_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def latency_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _latency_integer(attempts) and _latency_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_RETRY_BOUNDED" if valid else "LATENCY_RETRY_UNSAFE", fail_closed=not valid)


def latency_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_REPLAY_DETERMINISTIC" if valid else "LATENCY_REPLAY_DIVERGED", fail_closed=not valid)


def latency_depth_receipt(*, bids: Sequence[Sequence[Any]], asks: Sequence[Sequence[Any]], is_bbo: bool) -> dict[str, Any]:
    valid = bool(bids) and bool(asks) and is_bbo is False and all(len(level) >= 2 and _latency_finite(level[0]) and _latency_finite(level[1]) and float(level[1]) > 0 for level in (*bids, *asks))
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_FULL_DEPTH" if valid else "LATENCY_BBO_OR_INVALID_DEPTH", fail_closed=not valid)


def latency_crossed_book_receipt(*, best_bid: Any, best_ask: Any) -> dict[str, Any]:
    valid = _latency_finite(best_bid) and _latency_finite(best_ask) and float(best_ask) >= float(best_bid) > 0
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_BOOK_NOT_CROSSED" if valid else "LATENCY_BOOK_CROSSED_OR_INVALID", fail_closed=not valid)


def latency_negative_size_receipt(*, sizes: Sequence[Any]) -> dict[str, Any]:
    valid = bool(sizes) and all(_latency_finite(size) and float(size) > 0 for size in sizes)
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_SIZES_POSITIVE" if valid else "LATENCY_NEGATIVE_OR_ZERO_SIZE", fail_closed=not valid)


def latency_tick_receipt(*, prices: Sequence[Any], tick_size: Any) -> dict[str, Any]:
    try:
        tick = float(tick_size)
        valid = math.isfinite(tick) and tick > 0 and bool(prices) and all(abs((float(price) / tick) - round(float(price) / tick)) <= 1e-9 for price in prices)
    except (TypeError, ValueError, OverflowError):
        valid = False
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_TICK_ALIGNED" if valid else "LATENCY_TICK_INVALID", fail_closed=not valid)


def latency_delta_receipt(*, has_snapshot: bool, delta_count: Any) -> dict[str, Any]:
    valid = has_snapshot is True and _latency_integer(delta_count) and delta_count > 0
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_DELTA_HAS_SNAPSHOT" if valid else "LATENCY_DELTA_WITHOUT_SNAPSHOT", fail_closed=not valid)


def latency_staleness_receipt(*, now_ms: Any, received_ts_ms: Any, max_age_ms: Any) -> dict[str, Any]:
    valid = all(_latency_integer(value) for value in (now_ms, received_ts_ms, max_age_ms)) and now_ms >= received_ts_ms and now_ms - received_ts_ms <= max_age_ms
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_FRESH" if valid else "LATENCY_STALE", fail_closed=not valid)


def latency_quantity_receipt(*, requested_quantity: Any, visible_depth: Any) -> dict[str, Any]:
    valid = _latency_finite(requested_quantity) and _latency_finite(visible_depth) and 0 < float(requested_quantity) <= float(visible_depth)
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_QUANTITY_WITHIN_DEPTH" if valid else "LATENCY_QUANTITY_EXCEEDS_DEPTH", fail_closed=not valid)


def latency_consumption_receipt(*, consumed_quantity: Any, available_quantity: Any, already_consumed: Any) -> dict[str, Any]:
    valid = all(_latency_finite(value) for value in (consumed_quantity, available_quantity, already_consumed)) and min(float(consumed_quantity), float(available_quantity), float(already_consumed)) >= 0 and float(consumed_quantity) + float(already_consumed) <= float(available_quantity)
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_CONSUMPTION_ONCE" if valid else "LATENCY_DOUBLE_CONSUMPTION", fail_closed=not valid)


def latency_maker_touch_receipt(*, touched: bool, executed: bool) -> dict[str, Any]:
    valid = touched is False or executed is True
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_MAKER_EXECUTION_CONFIRMED" if valid else "LATENCY_TOUCH_ONLY_NOT_FILL", fail_closed=not valid)


def latency_fee_order_receipt(*, maker_fee_bps: Any, taker_fee_bps: Any) -> dict[str, Any]:
    valid = _latency_finite(maker_fee_bps) and _latency_finite(taker_fee_bps) and float(maker_fee_bps) >= 0 and float(taker_fee_bps) >= float(maker_fee_bps)
    return _latency_base("PROVEN" if valid else "REJECTED", verdict="LATENCY_FEE_ORDER_VALID" if valid else "LATENCY_FEE_ORDER_INVERTED", fail_closed=not valid)


__all__ = [
    "SCHEMA_VERSION", "MEASURED", "ASSUMED", "NO_FILL", "STALE_BOOK", "UNMEASURABLE", "STRESS_ONLY",
    "selectionner_carnet_causal", "latence_scalaire_stress_bps", "verite_latence",
    "latency_truth_safety_receipt", "latency_required_field_receipt", "latency_null_field_receipt",
    "latency_field_type_receipt", "latency_finite_receipt", "latency_cutoff_receipt", "latency_age_receipt",
    "latency_duplicate_receipt", "latency_retry_receipt", "latency_replay_receipt", "latency_depth_receipt",
    "latency_crossed_book_receipt", "latency_negative_size_receipt", "latency_tick_receipt", "latency_delta_receipt",
    "latency_staleness_receipt", "latency_quantity_receipt", "latency_consumption_receipt",
    "latency_maker_touch_receipt", "latency_fee_order_receipt",
]
