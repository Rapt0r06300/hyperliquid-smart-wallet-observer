"""Read-only fault-injection receipts for Copy-Vault resilience contracts."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def network_loss_scan_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require a scan to fail closed when the network disappears."""
    if not rows:
        return _base("MORE_DATA", reason="empty_network_loss_injection")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("fault") != "NETWORK_LOSS"
        or row.get("scan_state") != "FAIL_CLOSED"
        or row.get("execution_attempted") is not False
        or row.get("data_certified") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="NETWORK_LOSS_SCAN_FAIL_CLOSED", invalid_rows=invalid)


def rest_429_budget_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require repeated REST 429 responses to stay within retry and budget bounds."""
    if not rows:
        return _base("MORE_DATA", reason="empty_rest_429_injection")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        retries = _number(row.get("retries")) if isinstance(row, Mapping) else None
        max_retries = _number(row.get("max_retries")) if isinstance(row, Mapping) else None
        budget = _number(row.get("budget_units")) if isinstance(row, Mapping) else None
        consumed = _number(row.get("consumed_units")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or row.get("fault") != "HTTP_429" or retries is None or max_retries is None or budget is None or consumed is None or retries < 1 or retries > max_retries or consumed > budget or row.get("fail_closed") is not True:
            invalid.append(index)
    return _base("PROVEN" if not invalid else "REJECTED", verdict="REST_429_BUDGET_BOUNDED", invalid_rows=invalid)


def stale_ws_without_tcp_close_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require watchdog handling when WS is stale while TCP remains open."""
    if not rows:
        return _base("MORE_DATA", reason="empty_ws_stale_injection")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("fault") != "WS_STALE"
        or row.get("tcp_connected") is not True
        or row.get("watchdog_state") != "STALE_FAIL_CLOSED"
        or row.get("new_decisions") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="WS_STALE_WITHOUT_TCP_CLOSE_HANDLED", invalid_rows=invalid)


def bbo_loss_mids_live_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require BBO loss to veto decisions even when allMids remains live."""
    if not rows:
        return _base("MORE_DATA", reason="empty_bbo_loss_injection")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("fault") != "BBO_LOSS"
        or row.get("allmids_live") is not True
        or row.get("bbo_available") is not False
        or row.get("decision") != "VETO_NO_BOOK"
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="BBO_LOSS_VETOES_WITH_MIDS_LIVE", invalid_rows=invalid)


def l2_delta_discontinuity_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require discontinuous L2 deltas to enter quarantine."""
    if not rows:
        return _base("MORE_DATA", reason="empty_l2_delta_injection")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("fault") != "L2_DELTA_GAP"
        or not isinstance(row.get("expected_seq"), int)
        or not isinstance(row.get("received_seq"), int)
        or row.get("received_seq") <= row.get("expected_seq")
        or row.get("quarantined") is not True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="L2_DELTA_DISCONTINUITY_QUARANTINED", invalid_rows=invalid)


def sqlite_corruption_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require corrupted session SQLite state to be isolated before recovery."""
    if not rows:
        return _base("MORE_DATA", reason="empty_sqlite_corruption_injection")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("fault") != "SQLITE_CORRUPTION"
        or row.get("integrity_check") != "FAILED"
        or row.get("quarantined") is not True
        or row.get("certified") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="SQLITE_CORRUPTION_ISOLATED", invalid_rows=invalid)


def pid_journal_disk_full_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require disk-full PID journal failures to stop rather than fabricate liveness."""
    if not rows:
        return _base("MORE_DATA", reason="empty_pid_journal_injection")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("fault") != "DISK_FULL"
        or row.get("journal_append") is not False
        or row.get("liveness_claim") is not False
        or row.get("fail_closed") is not True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="PID_JOURNAL_DISK_FULL_FAIL_CLOSED", invalid_rows=invalid)


def abrupt_parent_powershell_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require abrupt parent termination to stop writers and mark recovery pending."""
    if not rows:
        return _base("MORE_DATA", reason="empty_parent_stop_injection")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("fault") != "PARENT_POWERSHELL_STOP"
        or row.get("all_writers_stopped") is not True
        or row.get("recovery_state") != "PENDING"
        or row.get("certified") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="ABRUPT_PARENT_STOP_RECOVERY_PENDING", invalid_rows=invalid)


def archive_replay_powerloss_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require archive replay interruption to resume from a verified checkpoint."""
    if not rows:
        return _base("MORE_DATA", reason="empty_archive_powerloss_injection")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("fault") != "POWER_LOSS"
        or not str(row.get("checkpoint_id") or "").strip()
        or not str(row.get("manifest_sha256") or "").strip()
        or row.get("partial_certification") is not False
        or row.get("resume_state") != "CHECKPOINTED"
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="ARCHIVE_REPLAY_POWERLOSS_CHECKPOINTED", invalid_rows=invalid)


def concurrent_restart_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require concurrent restart requests to resolve through one lease winner."""
    if not rows:
        return _base("MORE_DATA", reason="empty_concurrent_restart_injection")
    winners = [row for row in rows if isinstance(row, Mapping) and row.get("lease_result") == "WON"]
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("fault") != "CONCURRENT_RESTART"
        or row.get("lease_result") not in {"WON", "REFUSED"}
        or (row.get("lease_result") == "REFUSED" and row.get("started") is not False)
    ]
    if len(winners) != 1:
        invalid.append("lease_winner_count")
    return _base("PROVEN" if not invalid else "REJECTED", verdict="CONCURRENT_RESTART_SINGLE_LEASE", invalid_rows=invalid)


__all__ = [
    "network_loss_scan_receipt",
    "rest_429_budget_receipt",
    "stale_ws_without_tcp_close_receipt",
    "bbo_loss_mids_live_receipt",
    "l2_delta_discontinuity_receipt",
    "sqlite_corruption_receipt",
    "pid_journal_disk_full_receipt",
    "abrupt_parent_powershell_receipt",
    "archive_replay_powerloss_receipt",
    "concurrent_restart_receipt",
]
