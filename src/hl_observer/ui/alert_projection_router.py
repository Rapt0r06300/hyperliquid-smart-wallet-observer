"""GET-only dashboard boundary for the canonical alert projection."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from hl_observer.alerts.read_model import materialized_read_model_hash
from hl_observer.alerts.spine import PROJECTION_SCHEMA
from hl_observer.config.settings import Settings

ALERT_DASHBOARD_CAPABILITY_SCHEMA = "hypersmart.alert_dashboard_capabilities.v1"
ALERT_DASHBOARD_UX_SCHEMA = "hypersmart.alert_dashboard_ux.v1"
_ALLOWED_CAPABILITIES = (
    "VIEW_LATEST_ALERTS",
    "FILTER_ALERT_FAMILY",
    "FILTER_ALERT_ENTITY",
    "FILTER_ALERT_CATEGORY",
    "FILTER_ALERT_SOURCE",
    "INSPECT_SOURCE_HEALTH",
    "INSPECT_CORRECTIONS_CONFLICTS",
    "INSPECT_FRESHNESS_METRICS",
    "INSPECT_RESEARCH_SUMMARIES",
)
_FORBIDDEN_AUTHORITIES = (
    "REWRITE_ALERT_SCORE",
    "MARK_EVIDENCE_VERIFIED",
    "MUTATE_GUARDIAN_STATE",
    "ENABLE_TRADING",
    "START_TESTNET_EXECUTION",
    "START_MAINNET_EXECUTION",
    "WRITE_CANONICAL_LEDGER",
)


class AlertProjectionUnavailable(RuntimeError):
    """Raised when the disposable dashboard snapshot cannot be trusted."""


def default_alert_projection_path(settings: Settings) -> Path:
    override = str(os.environ.get("HYPERSMART_ALERT_PROJECTION_PATH") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    logs_dir = Path(settings.logs_dir).resolve()
    project_root = logs_dir.parent if logs_dir.name.lower() == "logs" else Path.cwd()
    return (
        project_root
        / "runtime"
        / "data"
        / "alert_spine"
        / "projections"
        / "alerts_dashboard.json"
    ).resolve()


def alert_dashboard_capability_manifest() -> dict[str, Any]:
    return {
        "schema_version": ALERT_DASHBOARD_CAPABILITY_SCHEMA,
        "surface": "ALERT_RESEARCH_DASHBOARD",
        "capabilities": [
            {
                "capability_id": capability,
                "kind": "RESEARCH_NAVIGATION",
                "access": "READ",
                "mutates_state": False,
            }
            for capability in _ALLOWED_CAPABILITIES
        ],
        "forbidden_authorities": list(_FORBIDDEN_AUTHORITIES),
        "ledger_access": "NONE",
        "projection_access": "READ_ONLY",
        "paper_read_only": True,
        "real_execution": False,
    }


def _as_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def build_alert_dashboard_ux(
    projection: Mapping[str, Any],
    *,
    displayed_at_ms: int,
) -> dict[str, Any]:
    """Build presentation fields from a trusted projection, never from the ledger."""

    freshness = projection.get("freshness")
    freshness = freshness if isinstance(freshness, Mapping) else {}
    policy = freshness.get("policy")
    policy = policy if isinstance(policy, Mapping) else {}
    fresh_max_age_ms = max(0, _as_int(policy.get("fresh_max_age_ms"), default=30_000))
    degraded_max_age_ms = max(
        fresh_max_age_ms,
        _as_int(policy.get("degraded_max_age_ms"), default=120_000),
    )
    display_slo_ms = max(
        0,
        _as_int(policy.get("detection_to_display_slo_ms"), default=15_000),
    )
    source_health = freshness.get("source_health")
    source_health = source_health if isinstance(source_health, Mapping) else {}
    raw_alerts = projection.get("alerts")
    raw_alerts = raw_alerts if isinstance(raw_alerts, list) else []
    alerts: list[dict[str, Any]] = []
    for raw_alert in raw_alerts:
        if not isinstance(raw_alert, Mapping):
            continue
        observed_at_ms = _as_int(raw_alert.get("observed_at_ms"))
        age_ms = max(0, int(displayed_at_ms) - observed_at_ms)
        if age_ms <= fresh_max_age_ms:
            marker = "FRESH"
        elif age_ms <= degraded_max_age_ms:
            marker = "DEGRADED"
        else:
            marker = "STALE"
        declared_health = str(raw_alert.get("source_health_state") or "UNKNOWN")
        if marker == "STALE":
            effective_health = "STALE"
        elif marker == "DEGRADED" and declared_health == "HEALTHY":
            effective_health = "DEGRADED"
        else:
            effective_health = declared_health
        source_id = str(raw_alert.get("source_id") or "UNKNOWN")
        source_state = source_health.get(source_id)
        source_state = source_state if isinstance(source_state, Mapping) else {}
        refresh_ms = _as_int(
            source_state.get("last_successful_refresh_ms"),
            default=_as_int(raw_alert.get("fetched_at_ms")),
        )
        source_timestamp = raw_alert.get("source_event_time_ms")
        source_timestamp_ms = (
            _as_int(source_timestamp) if source_timestamp is not None else None
        )
        payload = raw_alert.get("payload")
        payload_family = (
            payload.get("alert_family") if isinstance(payload, Mapping) else None
        )
        lifecycle = str(
            raw_alert.get("projection_lifecycle_state") or "PROJECTED"
        )
        detection_to_display_ms = max(0, int(displayed_at_ms) - observed_at_ms)
        alerts.append(
            {
                "event_id": str(raw_alert.get("event_id") or ""),
                "headline": str(raw_alert.get("headline") or ""),
                "family": str(
                    payload_family or raw_alert.get("category") or "UNKNOWN"
                ).upper(),
                "category": str(raw_alert.get("category") or "UNKNOWN"),
                "source_id": source_id,
                "source_timestamp_ms": source_timestamp_ms,
                "source_timestamp_available": source_timestamp_ms is not None,
                "observed_at_ms": observed_at_ms,
                "observed_age_ms": age_ms,
                "source_health_state": effective_health,
                "last_successful_refresh_ms": refresh_ms or None,
                "stale_degraded_marker": marker,
                "lifecycle_state": lifecycle,
                "corrected_or_retracted": lifecycle in {"CORRECTED", "RETRACTED"},
                "detection_to_display_ms": detection_to_display_ms,
                "display_slo_state": (
                    "MEETS_SLO"
                    if detection_to_display_ms <= display_slo_ms
                    else "BREACH"
                ),
            }
        )

    latest = max(alerts, key=lambda alert: alert["observed_at_ms"], default=None)
    if latest is None:
        badge_state = "NO_DATA"
        badge_reason = "NO_MEASURABLE_ALERT_FRESHNESS"
    elif latest["stale_degraded_marker"] == "STALE":
        badge_state = "STALE"
        badge_reason = "LATEST_ALERT_STALE"
    elif (
        latest["stale_degraded_marker"] == "FRESH"
        and latest["source_health_state"] == "HEALTHY"
        and latest["display_slo_state"] == "MEETS_SLO"
    ):
        badge_state = "LIVE"
        badge_reason = "MEASURED_FRESH_HEALTHY_WITHIN_SLO"
    else:
        badge_state = "DEGRADED"
        badge_reason = "LATEST_ALERT_NOT_FULLY_FRESH_HEALTHY_WITHIN_SLO"
    return {
        "schema_version": ALERT_DASHBOARD_UX_SCHEMA,
        "displayed_at_ms": int(displayed_at_ms),
        "alerts": alerts,
        "live_badge": {
            "state": badge_state,
            "color": "GREEN" if badge_state == "LIVE" else "NON_GREEN",
            "measurable_freshness": latest is not None,
            "reason": badge_reason,
            "process_running_is_not_evidence": True,
        },
        "paper_read_only": True,
        "real_execution": False,
    }


def read_alert_projection(path: str | Path) -> dict[str, Any]:
    projection_path = Path(path)
    if not projection_path.is_file():
        raise AlertProjectionUnavailable("ALERT_PROJECTION_MISSING")
    try:
        raw = projection_path.read_bytes()
        projection = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AlertProjectionUnavailable("ALERT_PROJECTION_INVALID_JSON") from exc
    if not isinstance(projection, Mapping):
        raise AlertProjectionUnavailable("ALERT_PROJECTION_NOT_MAPPING")
    if (
        projection.get("schema_version") != PROJECTION_SCHEMA
        or projection.get("paper_read_only") is not True
        or projection.get("real_execution") is not False
    ):
        raise AlertProjectionUnavailable("ALERT_PROJECTION_SAFETY_INVALID")
    read_model = projection.get("materialized_read_model")
    if not isinstance(read_model, Mapping):
        raise AlertProjectionUnavailable("ALERT_READ_MODEL_MISSING")
    expected_hash = materialized_read_model_hash(read_model)
    if (
        projection.get("materialized_read_model_hash") != expected_hash
        or projection.get("canonical_projection_hash") != expected_hash
    ):
        raise AlertProjectionUnavailable("ALERT_READ_MODEL_HASH_MISMATCH")
    if (
        read_model.get("paper_read_only") is not True
        or read_model.get("real_execution") is not False
    ):
        raise AlertProjectionUnavailable("ALERT_READ_MODEL_SAFETY_INVALID")
    return dict(projection)


def create_alert_projection_router(
    projection_path: str | Path,
    *,
    clock_ms: Callable[[], int] | None = None,
    dashboard_path: str | Path | None = None,
) -> APIRouter:
    """Expose projection and capabilities without any writer or ledger handle."""

    path = Path(projection_path)
    now_ms = clock_ms or (lambda: int(time.time() * 1000))
    page_path = Path(dashboard_path) if dashboard_path else Path(__file__).with_name(
        "static"
    ) / "alerts_v26.html"
    router = APIRouter()

    @router.get("/api/alerts/projection")
    def alert_projection() -> dict[str, Any]:
        try:
            projection = read_alert_projection(path)
        except AlertProjectionUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            **projection,
            "dashboard_ux": build_alert_dashboard_ux(
                projection,
                displayed_at_ms=int(now_ms()),
            ),
        }

    @router.get("/api/alerts/capabilities")
    def alert_capabilities() -> dict[str, Any]:
        return alert_dashboard_capability_manifest()

    @router.get("/alerts", include_in_schema=False)
    def alert_dashboard() -> FileResponse:
        if not page_path.is_file():
            raise HTTPException(status_code=503, detail="ALERT_DASHBOARD_MISSING")
        return FileResponse(page_path)

    return router


__all__ = [
    "ALERT_DASHBOARD_CAPABILITY_SCHEMA",
    "ALERT_DASHBOARD_UX_SCHEMA",
    "AlertProjectionUnavailable",
    "alert_dashboard_capability_manifest",
    "build_alert_dashboard_ux",
    "create_alert_projection_router",
    "default_alert_projection_path",
    "read_alert_projection",
]
