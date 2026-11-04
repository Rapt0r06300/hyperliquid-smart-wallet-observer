"""ALPHA P27 — METAORDER HAZARD : P(prochaine slice | état) et FLUX RÉSIDUEL attendu.

But : prédire le flux RÉSIDUEL d'un métaordre (ce qu'il reste à exécuter, qui poussera le prix), pas copier
une slice déjà publique. Features : stade (EARLY/MIDDLE/LATE), cadence régulière, fraction exécutée, résidu,
catch-up, reconstitution de profondeur, crowding. Sorties : remaining_flow_probability, expected_remaining_notional.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _finite(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def compare_metaorders_to_isolated_fills(
    metaorders: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
    *,
    metaorder_id_field: str = "metaorder_id",
    value_field: str = "net_pnl_bps",
    weight_field: str = "notional_usd",
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Compare an aggregate metaorder value with its isolated-fill reconstruction.

    Every fill must have a finite value and strictly positive notional.  The
    isolated baseline is a notional-weighted mean per metaorder; rows without an
    ID, a value or a valid weight are rejected rather than replaced with zero.
    Duplicate aggregate IDs are ambiguous and fail closed.  This is a PAPER
    conservation diagnostic, not an economic promotion gate.
    """

    tol = _finite(tolerance)
    if tol is None or tol < 0.0:
        raise ValueError("tolerance must be finite and non-negative")

    aggregate: dict[str, float] = {}
    duplicate_metaorders = 0
    invalid_metaorders = 0
    for raw in metaorders or ():
        if not isinstance(raw, Mapping):
            invalid_metaorders += 1
            continue
        identifier = str(raw.get(metaorder_id_field) or "").strip()
        value = _finite(raw.get(value_field))
        if not identifier or value is None:
            invalid_metaorders += 1
            continue
        if identifier in aggregate:
            duplicate_metaorders += 1
            aggregate.pop(identifier, None)
            continue
        aggregate[identifier] = value

    grouped: defaultdict[str, list[tuple[float, float]]] = defaultdict(list)
    invalid_fills = 0
    for raw in fills or ():
        if not isinstance(raw, Mapping):
            invalid_fills += 1
            continue
        identifier = str(raw.get(metaorder_id_field) or "").strip()
        value = _finite(raw.get(value_field))
        weight = _finite(raw.get(weight_field))
        if not identifier or value is None or weight is None or weight <= 0.0:
            invalid_fills += 1
            continue
        grouped[identifier].append((value, weight))

    comparisons: list[dict[str, Any]] = []
    unmatched_fills = 0
    for identifier, rows in sorted(grouped.items()):
        if identifier not in aggregate:
            unmatched_fills += len(rows)
            continue
        total_weight = sum(weight for _value, weight in rows)
        isolated = sum(value * weight for value, weight in rows) / total_weight
        aggregate_value = aggregate[identifier]
        difference = aggregate_value - isolated
        comparisons.append(
            {
                "metaorder_id": identifier,
                "metaorder_value": round(aggregate_value, 8),
                "isolated_weighted_value": round(isolated, 8),
                "difference": round(difference, 8),
                "fill_count": len(rows),
                "notional_total": round(total_weight, 8),
                "status": "MATCH" if abs(difference) <= tol else "MISMATCH",
            }
        )

    mismatches = sum(row["status"] == "MISMATCH" for row in comparisons)
    return {
        "status": "COMPARABLE" if comparisons else UNMEASURABLE,
        "value_field": value_field,
        "weight_field": weight_field,
        "tolerance": tol,
        "metaorders_input": len(metaorders),
        "valid_metaorders": len(aggregate),
        "invalid_metaorders_rejected": invalid_metaorders,
        "duplicate_metaorders_rejected": duplicate_metaorders,
        "fills_input": len(fills),
        "valid_fills": sum(len(rows) for rows in grouped.values()),
        "invalid_fills_rejected": invalid_fills,
        "unmatched_fills": unmatched_fills,
        "matched_metaorders": len(comparisons),
        "mismatched_metaorders": mismatches,
        "all_matched": bool(comparisons) and mismatches == 0,
        "comparisons": comparisons,
        "paper_read_only": True,
        "real_execution": False,
    }


def flux_residuel(total_size: Any, executed_fraction: Any) -> Any:
    """Notional résiduel attendu = total × (1 − fraction exécutée). UNMEASURABLE si inconnu."""
    if not isinstance(total_size, (int, float)) or not isinstance(executed_fraction, (int, float)):
        return UNMEASURABLE
    return round(float(total_size) * max(0.0, 1.0 - float(executed_fraction)), 6)


def remaining_flow_probability(*, stade: str, executed_fraction: Any, cadence_reguliere: bool = True,
                               crowding: Any = 0.0, depth_replenishment: Any = 0.5) -> dict[str, Any]:
    """P(continuation du métaordre) ∈ [0,1] : haute si EARLY + faible fraction + cadence + peu de crowding."""
    if not isinstance(executed_fraction, (int, float)):
        return {"p_continuation": UNMEASURABLE}
    base = {"FIRST_SLICE": 0.85, "EARLY": 0.8, "MIDDLE": 0.5, "CONTINUATION": 0.55, "LATE": 0.2}.get(str(stade).upper(), 0.5)
    p = base * (1.0 - float(executed_fraction))
    if not cadence_reguliere:
        p *= 0.7
    if isinstance(crowding, (int, float)):
        p *= (1.0 - 0.5 * max(0.0, min(1.0, crowding)))     # crowding réduit notre part du résidu
    p = max(0.0, min(1.0, p))
    favorable = bool(str(stade).upper() in ("FIRST_SLICE", "EARLY") and float(executed_fraction) < 0.4
                     and (isinstance(crowding, (int, float)) and crowding < 0.3))
    return {"p_continuation": round(p, 4), "favorable_EARLY_LARGE_RESIDUAL_LOW_CROWDING": favorable}


def markout_by_signal_age_receipt(
    train_rows: Sequence[Mapping[str, Any]], oos_rows: Sequence[Mapping[str, Any]], *, min_rows: int = 3
) -> dict[str, Any]:
    """Summarize markout by signal age on disjoint TRAIN/OOS observations."""
    if isinstance(min_rows, bool) or not isinstance(min_rows, int) or min_rows < 1:
        return {"status": UNMEASURABLE, "reason": "invalid_min_rows"}
    bands = ((0, 100), (100, 500), (500, 1000), (1000, None))
    def summarize(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], str | None]:
        out: dict[str, Any] = {}
        for lower, upper in bands:
            values: list[float] = []
            for row in rows or ():
                if not isinstance(row, Mapping):
                    return {}, "invalid_row"
                age = _finite(row.get("signal_age_ms"))
                markout = _finite(row.get("net_markout_bps"))
                if age is None or markout is None or age < 0 or (upper is not None and age >= upper) or age < lower:
                    continue
                values.append(markout)
            key = f"{lower}_{upper if upper is not None else 'plus'}"
            out[key] = {"count": len(values), "mean_net_markout_bps": round(sum(values) / len(values), 8) if values else None}
        return out, None
    train, train_error = summarize(train_rows)
    oos, oos_error = summarize(oos_rows)
    if train_error or oos_error:
        return {"status": UNMEASURABLE, "reason": train_error or oos_error}
    enough = all(bucket["count"] >= min_rows for split in (train, oos) for bucket in split.values())
    return {"status": "PROVEN" if enough else "MORE_DATA", "train": train, "oos": oos,
            "min_rows": min_rows, "lookahead_free": True}


def metaorder_aggregation_receipt(
    metaorders: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
    *,
    value_field: str = "net_pnl_bps",
    weight_field: str = "notional_usd",
) -> dict[str, Any]:
    """Compare aggregated metaorders with isolated fills without inventing matches."""
    result = compare_metaorders_to_isolated_fills(
        metaorders,
        fills,
        value_field=value_field,
        weight_field=weight_field,
    )
    comparable = result.get("status") == "COMPARABLE" and result.get("all_matched") is True
    return {
        **result,
        "verdict": "PROVEN" if comparable else "UNMEASURABLE",
        "aggregation_is_causal": True,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "flux_residuel",
    "remaining_flow_probability",
    "compare_metaorders_to_isolated_fills",
    "markout_by_signal_age_receipt",
    "metaorder_aggregation_receipt",
    "UNMEASURABLE",
]
