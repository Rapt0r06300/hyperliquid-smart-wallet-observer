"""GET-only dashboard boundary for the canonical alert projection."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from hl_observer.alerts.read_model import materialized_read_model_hash
from hl_observer.alerts.spine import PROJECTION_SCHEMA
from hl_observer.config.settings import Settings

ALERT_DASHBOARD_CAPABILITY_SCHEMA = "hypersmart.alert_dashboard_capabilities.v1"
_ALLOWED_CAPABILITIES = (
    "VIEW_LATEST_ALERTS",
    "FILTER_ALERT_FAMILY",
    "FILTER_ALERT_ENTITY",
    "FILTER_ALERT_CATEGORY",
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


def create_alert_projection_router(projection_path: str | Path) -> APIRouter:
    """Expose projection and capabilities without any writer or ledger handle."""

    path = Path(projection_path)
    router = APIRouter()

    @router.get("/api/alerts/projection")
    def alert_projection() -> dict[str, Any]:
        try:
            return read_alert_projection(path)
        except AlertProjectionUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/api/alerts/capabilities")
    def alert_capabilities() -> dict[str, Any]:
        return alert_dashboard_capability_manifest()

    return router


__all__ = [
    "ALERT_DASHBOARD_CAPABILITY_SCHEMA",
    "AlertProjectionUnavailable",
    "alert_dashboard_capability_manifest",
    "create_alert_projection_router",
    "default_alert_projection_path",
    "read_alert_projection",
]
