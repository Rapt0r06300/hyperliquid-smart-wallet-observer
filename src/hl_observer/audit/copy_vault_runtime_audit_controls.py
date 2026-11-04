"""Fail-closed runtime controls for the Copy-Vault audit/collection lanes.

These helpers are executable contracts used by local tests and hosted workflow
preflight.  They do not create evidence, contact an execution endpoint, or
promote any economic result.  Missing or ambiguous input stays UNKNOWN.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

MAX_PATCH_BYTES = 95_000_000
KNOWN_DELTA_STATES = frozenset({"OPEN", "ADD", "REDUCE", "CLOSE", "UNKNOWN"})
OFFICIAL_ENTRYPOINTS = (
    "tools/start_hypersmart_simulation.ps1",
    "src/hl_observer/ops/superviseur_collecteurs.py",
)


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def atomic_publish_bytes(path: str | Path, payload: bytes, *, max_bytes: int | None = None) -> dict[str, Any]:
    """Publish bytes atomically and durably, refusing an oversized single blob."""
    target = Path(path)
    if target.is_symlink():
        raise ValueError("AUDIT_ATOMIC_SYMLINK_TARGET")
    if max_bytes is not None and len(payload) > max_bytes:
        raise ValueError("AUDIT_ATOMIC_PARTITION_REQUIRED")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return {
            "path": target.as_posix(),
            "bytes": len(payload),
            "sha256": sha256(payload).hexdigest(),
            "atomic": True,
        }
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def partition_mapping(value: Mapping[str, Any], *, max_bytes: int = MAX_PATCH_BYTES) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    """Build a deterministic partition plan without mutating the source value."""
    if not isinstance(value, Mapping) or not value:
        raise ValueError("AUDIT_PARTITION_EMPTY_MAPPING")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 16:
        raise ValueError("AUDIT_PARTITION_INVALID_LIMIT")
    parts: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}
    current: dict[str, Any] = {}
    for key in sorted(value):
        candidate = dict(current)
        candidate[str(key)] = value[key]
        encoded = _canonical_json(candidate)
        if len(encoded) > max_bytes and current:
            number = len(parts) + 1
            payload = _canonical_json(current)
            name = f"part-{number:06d}.json"
            files[name] = payload
            parts.append({"path": name, "bytes": len(payload), "sha256": sha256(payload).hexdigest()})
            current = {str(key): value[key]}
            encoded = _canonical_json(current)
        if len(encoded) > max_bytes:
            raise ValueError("AUDIT_PARTITION_SINGLE_ENTRY_OVERSIZE")
        if str(key) not in current:
            current[str(key)] = value[key]
    if current:
        number = len(parts) + 1
        payload = _canonical_json(current)
        name = f"part-{number:06d}.json"
        files[name] = payload
        parts.append({"path": name, "bytes": len(payload), "sha256": sha256(payload).hexdigest()})
    return parts, files


def measured_patch_reuse(current: Mapping[str, Any], measured: Mapping[str, Any], *, asset_sha256: str) -> dict[str, Any]:
    """Reuse an exact current measurement and reject a retryable rescan request."""
    wanted = str(asset_sha256).lower()
    if len(wanted) != 64:
        raise ValueError("AUDIT_MEASURED_SHA_INVALID")
    current_sha = str(current.get("asset_sha256") or "").lower()
    measured_sha = str(measured.get("asset_sha256") or "").lower()
    if current_sha == wanted and current.get("exact") is True:
        return {"decision": "REUSED_EXACT", "asset_sha256": wanted}
    if measured_sha != wanted or measured.get("exact") is not True:
        return {"decision": "REMEASURE_REQUIRED", "asset_sha256": wanted}
    return {"decision": "ACCEPT_MEASURED", "asset_sha256": wanted}


def sha256_file_receipt(path: str | Path) -> dict[str, Any]:
    """Hash a regular file exactly; never return a digest for a symlink."""
    file_path = Path(path)
    if file_path.is_symlink() or not file_path.is_file():
        raise ValueError("AUDIT_SHA256_FILE_UNAVAILABLE")
    digest = sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": file_path.as_posix(), "sha256": digest.hexdigest(), "bytes": file_path.stat().st_size}


def classify_delta_state(value: Any, *, causal: bool) -> str:
    """Keep UNKNOWN when causal evidence is incomplete; never coerce to OPEN."""
    state = str(value or "").upper()
    if state not in KNOWN_DELTA_STATES or not causal:
        return "UNKNOWN"
    return state


def official_entrypoint_receipt(root: str | Path) -> dict[str, Any]:
    """Return a bounded inventory of the official Copy-Vault entrypoints."""
    base = Path(root)
    missing = [path for path in OFFICIAL_ENTRYPOINTS if not (base / path).is_file()]
    return {
        "scope": "copy_vault",
        "entrypoints": list(OFFICIAL_ENTRYPOINTS),
        "missing": missing,
        "ok": not missing,
        "paper_only": True,
    }


def coverage_shard_receipt(shard_paths: Sequence[str | Path], *, expected: int) -> dict[str, Any]:
    """Accept coverage only when every expected shard is present and regular."""
    paths = [Path(path) for path in shard_paths]
    valid = [path for path in paths if path.is_file() and not path.is_symlink() and path.stat().st_size > 0]
    return {
        "expected": expected,
        "observed": len(paths),
        "valid": len(valid),
        "complete": expected > 0 and len(paths) == expected and len(valid) == expected,
        "missing_or_invalid": expected - len(valid),
    }


def release_reconciliation_receipt(*, expected_sha: str, actual_sha: str, artifacts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Bind a release verdict to one SHA and complete non-empty artifacts."""
    expected = str(expected_sha).lower()
    actual = str(actual_sha).lower()
    artifact_ok = bool(artifacts) and all(
        isinstance(item, Mapping)
        and str(item.get("sha256") or "").lower()
        and int(item.get("bytes") or 0) > 0
        for item in artifacts
    )
    return {
        "verdict": "PROVEN" if expected == actual and artifact_ok else "UNKNOWN",
        "sha_match": expected == actual,
        "artifact_complete": artifact_ok,
        "paper_only": True,
    }


def collection_campaign_receipt(*, family: str, campaign_id: str, phase: str, epoch: int, source_sha: str) -> dict[str, Any]:
    """Require a resumable, exact-SHA collection campaign descriptor."""
    valid = (
        family == "copy_vault"
        and bool(str(campaign_id).strip())
        and phase == "COLLECT"
        and isinstance(epoch, int)
        and epoch >= 0
        and len(str(source_sha).lower()) == 64
    )
    return {
        "family": family,
        "campaign_id": str(campaign_id),
        "phase": phase,
        "epoch": epoch,
        "source_sha": str(source_sha).lower(),
        "status": "READY" if valid else "UNKNOWN",
        "paper_only": True,
    }


def market_campaign_receipt(*, campaign: Mapping[str, Any]) -> dict[str, Any]:
    """Keep market collection explicit and separate from the active family."""
    return {
        "family": "market_data",
        "status": "DISABLED_BY_SCOPE" if campaign.get("family") != "copy_vault" else "UNKNOWN",
        "source_provenance": bool(campaign.get("source_provenance")),
        "paper_only": True,
    }


def event_intelligence_campaign_receipt(*, campaign: Mapping[str, Any]) -> dict[str, Any]:
    """Accept event intelligence only as a provenance-bearing diagnostic input."""
    provenance = campaign.get("source_provenance")
    return {
        "family": "event_intelligence",
        "status": "DIAGNOSTIC_ONLY" if isinstance(provenance, str) and provenance else "UNKNOWN",
        "source_provenance": provenance if isinstance(provenance, str) else None,
        "paper_only": True,
    }


def worker_failure_verdict(result: Mapping[str, Any] | None, *, durable_ok: bool) -> str:
    """Never turn a crashed unit or failed durable publish into COMPLETE."""
    if not isinstance(result, Mapping) or not durable_ok:
        return "FAIL_CLOSED"
    status = str(result.get("status") or "").upper()
    return "COMPLETE" if status == "COMPLETE" else "FAIL_CLOSED"


def receipt_gate(*, unit_ok: bool, receipt_written: bool, checkpoint_written: bool) -> str:
    """A receipt is publishable only after the unit and checkpoint both succeed."""
    return "PROVEN" if unit_ok and receipt_written and checkpoint_written else "UNKNOWN"


def dispatch_fallback_verdict(*, http_status: int | None, attempts: int) -> str:
    """Report transient GitHub dispatch failures as deferred, never as success."""
    if http_status in {403, 429, 502, 503, 504} and attempts > 0:
        return "DEFERRED_RETRY"
    if http_status == 200:
        return "DISPATCHED"
    return "FAILED"


def workflow_permissions_receipt(*, contents: str, actions: str | None = None) -> dict[str, Any]:
    """Verify a diagnostic workflow cannot write repository state."""
    safe = contents == "read" and actions in (None, "read")
    return {"status": "SAFE" if safe else "UNSAFE", "contents": contents, "actions": actions}


def self_hosted_disabled_receipt(workflow_text: str) -> dict[str, Any]:
    """Require an explicit disabled job and reject self-hosted runner labels."""
    text = str(workflow_text)
    disabled = ("if: $" + "{{ false }}") in text or "if: false" in text
    reachable = "self-hosted" in text.lower() and disabled is False
    return {"status": "DISABLED" if disabled and not reachable else "UNKNOWN", "paper_only": True}


def controller_cadence_receipt(*, interval_minutes: int, empty_run_cost_known: bool) -> str:
    """Keep the hosted watchdog bounded while retaining resumable collection."""
    if isinstance(interval_minutes, bool) or interval_minutes < 5:
        return "UNKNOWN"
    return "PROVEN" if empty_run_cost_known else "MORE_DATA"


def capability_health_receipt(capability: Mapping[str, Any]) -> str:
    """FILE_PRESENT alone is never a healthy/replay-compatible capability."""
    if (
        capability.get("runtime_status") == "HEALTHY"
        and capability.get("status") not in {"FILE_PRESENT", "UNKNOWN"}
        and capability.get("replay_compatible") is True
    ):
        return "PROVEN"
    return "UNKNOWN"


def event_structural_receipt(*, source: str | None, feature: str | None, consumer: str | None, ablation: str | None) -> str:
    """Structural event inventory remains non-economic until all lineage is wired."""
    return "PROVEN" if all(isinstance(item, str) and item.strip() for item in (source, feature, consumer, ablation)) else "STRUCTURAL_ONLY"


def fee_revalidation_receipt(*, schedule_sha256: str | None, as_of: str | None, source: str | None) -> str:
    """Unknown fee schedules stay unknown instead of being silently refreshed."""
    if isinstance(schedule_sha256, str) and len(schedule_sha256) == 64 and as_of and source:
        return "PROVEN"
    return "UNKNOWN"


def fills_pagination_receipt(*, page_size: int, max_pages: int, max_fills: int, dedup_by_identity: bool) -> str:
    """Require bounded pagination and identity-level deduplication for fills."""
    if page_size not in {500, 2000} or max_pages < 1 or max_fills < page_size or not dedup_by_identity:
        return "UNKNOWN"
    return "PROVEN"


def execution_path_receipt(*, reachable_modules: Sequence[str], forbidden_reachable: Sequence[str]) -> dict[str, Any]:
    """Require the audited runtime graph to contain no reachable execution path."""

    reachable = {str(item).strip() for item in reachable_modules if str(item).strip()}
    forbidden = {str(item).strip() for item in forbidden_reachable if str(item).strip()}
    leaked = sorted(reachable & forbidden)
    return {"status": "PROVEN" if not leaked else "REJECTED", "real_execution": False, "forbidden_reachable": leaked, "paper_only": True}


def trading_flag_receipt(*, env: Mapping[str, Any]) -> dict[str, Any]:
    """Allow only an explicit paper/read-only environment contract."""

    if not isinstance(env, Mapping):
        return {"status": "UNKNOWN", "paper_only": True, "real_execution": False}
    safe = env.get("PAPER_ONLY") is True and env.get("READ_ONLY") is True and env.get("LIVE_TRADING") is False
    return {"status": "PROVEN" if safe else "REJECTED", "paper_only": safe, "real_execution": False}


def startup_secret_receipt(*, observed_secret_names: Sequence[str]) -> dict[str, Any]:
    """Startup remains safe only when no private key or signing secret is read."""

    names = [str(item).casefold() for item in observed_secret_names]
    forbidden = [item for item in names if any(token in item for token in ("private_key", "mnemonic", "seed", "signing_secret"))]
    return {"status": "PROVEN" if not forbidden else "REJECTED", "secret_reads": forbidden, "paper_only": True, "real_execution": False}


def legacy_import_receipt(*, exchange_call_detected: bool, import_side_effect_free: bool) -> dict[str, Any]:
    """Legacy compatibility imports may not trigger exchange calls during import."""

    valid = exchange_call_detected is False and import_side_effect_free is True
    return {"status": "PROVEN" if valid else "REJECTED", "exchange_call_detected": exchange_call_detected, "paper_only": True, "real_execution": False}


def subprocess_binary_receipt(*, command: Sequence[str]) -> dict[str, Any]:
    """Reject subprocesses that could launch trading or signing binaries."""

    text = " ".join(str(item).casefold() for item in command)
    forbidden = any(
        token in text
        for token in (
            "trade",
            "trading",
            "order",
            "sign",
            "withdraw",
            "deposit",
            "mainnet",
        )
    )
    return {"status": "REJECTED" if forbidden else "PROVEN", "forbidden_command": forbidden, "paper_only": True, "real_execution": False}


def backtest_risk_gate_receipt(*, risk_gate_rechecked: bool, paper_mode: bool) -> dict[str, Any]:
    """A replay/backtest cannot bypass the canonical risk gate."""

    valid = risk_gate_rechecked is True and paper_mode is True
    return {"status": "PROVEN" if valid else "REJECTED", "risk_gate_rechecked": risk_gate_rechecked, "paper_only": True, "real_execution": False}


def capital_allocation_receipt(*, position_notionals_usd: Sequence[Any], capital_usd: Any) -> dict[str, Any]:
    """Bound aggregate open positions by canonical paper capital."""

    try:
        capital = float(capital_usd)
        notionals = [float(value) for value in position_notionals_usd]
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNKNOWN", "paper_only": True, "real_execution": False}
    if not all(math.isfinite(value) and value >= 0 for value in [capital, *notionals]) or capital <= 0:
        return {"status": "UNKNOWN", "paper_only": True, "real_execution": False}
    total = sum(notionals)
    return {"status": "PROVEN" if total <= capital else "REJECTED", "total_notional_usd": total, "capital_usd": capital, "paper_only": True, "real_execution": False}


def correlated_exposure_receipt(*, exposures_by_cluster: Mapping[str, Any], max_exposure_usd: Any) -> dict[str, Any]:
    """Aggregate correlated positions before applying the exposure cap."""

    try:
        cap = float(max_exposure_usd)
        values = {str(key): float(value) for key, value in exposures_by_cluster.items()}
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNKNOWN", "paper_only": True, "real_execution": False}
    if not all(math.isfinite(value) and value >= 0 for value in [cap, *values.values()]) or cap <= 0:
        return {"status": "UNKNOWN", "paper_only": True, "real_execution": False}
    return {"status": "PROVEN" if all(value <= cap for value in values.values()) else "REJECTED", "exposure_by_cluster": values, "max_exposure_usd": cap, "paper_only": True, "real_execution": False}


def leverage_fresh_mark_receipt(*, leverage: Any, max_leverage: Any, mark_age_ms: Any, max_mark_age_ms: Any) -> dict[str, Any]:
    """Reject leverage checks performed on a stale mark."""

    try:
        lev, cap, age, max_age = float(leverage), float(max_leverage), float(mark_age_ms), float(max_mark_age_ms)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNKNOWN", "paper_only": True, "real_execution": False}
    valid = all(math.isfinite(value) for value in (lev, cap, age, max_age)) and lev >= 0 and cap > 0 and 0 <= age <= max_age
    return {"status": "PROVEN" if valid and lev <= cap else "REJECTED", "mark_fresh": valid, "paper_only": True, "real_execution": False}


def daily_loss_persistence_receipt(*, previous_loss_usd: Any, current_loss_usd: Any, persisted: bool) -> dict[str, Any]:
    """Carry the daily loss ledger across restart instead of resetting it."""

    try:
        previous, current = float(previous_loss_usd), float(current_loss_usd)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNKNOWN", "paper_only": True, "real_execution": False}
    valid = all(math.isfinite(value) and value >= 0 for value in (previous, current)) and persisted is True and current >= previous
    return {"status": "PROVEN" if valid else "REJECTED", "previous_loss_usd": previous, "current_loss_usd": current, "paper_only": True, "real_execution": False}


__all__ = [
    "MAX_PATCH_BYTES",
    "atomic_publish_bytes",
    "partition_mapping",
    "measured_patch_reuse",
    "sha256_file_receipt",
    "classify_delta_state",
    "official_entrypoint_receipt",
    "coverage_shard_receipt",
    "release_reconciliation_receipt",
    "collection_campaign_receipt",
    "market_campaign_receipt",
    "event_intelligence_campaign_receipt",
    "worker_failure_verdict",
    "receipt_gate",
    "dispatch_fallback_verdict",
    "workflow_permissions_receipt",
    "self_hosted_disabled_receipt",
    "controller_cadence_receipt",
    "capability_health_receipt",
    "event_structural_receipt",
    "fee_revalidation_receipt",
    "fills_pagination_receipt",
    "execution_path_receipt",
    "trading_flag_receipt",
    "startup_secret_receipt",
    "legacy_import_receipt",
    "subprocess_binary_receipt",
    "backtest_risk_gate_receipt",
    "capital_allocation_receipt",
    "correlated_exposure_receipt",
    "leverage_fresh_mark_receipt",
    "daily_loss_persistence_receipt",
]
