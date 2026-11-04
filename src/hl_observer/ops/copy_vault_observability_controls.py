"""Fail-closed observability contracts for the Copy-Vault launcher.

These controls make source/module health and provenance explicit.  They only
validate supplied observations and never convert a stale source into a healthy
one or a technical health signal into economic approval.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)


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
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None


def version_code_sha_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require every launched component to publish version and code fingerprint."""
    if not rows:
        return _base("MORE_DATA", reason="empty_component_inventory")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not str(row.get("component") or "").strip() or not str(row.get("version") or "").strip() or not SHA_RE.fullmatch(str(row.get("code_sha") or "")):
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="COMPONENT_VERSION_AND_SHA_PUBLISHED" if not invalid else "COMPONENT_IDENTITY_MISSING",
        components=len(rows),
        invalid_rows=invalid,
    )


def queue_latency_attribution_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Separate observed network wait from CPU queue wait."""
    if not rows:
        return _base("MORE_DATA", reason="empty_latency_sample")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            invalid.append(index)
            continue
        network = _number(row.get("network_ms"))
        cpu = _number(row.get("cpu_queue_ms"))
        total = _number(row.get("total_ms"))
        if network is None or cpu is None or total is None or min(network, cpu, total) < 0 or abs((network + cpu) - total) > 1e-9:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="NETWORK_AND_CPU_QUEUE_LATENCY_ATTRIBUTED" if not invalid else "LATENCY_ATTRIBUTION_INCOMPLETE",
        observations=len(rows),
        invalid_rows=invalid,
    )


def live_monitor_ui_health_receipt(
    monitor: Mapping[str, Any], ui: Mapping[str, Any]
) -> dict[str, Any]:
    """Do not let a live monitor hide a dead or stale UI."""
    if not isinstance(monitor, Mapping) or not isinstance(ui, Mapping):
        return _base("UNMEASURABLE", reason="invalid_monitor_ui_payload")
    live = monitor.get("live")
    ui_live = ui.get("live")
    if not isinstance(live, bool) or not isinstance(ui_live, bool):
        return _base("UNMEASURABLE", reason="monitor_ui_state_missing")
    coherent = not live or ui_live
    return _base(
        "PROVEN" if coherent else "REJECTED",
        verdict="LIVE_MONITOR_DOES_NOT_MASK_UI" if coherent else "LIVE_MONITOR_MASKS_DEAD_UI",
        monitor_live=live,
        ui_live=ui_live,
    )


def ui_poller_health_receipt(
    ui: Mapping[str, Any], poller: Mapping[str, Any]
) -> dict[str, Any]:
    """Do not let a responsive UI hide a dead poller."""
    if not isinstance(ui, Mapping) or not isinstance(poller, Mapping):
        return _base("UNMEASURABLE", reason="invalid_ui_poller_payload")
    ui_live = ui.get("live")
    poller_live = poller.get("live")
    if not isinstance(ui_live, bool) or not isinstance(poller_live, bool):
        return _base("UNMEASURABLE", reason="ui_poller_state_missing")
    coherent = not ui_live or poller_live
    return _base(
        "PROVEN" if coherent else "REJECTED",
        verdict="UI_DOES_NOT_MASK_DEAD_POLLER" if coherent else "UI_MASKS_DEAD_POLLER",
        ui_live=ui_live,
        poller_live=poller_live,
    )


def startup_exception_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require init/warmup exceptions to be reported with phase and handling state."""
    if not rows:
        return _base("MORE_DATA", reason="empty_startup_exception_log")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not str(row.get("phase") or "").strip() or not str(row.get("exception_type") or "").strip() or not str(row.get("message") or "").strip() or not isinstance(row.get("handled"), bool):
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="STARTUP_EXCEPTIONS_REPORTED" if not invalid else "STARTUP_EXCEPTION_REPORT_INCOMPLETE",
        exceptions=len(rows),
        invalid_rows=invalid,
    )


def ledger_evolution_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Detect a ledger that stops evolving without fabricating a new balance."""
    if not rows:
        return _base("MORE_DATA", reason="empty_ledger_history")
    sequence: list[int] = []
    balances: list[Any] = []
    invalid: list[int] = []
    for index, row in enumerate(rows):
        seq = row.get("sequence") if isinstance(row, Mapping) else None
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0 or not isinstance(row, Mapping) or "balance" not in row:
            invalid.append(index)
            continue
        sequence.append(seq)
        balances.append(row["balance"])
    if invalid or len(sequence) != len(set(sequence)) or sequence != sorted(sequence):
        return _base("UNMEASURABLE", reason="invalid_ledger_sequence", invalid_rows=invalid)
    evolved = len(set(repr(value) for value in balances)) > 1
    return _base(
        "PROVEN" if evolved else "REJECTED",
        verdict="LEDGER_EVOLVES" if evolved else "LEDGER_NO_EVOLUTION",
        observations=len(rows),
        sequence_start=sequence[0],
        sequence_end=sequence[-1],
        evolved=evolved,
    )


def delayed_vs_dead_server_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Distinguish delayed data from a dead server using heartbeat evidence."""
    if not rows:
        return _base("MORE_DATA", reason="empty_server_data_observations")
    invalid: list[int] = []
    classifications: list[str] = []
    for index, row in enumerate(rows):
        age = _number(row.get("data_age_ms")) if isinstance(row, Mapping) else None
        interval = _number(row.get("expected_interval_ms")) if isinstance(row, Mapping) else None
        heartbeat = row.get("server_heartbeat") if isinstance(row, Mapping) else None
        if age is None or interval is None or age < 0 or interval <= 0 or not isinstance(heartbeat, bool):
            invalid.append(index)
            continue
        classifications.append("DELAYED_DATA" if heartbeat and age > interval else "SERVER_ALIVE" if heartbeat else "SERVER_DEAD")
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="DELAYED_DATA_DISTINGUISHED_FROM_DEAD_SERVER" if not invalid else "SERVER_DATA_DIAGNOSTIC_INCOMPLETE",
        classifications=classifications,
        invalid_rows=invalid,
    )


def launcher_campaign_link_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Bind each launcher log to campaign, experiment and run identifiers."""
    if not rows:
        return _base("MORE_DATA", reason="empty_launcher_links")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not str(row.get("log_path") or "").strip() or not str(row.get("campaign_id") or "").strip() or not str(row.get("experiment_id") or "").strip() or not str(row.get("run_id") or "").strip():
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="LAUNCHER_LOG_LINKED_TO_EXPERIMENT" if not invalid else "LAUNCHER_LINK_INCOMPLETE",
        rows=len(rows),
        invalid_rows=invalid,
    )


def certified_source_launcher_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Allow launcher inputs only when certification and SAFE metadata are explicit."""
    if not rows:
        return _base("MORE_DATA", reason="empty_source_selection")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or row.get("certified") is not True or not SHA_RE.fullmatch(str(row.get("manifest_hash") or "")) or row.get("paper_read_only") is not True or row.get("real_execution") is not False:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="LAUNCHER_CONSUMES_CERTIFIED_SOURCES" if not invalid else "UNCERTIFIED_SOURCE_REJECTED",
        sources=len(rows),
        invalid_rows=invalid,
    )


__all__ = [
    "version_code_sha_receipt",
    "queue_latency_attribution_receipt",
    "live_monitor_ui_health_receipt",
    "ui_poller_health_receipt",
    "startup_exception_receipt",
    "ledger_evolution_receipt",
    "delayed_vs_dead_server_receipt",
    "launcher_campaign_link_receipt",
    "certified_source_launcher_receipt",
]
