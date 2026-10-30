"""Deterministic bounded adapters for resumable GitHub-hosted campaigns."""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hl_observer.ops.echec_silencieux import noter as _noter_echec

ROOT = Path(__file__).resolve().parents[3]
ECONOMIC_KINDS = frozenset({"backtest", "oos", "forward_paper", "module_pnl_proof", "scoreboard"})
HISTORICAL_BACKFILL_AUDIT_SCHEMA = "alina.copy_vault.historical_backfill_audit.v1"
MAX_DURABLE_HISTORY_AUDIT_BYTES = 1_048_576
ADAPTER_DIAGNOSTIC_SCHEMA = "alina.copy_vault.adapter_unit_diagnostic.v1"
ANALYSIS_STAGE_BY_KIND = {
    "replay": "REPLAY",
    "backtest": "BACKTEST",
    "oos": "OOS",
    "forward_paper": "FORWARD_PAPER",
    "module_pnl_proof": "PNL_PROOF",
    "scoreboard": "SCOREBOARD",
}


def _analysis_stage(kind: str) -> str | None:
    return ANALYSIS_STAGE_BY_KIND.get(str(kind))


@dataclass(frozen=True)
class AdapterContext:
    campaign_id: str
    kind: str
    unit_id: str
    soft_deadline_epoch: float
    partition: dict[str, Any]


@dataclass(frozen=True)
class AdapterResult:
    status: str
    sha256: str
    payload: dict[str, Any]
    progressed: bool = True


def _digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _bounded_float(value: Any, default: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(1.0, min(parsed, maximum))


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _exact_nonnegative_int(value: Any) -> int | None:
    if type(value) is not int or value < 0:
        return None
    return value


def _exact_nonnegative_int_map(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, int] = {}
    for key, raw_count in value.items():
        count = _exact_nonnegative_int(raw_count)
        if not isinstance(key, str) or not key or count is None:
            return None
        result[key] = count
    return dict(sorted(result.items()))


def _validated_subscription_attempts(
    value: Any,
    *,
    expected_type: str | None = None,
) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or len(value) > 256:
        return None
    allowed_types = {"userFills", "l2Book"}
    allowed_statuses = {
        "PENDING",
        "ACTIVE",
        "REJECTED",
        "TIMED_OUT",
        "INVALIDATED",
        "SEND_FAILED",
    }
    time_fields = (
        "acknowledged_at_ms",
        "timed_out_at_ms",
        "invalidated_at_ms",
    )
    result: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, dict):
            return None
        kind = row.get("type")
        identity = row.get("identity")
        connection_id = row.get("connection_id")
        status = row.get("status")
        sent_at_ms = _exact_nonnegative_int(row.get("sent_at_ms"))
        if (
            not isinstance(kind, str)
            or kind not in allowed_types
            or (expected_type is not None and kind != expected_type)
            or not isinstance(identity, str)
            or not identity
            or not isinstance(connection_id, str)
            or not connection_id
            or not isinstance(status, str)
            or status not in allowed_statuses
            or sent_at_ms is None
            or type(row.get("late_ack")) is not bool
        ):
            return None
        item: dict[str, Any] = {
            "type": kind,
            "identity": identity,
            "connection_id": connection_id,
            "status": status,
            "sent_at_ms": sent_at_ms,
            "late_ack": row["late_ack"],
        }
        for field in time_fields:
            raw_time = row.get(field)
            if raw_time is not None and _exact_nonnegative_int(raw_time) is None:
                return None
            item[field] = raw_time
        error = row.get("error")
        if error is not None and not isinstance(error, str):
            return None
        item["error"] = error[:256] if isinstance(error, str) else None
        previous_status = row.get("status_before_invalidation")
        if previous_status is not None:
            if not isinstance(previous_status, str) or previous_status not in {
                "PENDING",
                "ACTIVE",
                "TIMED_OUT",
            }:
                return None
            item["status_before_invalidation"] = previous_status
        invalidation_reason = row.get("invalidation_reason")
        if invalidation_reason is not None:
            if not isinstance(invalidation_reason, str):
                return None
            item["invalidation_reason"] = invalidation_reason[:128]
        result.append(item)
    return result


def _validated_subscription_attempt_map(
    value: Any,
    *,
    expected_type: str,
) -> dict[str, list[dict[str, Any]]] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, list[dict[str, Any]]] = {}
    for identity, attempts in value.items():
        if not isinstance(identity, str) or not identity:
            return None
        validated = _validated_subscription_attempts(
            attempts,
            expected_type=expected_type,
        )
        if validated is None or any(
            attempt["identity"] != identity for attempt in validated
        ):
            return None
        result[identity] = validated
    return dict(sorted(result.items()))


def _validated_l2_diagnostic_gap(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    reason = value.get("reason")
    reasons = value.get("reasons")
    continuity = value.get("continuity_proven")
    if (
        not isinstance(reason, str)
        or not reason
        or not isinstance(reasons, list)
        or any(not isinstance(item, str) or not item for item in reasons)
        or type(continuity) is not bool
    ):
        return None
    result: dict[str, Any] = {
        "reason": reason[:128],
        "reasons": [item[:128] for item in reasons[:64]],
        "continuity_proven": continuity,
    }
    gap_epoch = value.get("l2_gap_epoch")
    if gap_epoch is not None and _exact_nonnegative_int(gap_epoch) is None:
        return None
    result["l2_gap_epoch"] = gap_epoch
    for key in (
        "start_after_receive_ts_ms",
        "detected_at_ms",
        "last_detected_at_ms",
        "recovery_at_ms",
    ):
        raw = value.get(key)
        if raw is not None and _exact_nonnegative_int(raw) is None:
            return None
        result[key] = raw
    for key in ("connection_id", "recovery_connection_id"):
        raw = value.get(key)
        if raw is not None and not isinstance(raw, str):
            return None
        result[key] = raw[:128] if isinstance(raw, str) else None
    return result


def _validated_l2_diagnostics_receipt(value: Any) -> dict[str, Any] | None:
    """Copy bounded L2 health evidence into the durable campaign receipt."""
    if not isinstance(value, dict):
        return None

    def optional_count(source: Mapping[str, Any], key: str) -> int | None:
        raw = source.get(key)
        if raw is None:
            return None
        count = _exact_nonnegative_int(raw)
        if count is None:
            raise ValueError(f"invalid L2 counter: {key}")
        return count

    def optional_count_map(
        source: Mapping[str, Any], key: str
    ) -> dict[str, int] | None:
        raw = source.get(key)
        if raw is None:
            return None
        result = _exact_nonnegative_int_map(raw)
        if result is None:
            raise ValueError(f"invalid L2 counter map: {key}")
        return result

    try:
        result: dict[str, Any] = {
            key: optional_count(value, key)
            for key in (
                "received_frames",
                "candidate_l2_frames",
                "accepted_frames",
                "rejected_frames",
                "ignored_frames",
                "duplicate_snapshots",
                "reconnects",
                "heartbeats_sent",
                "heartbeats_received",
                "subscription_ack_mismatches",
                "invalid_subscription_acks",
                "connection_events_dropped",
                "unknown_market_rejections_dropped",
            )
        }
        for key in (
            "rejected_by_reason",
            "ignored_by_reason",
        ):
            result[key] = optional_count_map(value, key)

        requested = value.get("requested_markets")
        if requested is not None and (
            not isinstance(requested, list)
            or any(not isinstance(coin, str) or not coin for coin in requested)
        ):
            return None
        result["requested_markets"] = (
            sorted(set(requested)) if isinstance(requested, list) else None
        )

        markets = value.get("markets")
        if not isinstance(markets, dict):
            return None
        market_rows: dict[str, Any] = {}
        allowed_subscription_statuses = {
            "UNKNOWN", "PENDING", "ACTIVE", "REJECTED", "TIMED_OUT",
            "INVALIDATED", "SEND_FAILED",
        }
        allowed_coverage_statuses = {
            "GAP_OPEN", "SNAPSHOTS_CONTINUITY_UNPROVEN", "NO_SNAPSHOT",
            "NO_MARKET_STATE",
        }
        allowed_proof_window_statuses = {
            "UNAVAILABLE", "UNPROVEN", "UNMEASURABLE",
        }
        for coin, row in markets.items():
            if not isinstance(coin, str) or not coin or not isinstance(row, dict):
                return None
            market: dict[str, Any] = {
                key: optional_count(row, key)
                for key in (
                    "received",
                    "candidate_l2_frames",
                    "accepted",
                    "rejected",
                    "duplicates",
                    "l2_gap_epoch",
                    "subscription_attempts_dropped",
                    "gaps_dropped",
                )
            }
            for key in ("rejected_by_reason", "ignored_by_reason"):
                market[key] = optional_count_map(row, key)
            for key in (
                "last_receive_ts_ms",
                "last_receive_age_ms",
                "last_exchange_ts_ms",
            ):
                market[key] = optional_count(row, key)
            for key in (
                "subscription_status",
                "coverage_status",
                "proof_window_status",
            ):
                raw = row.get(key)
                allowed = (
                    allowed_subscription_statuses
                    if key == "subscription_status"
                    else (
                        allowed_coverage_statuses
                        if key == "coverage_status"
                        else allowed_proof_window_statuses
                    )
                )
                if raw is not None and (not isinstance(raw, str) or raw not in allowed):
                    return None
                market[key] = raw
            connection_id = row.get("last_connection_id")
            if connection_id is not None and not isinstance(connection_id, str):
                return None
            market["last_connection_id"] = connection_id
            continuity = row.get("sequence_continuity_proven")
            if continuity is not None and type(continuity) is not bool:
                return None
            market["sequence_continuity_proven"] = continuity

            attempts_raw = row.get("subscription_attempts")
            attempts = (
                _validated_subscription_attempts(
                    attempts_raw,
                    expected_type="l2Book",
                )
                if attempts_raw is not None
                else None
            )
            if attempts_raw is not None and (
                attempts is None or any(item["identity"] != coin for item in attempts)
            ):
                return None
            market["subscription_attempts"] = attempts

            gaps_raw = row.get("gaps")
            if gaps_raw is None:
                market["gaps"] = None
            else:
                if not isinstance(gaps_raw, list) or len(gaps_raw) > 256:
                    return None
                gaps = [_validated_l2_diagnostic_gap(gap) for gap in gaps_raw]
                if any(gap is None for gap in gaps):
                    return None
                market["gaps"] = gaps
            open_gap_raw = row.get("open_gap")
            open_gap = (
                _validated_l2_diagnostic_gap(open_gap_raw)
                if open_gap_raw is not None
                else None
            )
            if open_gap_raw is not None and open_gap is None:
                return None
            market["open_gap"] = open_gap
            market_rows[coin] = market
        result["markets"] = dict(sorted(market_rows.items()))

        for key in ("connection_events", "unknown_market_rejections"):
            raw_events = value.get(key)
            if raw_events is None:
                result[key] = None
                continue
            if not isinstance(raw_events, list) or len(raw_events) > 256:
                return None
            events: list[dict[str, Any]] = []
            for raw_event in raw_events:
                if not isinstance(raw_event, dict):
                    return None
                event_time = _exact_nonnegative_int(raw_event.get("time_ms"))
                connection_id = raw_event.get("connection_id")
                if (
                    event_time is None
                    or not isinstance(connection_id, str)
                    or not connection_id
                ):
                    return None
                if key == "connection_events":
                    event = raw_event.get("event")
                    raw_coins = raw_event.get("markets")
                    if (
                        not isinstance(event, str)
                        or event not in {"connected", "disconnect"}
                        or not isinstance(raw_coins, list)
                        or any(not isinstance(coin, str) or not coin for coin in raw_coins)
                    ):
                        return None
                    item = {
                        "event": event,
                        "time_ms": event_time,
                        "connection_id": connection_id[:128],
                        "markets": sorted(set(raw_coins)),
                    }
                    error_class = raw_event.get("error_class")
                    if error_class is not None and not isinstance(error_class, str):
                        return None
                    item["error_class"] = (
                        error_class[:128] if isinstance(error_class, str) else None
                    )
                else:
                    reason = raw_event.get("reason")
                    if not isinstance(reason, str) or not reason:
                        return None
                    item = {
                        "time_ms": event_time,
                        "connection_id": connection_id[:128],
                        "reason": reason[:128],
                    }
                events.append(item)
            result[key] = events

        coverage_claim = value.get("coverage_claim")
        if coverage_claim is not None and coverage_claim != "NOT_PROVEN":
            return None
        result["coverage_claim"] = coverage_claim
        proof_window_status = value.get("required_market_proof_window_status")
        if proof_window_status is not None and (
            not isinstance(proof_window_status, str)
            or proof_window_status not in {
                "UNAVAILABLE", "UNPROVEN", "UNMEASURABLE",
            }
        ):
            return None
        result["required_market_proof_window_status"] = proof_window_status
        freshness_policy = value.get("freshness_policy")
        if freshness_policy is not None and not isinstance(freshness_policy, str):
            return None
        result["freshness_policy"] = freshness_policy
        return result
    except ValueError:
        return None


def _copy_vault_subscription_receipt(summary: dict[str, Any]) -> dict[str, Any]:
    raw_l2 = summary.get("l2_diagnostics")
    l2_subscription: dict[str, Any] | None = None
    if isinstance(raw_l2, dict) and isinstance(raw_l2.get("markets"), dict):
        market_rows: dict[str, Any] = {}
        valid = True
        for coin, row in raw_l2["markets"].items():
            if not isinstance(coin, str) or not coin or not isinstance(row, dict):
                valid = False
                break
            status = row.get("subscription_status")
            if status is not None and (
                not isinstance(status, str)
                or status
                not in {
                    "UNKNOWN",
                    "PENDING",
                    "ACTIVE",
                    "REJECTED",
                    "TIMED_OUT",
                    "INVALIDATED",
                    "SEND_FAILED",
                }
            ):
                valid = False
                break
            attempts_raw = row.get("subscription_attempts")
            attempts = (
                _validated_subscription_attempts(
                    attempts_raw,
                    expected_type="l2Book",
                )
                if attempts_raw is not None
                else None
            )
            dropped_raw = row.get("subscription_attempts_dropped")
            dropped = (
                _exact_nonnegative_int(dropped_raw)
                if dropped_raw is not None
                else None
            )
            if (
                attempts_raw is not None
                and (
                    attempts is None
                    or any(attempt["identity"] != coin for attempt in attempts)
                )
            ) or (
                dropped_raw is not None and dropped is None
            ):
                valid = False
                break
            market_rows[coin] = {
                "subscription_status": status,
                "subscription_attempts": attempts,
                "subscription_attempts_dropped": dropped,
            }
        if valid:
            mismatch_count = _exact_nonnegative_int(
                raw_l2.get("subscription_ack_mismatches")
            )
            invalid_ack_count = _exact_nonnegative_int(
                raw_l2.get("invalid_subscription_acks")
            )
            l2_subscription = {
                "subscription_ack_mismatches": mismatch_count,
                "invalid_subscription_acks": invalid_ack_count,
                "markets": dict(sorted(market_rows.items())),
            }

    return {
        "vault_observation_start_ts_ms": _exact_nonnegative_int_map(
            summary.get("vault_observation_start_ts_ms")
        ),
        "vault_subscription_attempts": _validated_subscription_attempt_map(
            summary.get("vault_subscription_attempts"),
            expected_type="userFills",
        ),
        "vault_subscription_attempts_dropped": _exact_nonnegative_int_map(
            summary.get("vault_subscription_attempts_dropped")
        ),
        "subscription_diagnostics": _exact_nonnegative_int_map(
            summary.get("subscription_diagnostics")
        ),
        "l2_diagnostics": _validated_l2_diagnostics_receipt(raw_l2),
        "l2_subscription": l2_subscription,
    }


def _copy_vault_position_snapshot_receipt(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Carry the position-anchor gate into the durable campaign receipt.

    A collection summary may contain valid empty snapshots, but it must never
    turn a missing/failed START or END anchor into an empty position set.  The
    collector owns the detailed per-wallet rows; this adapter only validates
    and carries the compact gate needed by downstream proof stages.
    """
    raw = summary.get("position_snapshot_coverage")
    is_copy_vault_summary = str(summary.get("schema") or "").startswith(
        "alina.copy_vault_cloud_window."
    )
    if raw is None and not is_copy_vault_summary:
        return None
    if not isinstance(raw, Mapping):
        return {
            "status": "MISSING_RECEIPT",
            "requested_wallets": None,
            "proof_eligible": False,
            "proof_blocked": True,
            "proof_block_reason": "POSITION_SNAPSHOT_COVERAGE_MISSING",
            "phases": None,
            "source": "collection_summary.json",
        }

    status = raw.get("status")
    requested_wallets = _exact_nonnegative_int(raw.get("requested_wallets"))
    phases_raw = raw.get("phases")
    phase_receipts: dict[str, Any] = {}
    valid = (
        status in {"UNMEASURABLE_NO_WALLETS", "COMPLETE", "PARTIAL"}
        and requested_wallets is not None
        and raw.get("missing_or_failed_is_not_empty") is True
        and isinstance(phases_raw, Mapping)
    )
    for phase in ("START", "END"):
        phase_raw = phases_raw.get(phase) if isinstance(phases_raw, Mapping) else None
        if not isinstance(phase_raw, Mapping):
            valid = False
            phase_receipts[phase] = None
            continue
        expected = _exact_nonnegative_int(phase_raw.get("expected_wallets"))
        accepted = _exact_nonnegative_int(
            phase_raw.get("valid_snapshots_accepted_for_storage")
        )
        failed = _exact_nonnegative_int(
            phase_raw.get("failed_or_unverified_wallets")
        )
        by_wallet = phase_raw.get("by_wallet")
        phase_status = phase_raw.get("status")
        phase_valid = (
            phase_status in {"UNMEASURABLE_NO_WALLETS", "COMPLETE", "PARTIAL"}
            and expected is not None
            and accepted is not None
            and failed is not None
            and accepted + failed == expected
            and expected == requested_wallets
            and isinstance(by_wallet, list)
            and len(by_wallet) == expected
        )
        if phase_valid:
            seen_vaults: set[str] = set()
            for row in by_wallet:
                if not isinstance(row, Mapping):
                    phase_valid = False
                    break
                vault = str(row.get("vault") or "").strip().lower()
                row_status = row.get("status")
                if (
                    not vault
                    or vault in seen_vaults
                    or row_status not in {
                        "NOT_SENT",
                        "HTTP_ERROR",
                        "TIMEOUT",
                        "REQUEST_ERROR",
                        "INVALID_RESPONSE",
                        "VALID_EMPTY",
                        "VALID_WITH_POSITIONS",
                        "PERSISTENCE_UNVERIFIED",
                    }
                    or type(row.get("accepted_for_storage")) is not bool
                ):
                    phase_valid = False
                    break
                seen_vaults.add(vault)
        valid = valid and phase_valid
        phase_receipts[phase] = {
            "status": phase_status,
            "expected_wallets": expected,
            "valid_snapshots_accepted_for_storage": accepted,
            "failed_or_unverified_wallets": failed,
            "outcomes_by_status": (
                dict(phase_raw.get("outcomes_by_status"))
                if isinstance(phase_raw.get("outcomes_by_status"), Mapping)
                else None
            ),
            "by_wallet": by_wallet if phase_valid else None,
        }

    proof_eligible = valid and status == "COMPLETE" and requested_wallets > 0
    if not valid:
        proof_block_reason = "POSITION_SNAPSHOT_COVERAGE_INVALID"
    elif not proof_eligible:
        proof_block_reason = "POSITION_SNAPSHOT_ANCHOR_MISSING_OR_FAILED"
    else:
        proof_block_reason = None
    return {
        "status": status if valid else "INVALID_RECEIPT",
        "requested_wallets": requested_wallets,
        "proof_eligible": proof_eligible,
        "proof_blocked": not proof_eligible,
        "proof_block_reason": proof_block_reason,
        "phases": phase_receipts,
        "source": "collection_summary.json",
    }


def _output_root(ctx: AdapterContext) -> Path:
    configured = ctx.partition.get("output_root")
    root = Path(str(configured)) if configured else Path.cwd() / "campaign-output"
    return root / ctx.campaign_id / ctx.unit_id


def _workspace(ctx: AdapterContext) -> Path:
    configured = ctx.partition.get("workspace_root")
    if configured:
        return Path(str(configured))
    return Path.cwd() / "campaign-workspaces" / ctx.campaign_id / ctx.unit_id


def _cutoff_ts_ms(value: Any) -> int | None:
    if not value:
        return None
    try:
        from datetime import datetime
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(parsed.timestamp() * 1000)
    except (TypeError, ValueError, OverflowError):
        return None


def _economic_campaign_binding_args(ctx: AdapterContext) -> list[str]:
    """Require the exact frozen SAFE selection identity for economic runs."""
    selection_id = ctx.partition.get("dataset_selection_id")
    if (
        not isinstance(selection_id, str)
        or len(selection_id) != 64
        or any(char not in "0123456789abcdef" for char in selection_id)
    ):
        raise ValueError("economic campaign requires a SHA-256 dataset_selection_id")

    cutoff = ctx.partition.get("collection_cutoff_at_utc")
    if not isinstance(cutoff, str) or not cutoff.endswith("Z") or _cutoff_ts_ms(cutoff) is None:
        raise ValueError("economic campaign requires a valid UTC collection_cutoff_at_utc ending in Z")

    epoch = ctx.partition.get("source_collection_epoch")
    if type(epoch) is not int or epoch < 1:
        raise ValueError("economic campaign requires a positive integer source_collection_epoch")

    return [
        "--dataset-selection-id", selection_id,
        "--collection-cutoff-at-utc", cutoff,
        "--source-collection-epoch", str(epoch),
    ]


def _selection_args(ctx: AdapterContext) -> list[str]:
    args: list[str] = []
    for key, flag in (
        ("families", "--families"),
        ("venues", "--venues"),
        ("symbols", "--symbols"),
    ):
        value = ctx.partition.get(key)
        if value:
            args.extend([flag, str(value)])
    for key, flag in (
        ("start_ts_ms", "--start-ts-ms"),
        ("end_ts_ms", "--end-ts-ms"),
        ("max_shards", "--max-shards"),
    ):
        value = ctx.partition.get(key)
        if value is not None:
            args.extend([flag, str(int(value))])
    if ctx.partition.get("end_ts_ms") is None:
        cutoff = _cutoff_ts_ms(ctx.partition.get("collection_cutoff_at_utc"))
        if cutoff is not None:
            args.extend(["--end-ts-ms", str(cutoff)])
    for key, flag in (
        ("dataset_selection_id", "--dataset-selection-id"),
        ("collection_cutoff_at_utc", "--collection-cutoff-at-utc"),
    ):
        value = ctx.partition.get(key)
        if value:
            args.extend([flag, str(value)])
    if ctx.partition.get("source_collection_epoch") is not None:
        args.extend(["--source-collection-epoch", str(int(ctx.partition["source_collection_epoch"]))])
    return args


def _dataset_bridge_command(
    ctx: AdapterContext,
    workspace: Path,
    *,
    action: str,
) -> list[str]:
    if action not in {"plan", "materialize"}:
        raise ValueError("dataset bridge action must be plan or materialize")
    command = [
        sys.executable,
        "-m",
        "hl_observer.ops.v2_dataset_bridge",
        action,
        "--output",
        str(workspace),
        *_selection_args(ctx),
    ]
    if ctx.kind == "replay" or ctx.kind in ECONOMIC_KINDS:
        command.append("--require-trade-events")
    return command


def _materialize_command(ctx: AdapterContext, workspace: Path) -> list[str]:
    return _dataset_bridge_command(ctx, workspace, action="materialize")


def _economic_proof_status(workspace: Path) -> str | None:
    """Read the semantic PnL-proof verdict produced by the audit.

    This is intentionally separate from subprocess success. A valid audit may
    conclude that evidence is incomplete/unmeasurable without meaning that the
    orchestration itself crashed.
    """
    path = (
        workspace
        / "runtime"
        / "reports"
        / "economic_campaigns"
        / "HYPERSMART_ECONOMIC_PROOF_AUDIT.json"
    )
    if not path.is_file():
        return None
    try:
        audit = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if (
        audit.get("schema_version") != "hypersmart.economic_proof_audit.v1"
        or audit.get("paper_read_only") is not True
        or audit.get("real_execution") is not False
    ):
        return None
    if audit.get("missing_families") or audit.get("all_ledgers_valid") is not True:
        return "UNMEASURABLE"
    if audit.get("all_objectives_met") is True:
        return "PASS"
    classifications = {
        str(row.get("classification") or "")
        for row in (audit.get("families") or [])
        if isinstance(row, dict)
    }
    if "INCOMPLETE" in classifications:
        return "MORE_DATA"
    return "KILL"


def build_command(ctx: AdapterContext) -> tuple[list[str], Path | None]:
    """Build one real bounded command for the requested campaign kind."""
    out = _output_root(ctx)
    version = str(
        ctx.partition.get("code_sha")
        or ctx.partition.get("collector_version")
        or "campaign"
    )
    run_id = str(
        ctx.partition.get("collection_run_id")
        or f"{ctx.campaign_id}-{ctx.unit_id}"
    )
    py = sys.executable

    if ctx.kind == "market_collection":
        duration = _bounded_float(ctx.partition.get("duration_s"), 3600.0, 18_000.0)
        coins = str(ctx.partition.get("coins") or "BTC,ETH,SOL")
        return [
            py,
            str(ROOT / "tools" / "collect_cloud_window.py"),
            "--output",
            str(out),
            "--coins",
            coins,
            *(
                ["--plan-file", str(ctx.partition["plan_file"])]
                if ctx.partition.get("plan_file")
                else []
            ),
            "--duration-s",
            str(duration),
            "--collector-version",
            version,
            "--collection-run-id",
            run_id,
            "--rotate-mb",
            str(_bounded_int(ctx.partition.get("rotate_mb"), 64, 1, 512)),
            "--require-l2",
        ], out

    if ctx.kind == "copy_vault_collection":
        duration = _bounded_float(ctx.partition.get("duration_s"), 3600.0, 18_000.0)
        max_vaults = _bounded_int(ctx.partition.get("max_vaults"), 10, 1, 100_000)
        shard_count = _bounded_int(ctx.partition.get("vault_shard_count"), 1, 1, 10_000)
        shard_index = _bounded_int(
            ctx.partition.get("vault_shard_index"),
            0,
            0,
            max(0, shard_count - 1),
        )
        mode = str(ctx.partition.get("copy_vault_mode") or "legacy_sharded_ws")
        raw_max_ws_vaults = ctx.partition.get("max_ws_vaults", 10)
        try:
            requested_max_ws_vaults = int(raw_max_ws_vaults)
        except (TypeError, ValueError, OverflowError):
            requested_max_ws_vaults = 10
        if not 1 <= requested_max_ws_vaults <= 10:
            raise ValueError(
                "copy-vault two-speed mode allows 1..10 unique WS users per IP"
            )
        max_ws_vaults = requested_max_ws_vaults
        if mode == "two_speed_broad_rest_priority_ws":
            if shard_count != 1 or shard_index != 0:
                raise ValueError("two-speed Copy-Vault mode requires one broad universe lane")
        else:
            users_in_largest_lane = (max_vaults + shard_count - 1) // shard_count
            if users_in_largest_lane > 10:
                raise ValueError(
                    "copy-vault partition exceeds Hyperliquid 10 unique users per IP"
                )
        cmd = [
            py,
            str(ROOT / "tools" / "collect_cloud_copy_vault.py"),
            "--output",
            str(out),
            "--duration-s",
            str(duration),
            "--collector-version",
            version,
            "--collection-run-id",
            run_id,
            "--max-vaults",
            str(max_vaults),
            "--vault-shard-count",
            str(shard_count),
            "--vault-shard-index",
            str(shard_index),
            "--max-ws-vaults",
            str(max_ws_vaults),
            "--history-lookback-hours",
            str(_bounded_float(
                ctx.partition.get("history_lookback_hours"),
                72.0,
                72.0,
            )),
            *(
                ["--two-speed"]
                if mode == "two_speed_broad_rest_priority_ws"
                else []
            ),
            "--rotate-mb",
            str(_bounded_int(ctx.partition.get("rotate_mb"), 64, 1, 512)),
        ]
        selection = ctx.partition.get("selection_file")
        if selection:
            selection_path = Path(str(selection))
            if not selection_path.is_file():
                raise ValueError("copy-vault frozen selection file is missing")
            expected_sha = str(ctx.partition.get("selection_sha256") or "").lower()
            if expected_sha:
                actual_sha = hashlib.sha256(selection_path.read_bytes()).hexdigest()
                if actual_sha != expected_sha:
                    raise ValueError("copy-vault frozen selection digest mismatch")
            cmd.extend(["--selection-file", str(selection_path)])
        return cmd, out

    if ctx.kind == "official_archive_collection":
        venue = str(ctx.partition.get("venue") or "binance").lower()
        if venue not in {"binance", "bybit", "okx"}:
            raise ValueError("official archive venue must be binance, bybit, or okx")
        coin = str(ctx.partition.get("coin") or "BTC").upper()
        symbol = str(ctx.partition.get("symbol") or f"{coin}USDT").upper()
        start_date = str(ctx.partition.get("start_date") or "")
        if not start_date:
            raise ValueError("official archive campaign requires start_date")
        source_url = str(ctx.partition.get("source_url") or "").strip()
        if venue == "okx" and not source_url:
            raise ValueError("OKX official archive campaign requires source_url")
        stream_type = str(ctx.partition.get("stream_type") or "").strip()
        command = [
            py,
            str(ROOT / "tools" / "collect_official_archive_backfill.py"),
            "--venue",
            venue,
            "--coin",
            coin,
            "--symbol",
            symbol,
            "--start-date",
            start_date,
            "--end-date",
            str(ctx.partition.get("end_date") or start_date),
            "--output",
            str(out),
            "--collector-version",
            version,
            "--collection-run-id",
            run_id,
            "--max-days",
            str(_bounded_int(ctx.partition.get("max_days"), 1, 1, 3)),
            "--max-events-per-day",
            str(
                _bounded_int(
                    ctx.partition.get("max_events_per_day"),
                    0,
                    0,
                    25_000_000,
                )
            ),
        ]
        if stream_type:
            command.extend(["--stream-type", stream_type])
        if source_url:
            command.extend(["--source-url", source_url])
        return command, out / "bundle"

    if ctx.kind == "event_intelligence_collection":
        return [
            py,
            str(ROOT / "tools" / "collect_event_intelligence_v2.py"),
            "--output",
            str(out),
            "--collector-version",
            version,
            "--collection-run-id",
            run_id,
        ], out

    workspace = _workspace(ctx)
    if ctx.kind == "replay":
        # The dedicated resume-proof replay campaign deliberately splits one
        # canonical replay into two useful fresh-runner units: unit 0 freezes and
        # verifies the exact SAFE selection without materializing it; unit 1
        # restores from durable Dataset V2 and materializes that same selection.
        # No completed replay/materialization work is repeated across segments.
        if ctx.partition.get("resume_proof") is True and int(ctx.partition.get("chunk_index") or 0) == 0:
            return _dataset_bridge_command(ctx, workspace, action="plan"), workspace
        return _materialize_command(ctx, workspace), workspace

    if ctx.kind in ECONOMIC_KINDS:
        binding_args = _economic_campaign_binding_args(ctx)
        return [
            py,
            str(ROOT / "tools" / "run_economic_objective_campaigns.py"),
            "--root",
            str(workspace),
            "--no-start-collection",
            "--analysis-stage",
            _analysis_stage(ctx.kind) or str(ctx.kind).upper(),
            *binding_args,
        ], workspace

    raise ValueError(f"unsupported campaign kind: {ctx.kind}")


def _run(
    runner: Callable[..., Any],
    cmd: list[str],
    *,
    timeout: int,
    analysis_stage: str | None = None,
) -> Any:
    env = os.environ.copy()
    if analysis_stage:
        env["ALINA_ANALYSIS_STAGE"] = analysis_stage
    return runner(
        cmd,
        capture_output=True,
        text=True,
        timeout=max(1, int(timeout)),
        check=False,
        cwd=str(ROOT),
        env=env,
    )


def _text_tail(value: Any, limit: int = 8000) -> str:
    """Normalize captured subprocess output without allowing unbounded growth."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[-limit:]
    return str(value)[-limit:]


def _failure_payload(cmd: list[str], cp: Any) -> dict[str, Any]:
    stdout = _text_tail(getattr(cp, "stdout", ""))
    stderr = _text_tail(getattr(cp, "stderr", ""))
    combined = (stdout + "\n" + stderr).lower()
    category = (
        "TEMPORARY_EXTERNAL"
        if any(
            token in combined
            for token in (
                "timeout",
                "temporar",
                "503",
                "502",
                "connection reset",
                "rate limit",
                "temporary external",
            )
        )
        else "QUALITY"
    )
    return {
        "status": "FAILED",
        "reason": "adapter_failed",
        "failure_category": category,
        "returncode": int(getattr(cp, "returncode", 1) or 1),
        "command": cmd[:4],
        "stdout": stdout,
        "stderr": stderr,
    }


def _collection_checkpoint_metrics(output_root: Path) -> dict[str, Any]:
    """Read compact exact counters from one completed collection bundle."""
    summary_path = output_root / "collection_summary.json"
    index_path = output_root / "BUNDLE_INDEX.json"
    summary: dict[str, Any] = {}
    index: dict[str, Any] = {}
    summary_valid = False
    index_valid = False
    try:
        loaded = json.loads(summary_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            summary = loaded
            summary_valid = True
    except (OSError, ValueError, TypeError) as exc:
        _noter_echec("control_plane/campaign_adapters.py:collection_summary", exc)
    try:
        loaded = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            index = loaded
            index_valid = True
    except (OSError, ValueError, TypeError) as exc:
        _noter_echec("control_plane/campaign_adapters.py:bundle_index", exc)

    trade_count = 0
    record_count = 0
    compressed_bytes = 0
    uncompressed_bytes = 0
    uncompressed_exact_shards = 0
    bbo_frames = 0
    l2_manifest_frames = 0
    manifest_count = 0
    trade_shards = 0
    trade_shards_exact = 0
    historical_snapshot_shards = 0
    historical_fill_observations = 0
    historical_snapshot_shards_exact = 0
    manifest_paths = index.get("manifests")
    manifest_inventory_complete = isinstance(manifest_paths, list)
    seen_manifest_paths: set[str] = set()
    if isinstance(manifest_paths, list):
        for rel in manifest_paths:
            if not isinstance(rel, str) or not rel:
                manifest_inventory_complete = False
                continue
            if rel in seen_manifest_paths:
                manifest_inventory_complete = False
                continue
            seen_manifest_paths.add(rel)
            relative_path = Path(rel)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                manifest_inventory_complete = False
                continue
            try:
                bundle_root = output_root.resolve(strict=True)
                manifest_path = (output_root / relative_path).resolve(strict=True)
                manifest_path.relative_to(bundle_root)
                row = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                manifest_inventory_complete = False
                continue
            if not isinstance(row, dict):
                manifest_inventory_complete = False
                continue
            manifest_count += 1
            raw_records = row.get("record_count")
            if raw_records is None:
                raw_records = row.get("event_count")
            records = _exact_nonnegative_int(raw_records)
            if records is None:
                manifest_inventory_complete = False
                records = 0
            record_count += records
            compressed_bytes += _bounded_int(row.get("bytes"), 0, 0, 2**63 - 1)
            if row.get("uncompressed_size_exact") is True:
                uncompressed_exact_shards += 1
                uncompressed_bytes += _bounded_int(
                    row.get("uncompressed_bytes"), 0, 0, 2**63 - 1
                )
            family = str(row.get("family") or "").lower()
            if family == "copy_vault_snapshot":
                historical_snapshot_shards += 1
                if row.get("historical_fill_observation_count_exact") is True:
                    historical_snapshot_shards_exact += 1
                    historical_fill_observations += _bounded_int(
                        row.get("historical_fill_observation_count"),
                        0,
                        0,
                        2**63 - 1,
                    )
            if not family:
                manifest_inventory_complete = False
            if family in {"l2book", "copy_vault_l2", "native_market"}:
                l2_manifest_frames += records
            elif family == "bbo":
                bbo_frames += records
            if family in {
                "trades",
                "agg_trades",
                "fills",
                "userfills",
                "user_fills",
                "copy_vault_fills",
            }:
                trade_shards += 1
                if row.get("trade_count_exact") is True:
                    trade_shards_exact += 1
                    trade_count += _bounded_int(
                        row.get("trade_count"), 0, 0, 2**63 - 1
                    )

    declared_shards = _exact_nonnegative_int(index.get("shard_count"))
    safe_shards = _exact_nonnegative_int(index.get("safe_count"))
    partial_shards = _exact_nonnegative_int(index.get("partial_count"))
    rejected_shards = _exact_nonnegative_int(index.get("reject_count"))
    category_counts_complete = all(
        value is not None
        for value in (declared_shards, safe_shards, partial_shards, rejected_shards)
    ) and safe_shards + partial_shards + rejected_shards == declared_shards
    manifest_inventory_complete = (
        manifest_inventory_complete
        and index_valid
        and declared_shards == len(manifest_paths)
        and manifest_count == len(manifest_paths)
        and category_counts_complete
    )

    def exact_queue_drop_total(value: Any) -> int | None:
        if type(value) is int and value >= 0:
            return value
        if isinstance(value, dict):
            counts = [_exact_nonnegative_int(item) for item in value.values()]
            if all(count is not None for count in counts):
                return sum(counts)
        return None

    drops_source = summary.get("queue_drops")
    if "queue_drops" not in summary and "queue_drops" in index:
        drops_source = index.get("queue_drops")
    queue_drops = exact_queue_drop_total(drops_source)
    accepted_frames = _exact_nonnegative_int(summary.get("accepted_frames"))
    persisted_frames = _exact_nonnegative_int(summary.get("persisted_frames"))
    l2_frames_observed = _exact_nonnegative_int(summary.get("l2_frames"))
    l2_frames_manifest = l2_manifest_frames if manifest_inventory_complete else None
    l2_frames_reconciled = (
        l2_frames_observed is None
        or l2_frames_manifest is None
        or l2_frames_observed == l2_frames_manifest
    )
    l2_frames = (
        l2_frames_manifest
        if l2_frames_observed is None
        else l2_frames_observed
        if l2_frames_reconciled
        else None
    )
    bbo_frames_exact = bbo_frames if manifest_inventory_complete else None
    frame_counter_consistent = (
        manifest_inventory_complete
        and accepted_frames is not None
        and persisted_frames is not None
        and accepted_frames >= persisted_frames
        and persisted_frames == record_count
    )
    frame_metrics_complete = (
        summary_valid
        and manifest_inventory_complete
        and frame_counter_consistent
        and queue_drops is not None
        and l2_frames is not None
        and bbo_frames_exact is not None
        and l2_frames_reconciled
    )

    duration_raw = summary.get("duration_s")
    duration_s = (
        float(duration_raw)
        if type(duration_raw) in (int, float)
        and math.isfinite(duration_raw)
        and duration_raw >= 0
        else None
    )

    metrics = {
        "started_at_ms": _exact_nonnegative_int(summary.get("started_at_ms")),
        "ended_at_ms": _exact_nonnegative_int(summary.get("ended_at_ms")),
        "duration_s": duration_s,
        "trade_count_observed": trade_count,
        "trade_count_coverage_complete": (
            manifest_inventory_complete and trade_shards == trade_shards_exact
        ),
        "trade_shard_count": trade_shards,
        "trade_shards_exact": trade_shards_exact,
        "historical_fill_observations": historical_fill_observations,
        "historical_snapshot_shards": historical_snapshot_shards,
        "historical_snapshot_shards_exact": historical_snapshot_shards_exact,
        "historical_fill_observation_coverage_complete": (
            manifest_inventory_complete
            and historical_snapshot_shards == historical_snapshot_shards_exact
        ),
        "record_count_observed": record_count,
        "accepted_frames": accepted_frames,
        "persisted_frames": persisted_frames,
        "l2_frames": l2_frames,
        "l2_frames_observed": l2_frames_observed,
        "l2_frames_manifest_records": l2_frames_manifest,
        "l2_frames_reconciled": l2_frames_reconciled,
        "frame_counter_consistent": frame_counter_consistent,
        "bbo_frames": bbo_frames_exact,
        "queue_drops": queue_drops,
        "frame_metrics_complete": frame_metrics_complete,
        "manifest_inventory_complete": manifest_inventory_complete,
        "shard_count": declared_shards,
        "safe_count": safe_shards,
        "partial_count": partial_shards,
        "reject_count": rejected_shards,
        "compressed_bytes": compressed_bytes,
        "uncompressed_bytes": uncompressed_bytes,
        "uncompressed_size_coverage_complete": (
            manifest_inventory_complete
            and manifest_count == uncompressed_exact_shards
        ),
        "basis": "published_bundle_manifests",
    }
    if any(
        key in summary
        for key in (
            "vault_observation_start_ts_ms",
            "vault_subscription_attempts",
            "vault_subscription_attempts_dropped",
            "subscription_diagnostics",
            "l2_diagnostics",
        )
    ):
        metrics["copy_vault_subscription"] = _copy_vault_subscription_receipt(
            summary
        )
    position_snapshot_receipt = _copy_vault_position_snapshot_receipt(summary)
    if position_snapshot_receipt is not None:
        metrics["copy_vault_position_snapshots"] = position_snapshot_receipt
        # This is deliberately a separate gate from frame/shard coverage:
        # market data can be complete while the wallet state anchor is not.
        metrics["position_snapshot_proof_blocked"] = (
            position_snapshot_receipt["proof_blocked"] is True
        )
    if "historical_backfill" in index:
        raw_reports = index.get("historical_backfill")
        audit: dict[str, Any] = {
            "schema": HISTORICAL_BACKFILL_AUDIT_SCHEMA,
            "source": "BUNDLE_INDEX.json",
            "status": "INVALID_SOURCE",
            "report_count": 0,
            "reports_sha256": None,
            "reports": {},
        }
        if isinstance(raw_reports, dict) and all(
            isinstance(address, str) and isinstance(report, dict)
            for address, report in raw_reports.items()
        ):
            reports = raw_reports
            serialized = json.dumps(
                reports,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            audit["report_count"] = len(reports)
            audit["reports_sha256"] = hashlib.sha256(serialized).hexdigest()
            audit["reports_bytes"] = len(serialized)
            if len(serialized) <= MAX_DURABLE_HISTORY_AUDIT_BYTES:
                audit["status"] = "COMPLETE"
                audit["reports"] = reports
            else:
                audit["status"] = "OVERSIZE_FAIL_CLOSED"
        metrics["historical_backfill_audit"] = audit
    return metrics


def _exact_count_from_sources(
    sources: list[Any],
    keys: tuple[str, ...],
) -> int | None:
    """Return a count only when an authoritative source gives an exact integer."""
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in keys:
            if key not in source:
                continue
            value = _exact_nonnegative_int(source.get(key))
            if value is not None:
                return value
    return None


def _checkpoint_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_durable_checkpoint(
    ctx: AdapterContext,
    output_root: Path | None,
) -> dict[str, Any] | None:
    """Expose a checkpoint only when its durable identity is verifiable.

    A timeout must never turn an in-memory cursor into a resume claim.  The
    adapter may receive a checkpoint receipt from the orchestrator or a path
    plus expected SHA-256 in the partition.  A path is accepted only inside
    the unit workspace/output and only when the bytes match the expected hash.
    """
    partition = ctx.partition
    raw = partition.get("last_durable_checkpoint")
    if raw is None:
        raw = partition.get("durable_checkpoint")
    if raw is None and partition.get("checkpoint_path") is not None:
        raw = {
            "id": partition.get("checkpoint_id"),
            "path": partition.get("checkpoint_path"),
            "sha256": partition.get("checkpoint_sha256"),
        }

    if isinstance(raw, Mapping):
        checkpoint_id = raw.get("id", raw.get("checkpoint_id"))
        expected = raw.get("sha256", raw.get("checkpoint_sha256"))
        path_value = raw.get("path", raw.get("checkpoint_path"))
        if (
            raw.get("verified") is True
            and isinstance(checkpoint_id, str)
            and checkpoint_id
            and isinstance(expected, str)
            and len(expected) == 64
            and all(char in "0123456789abcdef" for char in expected.lower())
            and path_value is None
        ):
            return {
                "id": checkpoint_id,
                "path": str(path_value) if isinstance(path_value, str) else None,
                "sha256": expected.lower(),
                "verified": True,
            }

    if not isinstance(raw, Mapping):
        return None
    checkpoint_id = raw.get("id", raw.get("checkpoint_id"))
    expected = raw.get("sha256", raw.get("checkpoint_sha256"))
    path_value = raw.get("path", raw.get("checkpoint_path"))
    if (
        not isinstance(checkpoint_id, str)
        or not checkpoint_id
        or not isinstance(expected, str)
        or len(expected) != 64
        or any(char not in "0123456789abcdef" for char in expected.lower())
        or not isinstance(path_value, str)
        or not path_value
    ):
        return None

    allowed_roots = [root for root in (output_root, _workspace(ctx)) if root is not None]
    candidate = Path(path_value)
    try:
        resolved = candidate.resolve() if candidate.is_absolute() else None
        if resolved is None:
            for root in allowed_roots:
                possible = (root / candidate).resolve()
                try:
                    possible.relative_to(root.resolve())
                except ValueError:
                    continue
                resolved = possible
                break
        if resolved is None or not resolved.is_file():
            return None
        if not any(
            resolved == root.resolve() or resolved.is_relative_to(root.resolve())
            for root in allowed_roots
        ):
            return None
        actual = _checkpoint_sha256(resolved)
    except (OSError, RuntimeError, ValueError):
        return None
    if actual != expected.lower():
        return None
    return {
        "id": checkpoint_id,
        "path": str(resolved),
        "sha256": actual,
        "verified": True,
    }


def _collection_completion_reasons(metrics: Mapping[str, Any]) -> list[str]:
    """Return explicit reasons why a collection cannot publish a SAFE bundle."""
    reasons: list[str] = []
    if metrics.get("manifest_inventory_complete") is not True:
        reasons.append("manifest_inventory_incomplete")
    if metrics.get("frame_metrics_complete") is not True:
        reasons.append("frame_metrics_incomplete")
    shard_count = _exact_nonnegative_int(metrics.get("shard_count"))
    safe_count = _exact_nonnegative_int(metrics.get("safe_count"))
    partial_count = _exact_nonnegative_int(metrics.get("partial_count"))
    reject_count = _exact_nonnegative_int(metrics.get("reject_count"))
    if shard_count is None or safe_count is None:
        reasons.append("shard_counts_unproven")
    elif safe_count != shard_count:
        reasons.append("not_all_shards_safe")
    if partial_count is None:
        reasons.append("partial_count_unproven")
    elif partial_count != 0:
        reasons.append("partial_shards_present")
    if reject_count is None:
        reasons.append("reject_count_unproven")
    elif reject_count != 0:
        reasons.append("rejected_shards_present")
    queue_drops = _exact_nonnegative_int(metrics.get("queue_drops"))
    if queue_drops is None:
        reasons.append("queue_drops_unproven")
    elif queue_drops != 0:
        reasons.append("queue_drops_present")
    return reasons


def run_one_unit(
    ctx: AdapterContext,
    runner: Callable[..., Any] = subprocess.run,
) -> AdapterResult:
    """Run one bounded deterministic unit.

    Economic proof units first materialize the selected SAFE Dataset V2 shards,
    then run the economic campaign in the same GitHub-hosted job. This avoids
    relying on ephemeral runner state across continuations.
    """
    started_at_epoch_ms = int(time.time() * 1000)
    started_monotonic = time.monotonic()

    def finish(
        status: str,
        payload: dict[str, Any],
        progressed: bool,
        *,
        state: str | None = None,
        reason: str | None = None,
        deadline_exceeded: bool = False,
        output_root: Path | None = None,
        counts_source: Mapping[str, Any] | None = None,
    ) -> AdapterResult:
        enriched = dict(payload)
        ended_at_epoch_ms = int(time.time() * 1000)
        deadline_epoch_ms = (
            int(ctx.soft_deadline_epoch * 1000)
            if math.isfinite(float(ctx.soft_deadline_epoch))
            else None
        )
        partition = ctx.partition
        checkpoint = _verified_durable_checkpoint(ctx, output_root)
        sources = [enriched, counts_source, partition]
        counts = {
            "selected_count": _exact_count_from_sources(
                sources, ("selected_count", "selected_units", "units_selected")
            ),
            "completed_count": _exact_count_from_sources(
                sources, ("completed_count", "completed_units", "units_completed")
            ),
            "published_count": _exact_count_from_sources(
                sources, ("published_count", "published_units", "units_published")
            ),
            "safe_qualified_count": _exact_count_from_sources(
                sources,
                ("safe_qualified_count", "safe_count", "safe_shards", "qualified_safe_count"),
            ),
        }
        attempt = _exact_count_from_sources(
            [partition], ("attempt", "attempt_number", "attempt_count")
        )
        diagnostic_state = state or {
            "COMPLETE": "COMPLETE",
            "CONTINUATION_REQUIRED": "CHECKPOINTED",
            "UNAVAILABLE": "UNAVAILABLE",
            "PARTIAL": "PARTIAL",
            "FAILED": "FAILED",
        }.get(status, status)
        diagnostic_reason = reason or str(enriched.get("reason") or status.lower())
        enriched["counts"] = counts
        enriched["last_durable_checkpoint"] = checkpoint
        enriched["unit_diagnostic"] = {
            "schema": ADAPTER_DIAGNOSTIC_SCHEMA,
            "campaign_id": ctx.campaign_id,
            "kind": ctx.kind,
            "unit_id": ctx.unit_id,
            "state": diagnostic_state,
            "reason": diagnostic_reason,
            "status": status,
            "started_at_epoch_ms": started_at_epoch_ms,
            "ended_at_epoch_ms": ended_at_epoch_ms,
            "duration_ms": max(0, int((time.monotonic() - started_monotonic) * 1000)),
            "deadline_epoch_ms": deadline_epoch_ms,
            "deadline_exceeded": bool(deadline_exceeded),
            "attempt": attempt,
            "last_durable_checkpoint": checkpoint,
            "counts": counts,
            "safe_publication_allowed": status == "COMPLETE" and diagnostic_state == "COMPLETE",
        }
        return AdapterResult(status, _digest(enriched), enriched, progressed)

    remaining = ctx.soft_deadline_epoch - time.time()
    if remaining <= 5:
        payload = {"status": "CONTINUATION_REQUIRED", "reason": "soft_deadline"}
        return finish(
            payload["status"],
            payload,
            False,
            state="TIMED_OUT",
            reason="soft_deadline",
            deadline_exceeded=True,
        )

    commands: list[tuple[list[str], Path | None, str]]
    if ctx.kind in ECONOMIC_KINDS:
        try:
            binding_args = _economic_campaign_binding_args(ctx)
        except ValueError as exc:
            payload = {
                "status": "FAILED",
                "reason": "invalid_campaign_binding",
                "detail": str(exc),
            }
            return finish("FAILED", payload, False, reason="invalid_campaign_binding")
        workspace = _workspace(ctx)
        commands = [
            (_materialize_command(ctx, workspace), workspace, "materialize_safe_v2"),
            (
                [
                    sys.executable,
                    str(ROOT / "tools" / "run_economic_objective_campaigns.py"),
                    "--root",
                    str(workspace),
                    "--no-start-collection",
                    "--analysis-stage",
                    _analysis_stage(ctx.kind) or str(ctx.kind).upper(),
                    *binding_args,
                ],
                workspace,
                "economic_campaign",
            ),
        ]
        if ctx.kind == "module_pnl_proof":
            commands.append(
                (
                    [
                        sys.executable,
                        str(ROOT / "tools" / "audit_economic_objectives.py"),
                        "--root",
                        str(workspace),
                    ],
                    workspace,
                    "module_pnl_audit",
                )
            )
    else:
        try:
            cmd, output_root = build_command(ctx)
        except ValueError as exc:
            payload = {
                "status": "FAILED",
                "reason": "invalid_partition",
                "detail": str(exc),
            }
            return finish("FAILED", payload, False, reason="invalid_partition")
        commands = [(cmd, output_root, "unit")]

    phases: list[dict[str, Any]] = []
    economic_proof_status: str | None = None
    for cmd, output_root, phase_name in commands:
        remaining = ctx.soft_deadline_epoch - time.time()
        if remaining <= 5:
            payload = {
                "status": "CONTINUATION_REQUIRED",
                "reason": "soft_deadline",
                "phases": phases,
            }
            return finish(
                "CONTINUATION_REQUIRED",
                payload,
                bool(phases),
                state="TIMED_OUT",
                reason="soft_deadline",
                deadline_exceeded=True,
            )

        if output_root is not None:
            try:
                output_root.mkdir(parents=True, exist_ok=True)
            except (OSError, ValueError) as exc:
                payload = {
                    "status": "FAILED",
                    "reason": "output_root_unavailable",
                    "failure_category": "OUTPUT_PATH",
                    "phase": phase_name,
                    "detail": str(exc)[:1000],
                    "phases": phases,
                }
                return finish(
                    "FAILED",
                    payload,
                    False,
                    state="FAILED",
                    reason="output_root_unavailable",
                )
        try:
            cp = _run(runner, cmd, timeout=max(1, int(remaining - 5)), analysis_stage=_analysis_stage(ctx.kind))
        except subprocess.TimeoutExpired as exc:
            # A timeout may happen after the worker has durably flushed a
            # checkpoint but before this adapter receives a completed phase.
            # Preserve that evidence as progress so the controller schedules
            # the same unit for continuation instead of treating it as an
            # unprogressed retry.  ``finish`` verifies the checkpoint again
            # and never exposes an unverified cursor.
            checkpoint = _verified_durable_checkpoint(ctx, output_root)
            payload = {
                "status": "CONTINUATION_REQUIRED",
                "reason": "adapter_timeout",
                "phase": phase_name,
                "command": cmd[:4],
                "partial_stdout": _text_tail(exc.stdout),
                "partial_stderr": _text_tail(exc.stderr),
                "phases": phases,
            }
            return finish(
                "CONTINUATION_REQUIRED",
                payload,
                bool(phases) or checkpoint is not None,
                state="TIMED_OUT",
                reason="adapter_timeout",
                deadline_exceeded=True,
                output_root=output_root,
            )
        except Exception as exc:
            checkpoint = _verified_durable_checkpoint(ctx, output_root)
            payload = {
                "status": "CONTINUATION_REQUIRED" if checkpoint is not None else "FAILED",
                "reason": "adapter_interrupted",
                "failure_category": "ADAPTER_EXCEPTION",
                "phase": phase_name,
                "exception_type": type(exc).__name__,
                "detail": str(exc)[:1000],
                "phases": phases,
            }
            return finish(
                payload["status"],
                payload,
                checkpoint is not None,
                state="INTERRUPTED",
                reason="adapter_interrupted",
                output_root=output_root,
            )

        stdout = _text_tail(getattr(cp, "stdout", ""))
        stderr = _text_tail(getattr(cp, "stderr", ""))
        returncode = int(getattr(cp, "returncode", 1) or 0)
        phases.append(
            {
                "name": phase_name,
                "command": cmd[:4],
                "returncode": returncode,
                "stdout": stdout,
                "stderr": stderr,
                "analysis_stage": (
                    _analysis_stage(ctx.kind)
                ),
            }
        )

        if phase_name == "module_pnl_audit" and ctx.kind == "module_pnl_proof":
            economic_proof_status = _economic_proof_status(output_root or _workspace(ctx))
            if economic_proof_status is not None and returncode in {0, 2}:
                phases[-1]["semantic_status"] = economic_proof_status
                phases[-1]["certifying"] = economic_proof_status == "PASS"
                # Exit code 2 from audit_economic_objectives.py means the audit
                # was produced but mandatory economic evidence is not certifying.
                # That is a semantic verdict, not an orchestration crash.
                continue

        if returncode != 0:
            payload = _failure_payload(cmd, cp)
            combined = (stdout + "\n" + stderr).lower()
            if (
                ctx.kind in {"replay", "backtest", "module_pnl_proof"}
                and "no safe shards match the selection" in combined
            ):
                payload["status"] = "UNAVAILABLE"
                payload["reason"] = "no_safe_dataset_v2"
                payload["failure_category"] = "DATA_AVAILABILITY"
                payload["phase"] = phase_name
                payload["phases"] = phases
                return finish("UNAVAILABLE", payload, False, reason="no_safe_dataset_v2")
            if phase_name == "materialize_safe_v2":
                payload["reason"] = "dataset_materialization_failed"
            payload["phase"] = phase_name
            payload["phases"] = phases
            return finish("FAILED", payload, False, reason=str(payload.get("reason")))

    if (
        ctx.kind == "replay"
        and ctx.partition.get("resume_proof") is True
        and int(ctx.partition.get("chunk_index") or 0) == 0
    ):
        plan_stdout = phases[-1]["stdout"] if phases else ""
        payload = {
            "status": "CONTINUATION_REQUIRED",
            "reason": "resume_proof_selection_checkpoint",
            "analysis_stage": "REPLAY",
            "selection_plan_sha256": hashlib.sha256(plan_stdout.encode()).hexdigest(),
            "phase": "dataset_selection_plan",
            "phases": phases,
            "resume_proof": True,
            "next_unit": 1,
        }
        return finish(
            "CONTINUATION_REQUIRED",
            payload,
            True,
            state="CHECKPOINTED",
            reason="resume_proof_selection_checkpoint",
        )

    last_cmd, output_root, _ = commands[-1]
    collection_plan_sha256 = None
    if output_root is not None:
        digest_path = output_root / "collection_plan.sha256"
        if digest_path.is_file():
            collection_plan_sha256 = digest_path.read_text(
                encoding="utf-8"
            ).strip().split()[0]
    stdout = phases[-1]["stdout"] if phases else ""
    stderr = phases[-1]["stderr"] if phases else ""
    collection_kinds = {
        "market_collection", "copy_vault_collection",
        "official_archive_collection", "event_intelligence_collection",
    }
    collection_metrics = (
        _collection_checkpoint_metrics(output_root)
        if ctx.kind in collection_kinds and output_root is not None else None
    )
    if collection_metrics is not None:
        observed_records = _exact_nonnegative_int(
            collection_metrics.get("record_count_observed")
        )
        observed_shards = _exact_nonnegative_int(
            collection_metrics.get("shard_count")
        )
    else:
        observed_records = None
        observed_shards = None
    if collection_metrics is not None and (
        (observed_records is not None and observed_records <= 0)
        or (observed_shards is not None and observed_shards <= 0)
    ):
        unavailable = {
            "status": "UNAVAILABLE",
            "reason": "no_durable_collection_events",
            "failure_category": "DATA_AVAILABILITY",
            "output_root": str(output_root),
            "collection_metrics": collection_metrics,
            "phases": phases,
        }
        return finish(
            "UNAVAILABLE",
            unavailable,
            False,
            state="EMPTY",
            reason="no_durable_collection_events",
            output_root=output_root,
            counts_source=collection_metrics,
        )
    if collection_metrics is not None:
        publication_reasons = _collection_completion_reasons(collection_metrics)
        if publication_reasons:
            partial = {
                "status": "PARTIAL",
                "reason": "collection_publication_unproven",
                "failure_category": "QUALITY",
                "publication_blockers": publication_reasons,
                "output_root": str(output_root),
                "collection_metrics": collection_metrics,
                "phases": phases,
            }
            return finish(
                "PARTIAL",
                partial,
                bool(phases),
                state="PARTIAL",
                reason="collection_publication_unproven",
                output_root=output_root,
                counts_source=collection_metrics,
            )
    payload = {
        "status": "COMPLETE",
        "analysis_stage": (
            _analysis_stage(ctx.kind)
        ),
        "returncode": 0,
        "stdout": stdout,
        "stderr": stderr,
        "output_root": str(output_root) if output_root is not None else None,
        "collection_plan_sha256": collection_plan_sha256,
        "universe_discovery_required": ctx.kind == "market_collection",
        "safe_workspace": (
            str(output_root) if ctx.kind in ECONOMIC_KINDS and output_root is not None else None
        ),
        "bundle_root": (
            str(output_root)
            if ctx.kind in collection_kinds
            and output_root is not None
            else None
        ),
        "phases": phases,
    }
    if (
        collection_metrics is not None
    ):
        payload["collection_metrics"] = collection_metrics
    if ctx.kind == "module_pnl_proof":
        payload["economic_proof_status"] = economic_proof_status
        payload["economic_proof_certifying"] = economic_proof_status == "PASS"
    return finish(
        "COMPLETE",
        payload,
        True,
        state="COMPLETE",
        reason="completed",
        output_root=output_root,
        counts_source=collection_metrics,
    )

