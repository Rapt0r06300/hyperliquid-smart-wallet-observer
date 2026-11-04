"""Jalon 1 — décomposition du coût d'exécution en 4 composantes bps NON redondantes.

Le scoreboard reste `UNMEASURABLE` sur `costs_bps` tant que les 4 composantes ne sont pas mesurées.
`slippage_model` mesure pourtant déjà un slippage RÉFÉRENCÉ AU MID — qui contient DÉJÀ le demi-spread.
Sommer un `spread_bps` séparé par-dessus le double-compterait. Ce module décompose proprement le
coût réel d'un franchissement, tout référencé au **mid au moment de la DÉCISION**, en 4 parts
additives et disjointes (dénominateur commun = mid, donc `spread + slippage` égale EXACTEMENT le coût
mid→prix moyen, sans terme croisé) :

    spread_bps   = mid → meilleur prix touché       (franchir le demi-spread)
    slippage_bps = meilleur prix → prix moyen exécuté (impact de profondeur au-delà du touch)
    fees_bps     = frais taker (bps)
    latency_bps  = dérive du mid pendant la latence RÉELLE décision→exécution (adverse = coût +)

Règle dure : toute composante dont l'entrée manque vaut `UNMEASURABLE` (None), JAMAIS 0 — un coût
oublié fabrique un faux edge. Le total réutilise `scoreboard_metrics.costs_bps` : il n'existe que si
les 4 sont mesurées. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from collections.abc import Iterable, Mapping
from typing import Any, Sequence

from hl_observer.simulation.scoreboard_metrics import costs_bps as _sommer_couts

SCHEMA_VERSION = "hypersmart.cost_components.v1"
DEFAULT_MAX_OBSERVATION_AGE_MS = 90_000
_BPS = 10_000.0


def _pos(x) -> float | None:
    """Nombre fini strictement positif, sinon None (un prix/mid <= 0 n'est pas mesurable)."""
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _sens(side: object) -> int | None:
    """+1 pour un achat, -1 pour une vente ; None si le sens est illisible."""
    s = str(side or "").strip().upper()
    if s in ("BUY", "B", "LONG", "BID"):
        return 1
    if s in ("SELL", "S", "SHORT", "ASK"):
        return -1
    return None


def spread_bps(mid: float, best_touch: float, side: object) -> float | None:
    """Coût de franchir le demi-spread : mid → meilleur prix touché, en bps signés-coût (>0 = payé plus)."""
    m, t = _pos(mid), _pos(best_touch)
    sg = _sens(side)
    if m is None or t is None or sg is None:
        return None
    return round(sg * (t - m) / m * _BPS, 6)


def slippage_bps(best_touch: float, avg_fill: float, side: object, *, mid: float | None = None) -> float | None:
    """Impact de profondeur AU-DELÀ du touch : touch → prix moyen. Dénominateur = mid (défaut : touch).

    Utiliser le mid comme dénominateur commun rend `spread_bps + slippage_bps` EXACTEMENT égal au
    coût mid→prix moyen (pas de terme croisé). Sans mid fourni, on retombe sur le touch (approximation).
    """
    t, a = _pos(best_touch), _pos(avg_fill)
    sg = _sens(side)
    if t is None or a is None or sg is None:
        return None
    denom = _pos(mid) if mid is not None else t
    if denom is None:
        return None
    return round(sg * (a - t) / denom * _BPS, 6)


def latency_bps(mid_decision: float, mid_fill: float, side: object) -> float | None:
    """Dérive du mid pendant la latence RÉELLE décision→exécution. Adverse (>0) = surcoût ; favorable (<0) = crédit.

    Signé et honnête par trade : la latence peut jouer pour ou contre. `None` si un des deux mids manque
    (on ne suppose JAMAIS une latence nulle : une latence non mesurée reste UNMEASURABLE, pas 0)."""
    d, f = _pos(mid_decision), _pos(mid_fill)
    sg = _sens(side)
    if d is None or f is None or sg is None:
        return None
    return round(sg * (f - d) / d * _BPS, 6)


@dataclass(frozen=True, slots=True)
class CostComponents:
    fees_bps: float | None
    spread_bps: float | None
    slippage_bps: float | None
    latency_bps: float | None
    total_bps: float | None
    unmeasured: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "fees_bps": self.fees_bps, "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps, "latency_bps": self.latency_bps,
            "total_bps": self.total_bps, "unmeasured": list(self.unmeasured),
            "paper_only": True, "real_execution": False,
        }


def _finalise(fees, spread, slip, lat) -> CostComponents:
    total = _sommer_couts(fees_bps=fees, spread_bps=spread, slippage_bps=slip, latency_bps=lat)
    champs = {"fees_bps": fees, "spread_bps": spread, "slippage_bps": slip, "latency_bps": lat}
    unmeasured = tuple(k for k, v in champs.items() if v is None)
    if total is None and "total_bps" not in unmeasured:
        unmeasured = unmeasured + ("total_bps",)
    return CostComponents(fees_bps=fees, spread_bps=spread, slippage_bps=slip,
                          latency_bps=lat, total_bps=total, unmeasured=unmeasured)


def decompose_execution(
    *,
    side: object,
    mid_decision: float | None,
    best_touch: float | None,
    avg_fill_price: float | None,
    mid_at_fill: float | None = None,
    fee_bps: float | None = None,
    observation_age_ms: float | None = None,
    max_observation_age_ms: float = DEFAULT_MAX_OBSERVATION_AGE_MS,
) -> CostComponents:
    """Décompose un franchissement en 4 composantes bps. Chaque entrée absente ⇒ composante UNMEASURABLE."""
    try:
        age = None if observation_age_ms is None else float(observation_age_ms)
        max_age = float(max_observation_age_ms)
    except (TypeError, ValueError, OverflowError):
        age, max_age = math.nan, math.nan
    if age is not None and (not math.isfinite(age) or age < 0.0 or not math.isfinite(max_age) or max_age < 0.0 or age > max_age):
        return _finalise(None, None, None, None)
    spread = spread_bps(mid_decision, best_touch, side) if (mid_decision is not None and best_touch is not None) else None
    slip = (slippage_bps(best_touch, avg_fill_price, side, mid=mid_decision)
            if (best_touch is not None and avg_fill_price is not None) else None)
    lat = latency_bps(mid_decision, mid_at_fill, side) if (mid_decision is not None and mid_at_fill is not None) else None
    fees = None
    if fee_bps is not None and not isinstance(fee_bps, bool):
        try:
            fv = float(fee_bps)
            fees = round(fv, 6) if math.isfinite(fv) else None
        except (TypeError, ValueError):
            fees = None
    return _finalise(fees, spread, slip, lat)


def _meilleur_touch(book_side: Sequence, sens: int) -> float | None:
    """Meilleur prix touché : plus bas ask (achat), plus haut bid (vente). None si carnet vide/illisible."""
    prix: list[float] = []
    for niveau in book_side or ():
        try:
            p = float(niveau[0])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(p) and p > 0:
            prix.append(p)
    if not prix:
        return None
    return min(prix) if sens > 0 else max(prix)


def depuis_carnet_causal(
    *,
    side: object,
    notional_usdc: float,
    mid_decision: float,
    asks: Sequence = (),
    bids: Sequence = (),
    mid_at_fill: float | None = None,
    fee_bps: float | None = None,
    min_fill_ratio: float = 0.85,
) -> CostComponents:
    """Câblage L2 CAUSAL : marche le carnet (exec_model) au prix de décision, puis décompose le coût.

    Réutilise le book-walker existant (`simulate_depth_execution`) — aucune duplication. Si rien ne se
    remplit, `avg_fill_price` est None ⇒ slippage UNMEASURABLE (on ne facture pas un fill inexistant)."""
    from hl_observer.paper_trading.exec_model import simulate_depth_execution

    sg = _sens(side)
    touch = _meilleur_touch(asks if (sg or 0) > 0 else bids, sg) if sg is not None else None
    execution = simulate_depth_execution(
        side=str(side), notional_usdc=notional_usdc, mid_price=mid_decision,
        asks=list(asks), bids=list(bids), min_fill_ratio=min_fill_ratio,
    )
    avg = getattr(execution, "average_fill_price", None)
    return decompose_execution(
        side=side, mid_decision=mid_decision, best_touch=touch,
        avg_fill_price=avg, mid_at_fill=mid_at_fill, fee_bps=fee_bps,
    )


def mark_mid_cost_receipt(
    *,
    side: object,
    mid_decision: object,
    best_touch: object,
    avg_fill_price: object,
    mid_at_fill: object,
    fee_bps: object,
) -> dict[str, Any]:
    """Require observed depth and fill timing before certifying a mid-marked trade."""
    values = (mid_decision, best_touch, avg_fill_price, mid_at_fill, fee_bps)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values):
        return {"status": "UNMEASURABLE", "reason": "CAUSAL_COST_INPUT_MISSING"}
    components = decompose_execution(side=side, mid_decision=float(mid_decision), best_touch=float(best_touch), avg_fill_price=float(avg_fill_price), mid_at_fill=float(mid_at_fill), fee_bps=float(fee_bps))
    if components.total_bps is None:
        return {"status": "UNMEASURABLE", "reason": "CAUSAL_COST_COMPONENT_MISSING", **components.to_dict()}
    return {"status": "PROVEN", "depth_observed": True, "spread_included": True, **components.to_dict()}


__all__ = [
    "SCHEMA_VERSION", "DEFAULT_MAX_OBSERVATION_AGE_MS", "CostComponents",
    "spread_bps", "slippage_bps", "latency_bps",
    "decompose_execution", "depuis_carnet_causal", "mark_mid_cost_receipt",
]


def _cost_base(status: str, **values: Any) -> dict[str, Any]:
    """Return a non-promoting, paper-only cost-control receipt."""
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _cost_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _cost_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def cost_components_safety_receipt(result: Any) -> dict[str, Any]:
    """Validate the cost decomposition envelope without certifying a trading edge."""
    required = ("fees_bps", "spread_bps", "slippage_bps", "latency_bps", "total_bps", "unmeasured")
    component_names = required[:-1]
    valid = (
        isinstance(result, Mapping)
        and result.get("schema_version") == SCHEMA_VERSION
        and all(key in result for key in required)
        and isinstance(result.get("unmeasured"), list)
        and result.get("paper_only") is True
        and result.get("real_execution") is False
    )
    if valid:
        unmeasured = set(result["unmeasured"])
        valid = (
            unmeasured <= set(required)
            and all(
                value is None or _cost_finite(value)
                for value in (result[name] for name in component_names)
            )
            and all(
                (result[name] is None) == (name in unmeasured)
                for name in component_names
            )
            and ((result["total_bps"] is None) == ("total_bps" in unmeasured))
        )
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_COMPONENTS_SAFE" if valid else "COST_COMPONENTS_UNSAFE", fail_closed=not valid)


def runtime_parity_to_cost_boundary_receipt(
    runtime_parity_result: Any,
    cost_result: Any,
) -> dict[str, Any]:
    """Join runtime/replay parity with causal cost controls without certifying PnL."""
    parity_valid = False
    if runtime_parity_result is not None:
        from hl_observer.backtest.runtime_parity import runtime_parity_safety_receipt

        parity_valid = runtime_parity_safety_receipt(runtime_parity_result).get("status") == "PROVEN"
    cost_valid = cost_components_safety_receipt(cost_result).get("status") == "PROVEN"
    valid = parity_valid and cost_valid
    return _cost_base(
        "PROVEN" if valid else "REJECTED",
        verdict="RUNTIME_PARITY_TO_COST_BOUNDARY_SAFE" if valid else "RUNTIME_PARITY_TO_COST_BOUNDARY_UNSAFE",
        parity_status="PROVEN" if parity_valid else "REJECTED",
        cost_status="PROVEN" if cost_valid else "REJECTED",
        fail_closed=not valid,
    )


def cost_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_FIELD_PRESENT" if valid else "COST_FIELD_MISSING", field=field, fail_closed=not valid)


def cost_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_FIELD_NON_NULL" if valid else "COST_FIELD_NULL", field=field, fail_closed=not valid)


def cost_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_FIELD_TYPE_VALID" if valid else "COST_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def cost_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _cost_finite(value)
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_VALUE_FINITE" if valid else "COST_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def cost_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _cost_integer(event_ts_ms) and _cost_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_EVENT_WITHIN_CUTOFF" if valid else "COST_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def cost_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _cost_integer(event_ts_ms) and _cost_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_EVENT_AGE_VALID" if valid else "COST_EVENT_TOO_OLD", fail_closed=not valid)


def cost_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(str(value).strip() for value in values) and len(values) == len(set(values))
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_EVENTS_UNIQUE" if valid else "COST_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def cost_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _cost_integer(attempts) and _cost_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_RETRY_BOUNDED" if valid else "COST_RETRY_UNSAFE", fail_closed=not valid)


def cost_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_REPLAY_DETERMINISTIC" if valid else "COST_REPLAY_DIVERGED", fail_closed=not valid)


def cost_partition_receipt(*, train_ids: Sequence[Any], oos_ids: Sequence[Any], forward_ids: Sequence[Any]) -> dict[str, Any]:
    train, oos, forward = set(train_ids), set(oos_ids), set(forward_ids)
    valid = bool(train) and bool(oos) and bool(forward) and not (train & oos or train & forward or oos & forward)
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_PARTITIONS_DISJOINT" if valid else "COST_PARTITIONS_OVERLAP", fail_closed=not valid)


def cost_holdout_receipt(*, tuned_on_holdout: bool, holdout_locked: bool) -> dict[str, Any]:
    valid = tuned_on_holdout is False and holdout_locked is True
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_HOLDOUT_LOCKED" if valid else "COST_HOLDOUT_CONTAMINATED", fail_closed=not valid)


def cost_embargo_receipt(*, gap_ms: Any, required_gap_ms: Any) -> dict[str, Any]:
    valid = _cost_integer(gap_ms) and _cost_integer(required_gap_ms) and gap_ms >= 0 and gap_ms >= required_gap_ms
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_EMBARGO_SUFFICIENT" if valid else "COST_EMBARGO_INSUFFICIENT", fail_closed=not valid)


def cost_trials_receipt(*, trials: Any, recorded_trials: Any) -> dict[str, Any]:
    valid = _cost_integer(trials) and _cost_integer(recorded_trials) and trials > 0 and recorded_trials == trials
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_TRIALS_RECORDED" if valid else "COST_TRIALS_MISSING", fail_closed=not valid)


def cost_effect_size_receipt(*, trade_count: Any, gain: Any, minimum_trades: Any = 2) -> dict[str, Any]:
    valid = _cost_integer(trade_count) and _cost_integer(minimum_trades) and _cost_finite(gain) and trade_count >= minimum_trades
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_EFFECT_NOT_SINGLE_TRADE" if valid else "COST_EFFECT_UNDERPOWERED", fail_closed=not valid)


def cost_wallet_independence_receipt(*, wallet_ids: Sequence[Any], max_correlation: Any) -> dict[str, Any]:
    valid = bool(wallet_ids) and len(wallet_ids) == len(set(wallet_ids)) and _cost_finite(max_correlation) and 0 <= float(max_correlation) < 1
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_WALLETS_INDEPENDENT" if valid else "COST_WALLETS_CORRELATED", fail_closed=not valid)


def cost_hash_receipt(*, code_sha_before: Any, code_sha_after: Any, data_sha_before: Any, data_sha_after: Any) -> dict[str, Any]:
    valid = all(isinstance(value, str) and bool(value.strip()) for value in (code_sha_before, code_sha_after, data_sha_before, data_sha_after)) and code_sha_before == code_sha_after and data_sha_before == data_sha_after
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_HASHES_UNCHANGED" if valid else "COST_HASHES_CHANGED", fail_closed=not valid)


def cost_forward_cutoff_receipt(*, forward_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _cost_integer(forward_ts_ms) and _cost_integer(cutoff_ts_ms) and forward_ts_ms > cutoff_ts_ms
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_FORWARD_AFTER_CUTOFF" if valid else "COST_FORWARD_BEFORE_CUTOFF", fail_closed=not valid)


def cost_pessimistic_edge_receipt(*, gross_edge: Any, slippage: Any, fees: Any) -> dict[str, Any]:
    gross = float(gross_edge) if _cost_finite(gross_edge) else None
    slip = float(slippage) if _cost_finite(slippage) else None
    fee = float(fees) if _cost_finite(fees) else None
    valid = gross is not None and slip is not None and fee is not None and gross - slip - fee > 0
    return _cost_base("PROVEN" if valid else "REJECTED", verdict="COST_EDGE_SURVIVES_COSTS" if valid else "COST_EDGE_ERASED_BY_COSTS", fail_closed=not valid)


__all__ += [
    "cost_components_safety_receipt", "cost_required_field_receipt", "cost_null_field_receipt",
    "cost_field_type_receipt", "cost_finite_receipt", "cost_cutoff_receipt", "cost_age_receipt",
    "cost_duplicate_receipt", "cost_retry_receipt", "cost_replay_receipt", "cost_partition_receipt",
    "cost_holdout_receipt", "cost_embargo_receipt", "cost_trials_receipt", "cost_effect_size_receipt",
    "cost_wallet_independence_receipt", "cost_hash_receipt", "cost_forward_cutoff_receipt",
    "cost_pessimistic_edge_receipt",
]
