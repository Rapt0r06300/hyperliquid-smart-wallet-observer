"""SAFE-only independent module paper-PnL proof."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from hl_observer.simulation.economic_objective import TARGET_NET_USD_PER_DAY
from hl_observer.strategies.active_scope import (
    active_strategy_families,
    canonical_strategy_family,
    strategy_can_materialize,
)

MODULES = tuple(sorted(active_strategy_families()))


@dataclass(frozen=True)
class ModulePnl:
    module: str
    gross_pnl: float
    fees: float
    slippage: float
    funding_financing: float
    net_pnl: float
    sample_size: int
    threshold_usd: float
    threshold_met: bool
    proof_of_pnl: bool


def _canonical_module(module: str) -> str:
    # Versioned aliases are inputs only; certificates use one public family name.
    return canonical_strategy_family(module)


def prove_module(
    module: str,
    rows: Iterable[Mapping[str, Any]],
    threshold_usd: float = TARGET_NET_USD_PER_DAY,
) -> dict[str, Any]:
    canonical_module = _canonical_module(module)
    if canonical_module not in MODULES or not strategy_can_materialize(module):
        raise ValueError("unknown or inactive module")
    rows = list(rows)
    if not rows:
        raise ValueError("no evidence")
    try:
        threshold = float(threshold_usd)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid PnL threshold") from exc
    if not math.isfinite(threshold) or threshold < 0.0:
        raise ValueError("invalid PnL threshold")
    if any(
        row.get("quality_status") != "SAFE"
        or not row.get("replay_compatible", False)
        for row in rows
    ):
        raise ValueError("PnL proof requires SAFE replay-compatible inputs")
    components = ("gross_pnl", "fees", "slippage", "funding_financing")
    parsed: dict[str, list[float]] = {key: [] for key in components}
    for row in rows:
        for key in components:
            try:
                value = float(row.get(key))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unmeasured PnL component: {key}") from exc
            if not math.isfinite(value):
                raise ValueError(f"invalid PnL component: {key}")
            parsed[key].append(value)
    gross = sum(parsed["gross_pnl"])
    fees = sum(parsed["fees"])
    slippage = sum(parsed["slippage"])
    funding = sum(parsed["funding_financing"])
    net = gross - fees - slippage - funding
    return asdict(ModulePnl(
        canonical_module,
        gross,
        fees,
        slippage,
        funding,
        net,
        len(rows),
        threshold,
        net >= threshold,
        True,
    ))



def independent_module_verdict(
    module: str,
    rows: Iterable[Mapping[str, Any]],
    threshold_usd: float = TARGET_NET_USD_PER_DAY,
) -> dict[str, Any]:
    """Return a fail-closed independent certificate without cross-module compensation."""
    evidence = list(rows)
    canonical_module = _canonical_module(module)
    if canonical_module not in MODULES or not strategy_can_materialize(module):
        raise ValueError("unknown or inactive module")
    if not evidence:
        verdict = {"module": canonical_module, "status": "MORE_DATA", "reason": "NO_SAFE_REPLAY_COMPATIBLE_EVIDENCE", "proof_of_pnl": False, "sample_size": 0}
    elif any(row.get("quality_status") != "SAFE" or not row.get("replay_compatible", False) for row in evidence):
        verdict = {"module": canonical_module, "status": "UNMEASURABLE", "reason": "NON_SAFE_OR_NON_REPLAY_COMPATIBLE_INPUT", "proof_of_pnl": False, "sample_size": len(evidence)}
    else:
        try:
            result = prove_module(canonical_module, evidence, threshold_usd)
        except ValueError as exc:
            verdict = {"module": canonical_module, "status": "UNMEASURABLE", "reason": f"PNL_EVIDENCE_INVALID:{exc}", "proof_of_pnl": False, "sample_size": len(evidence)}
        else:
            # Politique canonique : aucun seuil chiffré n'est une porte de preuve. Le verdict dépend
            # du signe du net APRÈS tous les coûts ; l'atteinte du repère historique est rapportée à part.
            verdict = dict(result)
            net_positive = result["net_pnl"] > 0.0
            verdict["status"] = "PROVEN" if net_positive else "REJECTED"
            verdict["reason"] = "NET_POSITIVE_AFTER_COSTS" if net_positive else "NET_NOT_POSITIVE_AFTER_COSTS"
            verdict["reference_threshold_met"] = result["threshold_met"]
            verdict["threshold_is_evaluation_only"] = True
    verdict["certificate_digest"] = hashlib.sha256(json.dumps(verdict, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return verdict


def independent_module_certificates(
    evidence: Mapping[str, Iterable[Mapping[str, Any]]],
    threshold_usd: float = TARGET_NET_USD_PER_DAY,
) -> dict[str, Any]:
    certificates = {
        module: independent_module_verdict(module, evidence.get(module, ()), threshold_usd)
        for module in MODULES
    }
    return {
        "schema": "alina.independent_module_pnl_certificates.v1",
        "threshold_usd_per_day": threshold_usd,
        "modules": certificates,
        "aggregate_allowed": False,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }


def prove_all(
    evidence: Mapping[str, Iterable[Mapping[str, Any]]],
    threshold_usd: float = TARGET_NET_USD_PER_DAY,
) -> dict[str, Any]:
    out = {
        module: prove_module(module, evidence[module], threshold_usd)
        for module in MODULES
    }
    return {
        "threshold_is_evaluation_only": True,
        "modules": out,
        "all_modules_independently_met": all(
            value["threshold_met"] for value in out.values()
        ),
    }


def _pnl_base(status: str, **values: Any) -> dict[str, Any]:
    """Return deterministic paper evidence without claiming economic proof."""
    return {
        "status": status,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "mutation": False,
        "aggregate_allowed": False,
        "closure_allowed": False,
        **values,
    }


def _pnl_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _pnl_finite(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _pnl_sha(value: Any, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and all(
        character in "0123456789abcdef" for character in value
    )


def pnl_state_safety_receipt(certificate: Mapping[str, Any]) -> dict[str, Any]:
    valid = (
        isinstance(certificate, Mapping)
        and certificate.get("paper_only") is True
        and certificate.get("read_only") is True
        and certificate.get("real_execution") is False
        and certificate.get("aggregate_allowed") is False
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_STATE_SAFE" if valid else "PNL_STATE_UNSAFE",
        fail_closed=not valid,
    )


def dispatch_to_pnl_boundary_receipt(dispatch_result: Any, pnl_certificate: Any) -> dict[str, Any]:
    """Admit dispatch provenance to paper PnL controls without economic promotion."""
    from hl_observer.control_plane.dispatch_receipt import dispatch_state_safety_receipt

    dispatch = dispatch_state_safety_receipt(dispatch_result)
    pnl = pnl_state_safety_receipt(pnl_certificate)
    valid = (
        dispatch.get("status") == "PROVEN"
        and dispatch.get("paper_read_only") is True
        and dispatch.get("real_execution") is False
        and dispatch.get("dispatch_mutation") is False
        and dispatch.get("fail_closed") is False
        and pnl.get("status") == "PROVEN"
        and pnl.get("paper_only") is True
        and pnl.get("read_only") is True
        and pnl.get("real_execution") is False
        and pnl.get("aggregate_allowed") is False
        and pnl.get("mutation") is False
        and pnl.get("fail_closed") is False
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="DISPATCH_PNL_BOUNDARY_SAFE" if valid else "DISPATCH_PNL_BOUNDARY_REJECTED",
        dispatch_status=dispatch.get("status"),
        pnl_status=pnl.get("status"),
        dispatch_mutation=False,
        economic_promotion=False,
        phase_mutation=False,
        fail_closed=not valid,
    )


def native_venue_to_pnl_boundary_receipt(
    venue_result: Any,
    pnl_certificate: Any,
) -> dict[str, Any]:
    """Admit Bitget public capabilities to independent paper-PnL controls."""
    from hl_observer.venues.bitget import venue_capability_safety_receipt

    venue = venue_capability_safety_receipt(venue_result)
    pnl = pnl_state_safety_receipt(pnl_certificate)
    valid = (
        venue.get("status") == "PROVEN"
        and venue.get("paper_read_only") is True
        and venue.get("real_execution") is False
        and venue.get("network_execution") is False
        and pnl.get("status") == "PROVEN"
        and pnl.get("paper_only") is True
        and pnl.get("read_only") is True
        and pnl.get("real_execution") is False
        and pnl.get("aggregate_allowed") is False
        and pnl.get("mutation") is False
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="NATIVE_VENUE_PNL_BOUNDARY_SAFE" if valid else "NATIVE_VENUE_PNL_BOUNDARY_REJECTED",
        venue_status=venue.get("status"),
        pnl_status=pnl.get("status"),
        network_execution=False,
        aggregate_allowed=False,
        pnl_mutation=False,
        promotion="DISABLED_UNTIL_REVIEW",
        fail_closed=not valid,
    )


def pnl_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = (
        isinstance(row, Mapping)
        and isinstance(field, str)
        and bool(field)
        and field in row
        and row[field] not in (None, "")
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_FIELD_PRESENT" if valid else "PNL_FIELD_MISSING",
        field=field,
        fail_closed=not valid,
    )


def pnl_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = (
        isinstance(row, Mapping)
        and isinstance(field, str)
        and bool(field)
        and field in row
        and row[field] is not None
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_FIELD_NON_NULL" if valid else "PNL_FIELD_NULL",
        field=field,
        fail_closed=not valid,
    )


def pnl_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    value = row.get(field) if isinstance(row, Mapping) else None
    bool_is_int = expected_type is int and isinstance(value, bool)
    valid = (
        isinstance(row, Mapping)
        and isinstance(field, str)
        and bool(field)
        and isinstance(expected_type, type)
        and isinstance(value, expected_type)
        and not bool_is_int
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_FIELD_TYPE_VALID" if valid else "PNL_FIELD_TYPE_INVALID",
        field=field,
        fail_closed=not valid,
    )


def pnl_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _pnl_finite(value)
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_VALUE_FINITE" if valid else "PNL_VALUE_NON_FINITE",
        value=float(value) if valid else None,
        fail_closed=not valid,
    )


def pnl_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = (
        _pnl_integer(event_ts_ms)
        and _pnl_integer(cutoff_ts_ms)
        and event_ts_ms <= cutoff_ts_ms
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_EVENT_WITHIN_CUTOFF" if valid else "PNL_EVENT_AFTER_CUTOFF",
        fail_closed=not valid,
    )


def pnl_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = (
        _pnl_integer(event_ts_ms)
        and _pnl_integer(oldest_allowed_ts_ms)
        and event_ts_ms >= oldest_allowed_ts_ms
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_EVENT_AGE_VALID" if valid else "PNL_EVENT_TOO_OLD",
        fail_closed=not valid,
    )


def pnl_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = (
        bool(values)
        and all(isinstance(value, str) and value.strip() for value in values)
        and len(values) == len(set(values))
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_EVENTS_UNIQUE" if valid else "PNL_EVENT_DUPLICATE_OR_EMPTY",
        fail_closed=not valid,
    )


def pnl_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = (
        _pnl_integer(attempts)
        and _pnl_integer(max_attempts)
        and 1 <= attempts <= max_attempts
        and checkpoint_saved is True
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_RETRY_BOUNDED" if valid else "PNL_RETRY_UNSAFE",
        fail_closed=not valid,
    )


def pnl_replay_receipt(*, outputs: Iterable[Any]) -> dict[str, Any]:
    values = list(outputs)
    valid = bool(values) and len({json.dumps(value, sort_keys=True, separators=(",", ":")) for value in values}) == 1
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_REPLAY_DETERMINISTIC" if valid else "PNL_REPLAY_DIVERGED",
        fail_closed=not valid,
    )


def pnl_stage_order_receipt(*, creation_phase: Any, status: Any, phase_barrier: bool) -> dict[str, Any]:
    valid = creation_phase in {"COLLECT", "ANALYZE"} and status in {"RUNNING", "COMPLETE", "FAILED", "BLOCKED"} and phase_barrier is True
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_PHASE_BARRIER" if valid else "PNL_PHASE_BARRIER_MISSING",
        fail_closed=not valid,
    )


def pnl_collect_authorization_receipt(*, creation_phase: Any, automatic: bool, authorized: bool) -> dict[str, Any]:
    valid = (
        creation_phase == "COLLECT"
        and isinstance(automatic, bool)
        and ((automatic is False and authorized is False) or (automatic is True and authorized is True))
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_COLLECT_AUTHORIZED" if valid else "PNL_COLLECT_UNAUTHORIZED",
        fail_closed=not valid,
    )


def pnl_request_replay_receipt(*, request_ids: Iterable[Any], accepted_request_ids: Iterable[Any]) -> dict[str, Any]:
    requests = list(request_ids)
    accepted = list(accepted_request_ids)
    valid = (
        bool(requests)
        and all(isinstance(value, str) and value.strip() for value in requests)
        and len(requests) == len(set(requests))
        and len(accepted) == len(set(accepted))
        and set(accepted).issubset(requests)
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_REQUESTS_IDEMPOTENT" if valid else "PNL_REQUEST_REPLAYED",
        fail_closed=not valid,
    )


def pnl_epoch_receipt(*, observed_epoch: Any, current_epoch: Any) -> dict[str, Any]:
    valid = _pnl_integer(observed_epoch) and _pnl_integer(current_epoch) and observed_epoch == current_epoch
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_EPOCH_CURRENT" if valid else "PNL_EPOCH_STALE",
        fail_closed=not valid,
    )


def pnl_hash_receipt(*, expected_sha: Any, actual_sha: Any, length: int = 40) -> dict[str, Any]:
    valid = _pnl_sha(expected_sha, length) and _pnl_sha(actual_sha, length) and expected_sha == actual_sha
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_SHA_MATCH" if valid else "PNL_SHA_MISMATCH",
        fail_closed=not valid,
    )


def pnl_lease_receipt(*, worker_id: Any, lease_owner: Any, lease_expires_at_ms: Any, now_ms: Any) -> dict[str, Any]:
    valid = (
        isinstance(worker_id, str)
        and bool(worker_id.strip())
        and worker_id == lease_owner
        and _pnl_integer(lease_expires_at_ms)
        and _pnl_integer(now_ms)
        and now_ms < lease_expires_at_ms
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_LEASE_ACTIVE" if valid else "PNL_LEASE_EXPIRED_OR_MISMATCHED",
        fail_closed=not valid,
    )


def pnl_single_owner_receipt(*, owner_ids: Iterable[Any]) -> dict[str, Any]:
    owners = list(owner_ids)
    valid = len(owners) == 1 and isinstance(owners[0], str) and bool(owners[0].strip())
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_SINGLE_OWNER" if valid else "PNL_SPLIT_BRAIN",
        fail_closed=not valid,
    )


def pnl_checkpoint_receipt(*, checkpoint: Mapping[str, Any], required_fields: Iterable[str]) -> dict[str, Any]:
    required = list(required_fields)
    valid = (
        isinstance(checkpoint, Mapping)
        and bool(required)
        and all(isinstance(field, str) and checkpoint.get(field) not in (None, "") for field in required)
        and checkpoint.get("saved") is True
    )
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_CHECKPOINT_COMPLETE" if valid else "PNL_CHECKPOINT_PARTIAL",
        fail_closed=not valid,
    )


def pnl_runner_receipt(*, runner_label: Any) -> dict[str, Any]:
    normalized = runner_label.strip().lower() if isinstance(runner_label, str) else ""
    valid = bool(normalized) and "self-hosted" not in normalized and "self_hosted" not in normalized and "localhost" not in normalized and normalized in {"ubuntu-latest", "windows-latest", "macos-latest", "github-hosted"}
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_GITHUB_HOSTED" if valid else "PNL_RUNNER_FORBIDDEN",
        fail_closed=not valid,
    )


def pnl_done_coverage_receipt(*, status: Any, coverage_status: Any, required_proofs: Iterable[Any], completed_proofs: Iterable[Any]) -> dict[str, Any]:
    required = set(required_proofs)
    completed = set(completed_proofs)
    valid = status == "PROVEN" and coverage_status == "PROVEN" and bool(required) and required.issubset(completed)
    return _pnl_base(
        "PROVEN" if valid else "REJECTED",
        verdict="PNL_DONE_COVERAGE_COMPLETE" if valid else "PNL_DONE_WITHOUT_COVERAGE",
        fail_closed=not valid,
    )
