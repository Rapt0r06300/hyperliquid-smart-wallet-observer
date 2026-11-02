"""Fail-closed validator for the canonical H-T95 restoration snapshot.

The local lab already owns the ``hypersmart.copy_vault_restoration_snapshot``
contract. This module validates that emitted artifact; it does not introduce
another snapshot format, read a corpus, calculate missing counts, or create a
restoration receipt. A ``PROVEN`` result is only an artifact-level preflight;
the Agiflow closure gate still requires the exact task receipt and SHA-bound
evidence separately.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SCHEMA = "hypersmart.copy_vault_restoration_snapshot.v1"
PROVEN = "PROVEN"
NOT_PROVEN = "NOT_PROVEN"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LINEAGE_DIGESTS = (
    "selection_digest",
    "engine_source_sha256",
    "campaign_config_sha256",
    "source_catalog_sha256",
    "source_asset_inventory_sha256",
)
_ARTIFACTS = ("ledger", "equity", "costs", "metrics", "tests", "report", "restoration_receipt")


def _sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value.lower()))


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def verify_snapshot_contract(snapshot: Mapping[str, Any] | object) -> dict[str, Any]:
    """Validate one supplied canonical restoration snapshot without inference."""

    missing: list[str] = []
    invalid: list[str] = []

    if not isinstance(snapshot, Mapping):
        return {
            "schema": None,
            "status": NOT_PROVEN,
            "missing": [],
            "invalid": ["snapshot"],
            "paper_read_only": None,
            "real_execution": None,
        }

    def require(path: str, predicate: Any) -> Any:
        current: Any = snapshot
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                missing.append(path)
                return None
            current = current[part]
        if not predicate(current):
            invalid.append(path)
        return current

    schema = require("schema_version", lambda value: value == SCHEMA)
    require("restoration_status", lambda value: value == "READY")
    missing_requirements = require(
        "restoration_missing_requirements",
        lambda value: isinstance(value, list) and not value,
    )
    paper_read_only = require("paper_read_only", lambda value: value is True)
    real_execution = require("real_execution", lambda value: value is False)
    require("restore_started", lambda value: value is False)
    require("source_untouched", lambda value: value is True)
    require("restoration_snapshot_sha256", _sha256)

    lineage = require("lineage", lambda value: isinstance(value, Mapping))
    if isinstance(lineage, Mapping):
        for field in _LINEAGE_DIGESTS:
            path = f"lineage.{field}"
            if field not in lineage:
                missing.append(path)
            elif not _sha256(lineage[field]):
                invalid.append(path)
        count_path = "lineage.source_asset_inventory_count"
        if "source_asset_inventory_count" not in lineage:
            missing.append(count_path)
        elif not _nonnegative_int(lineage["source_asset_inventory_count"]):
            invalid.append(count_path)

    search = require("search", lambda value: isinstance(value, Mapping))
    if isinstance(search, Mapping):
        config = search.get("campaign_config")
        if config is None:
            missing.append("search.campaign_config")
        elif not isinstance(config, Mapping) or not config:
            invalid.append("search.campaign_config")
        for field, predicate in (
            ("proposal_seed", _nonnegative_int),
            ("global_trial_count", _positive_int),
        ):
            path = f"search.{field}"
            if field not in search:
                missing.append(path)
            elif not predicate(search[field]):
                invalid.append(path)
        windows = search.get("temporal_windows")
        if windows is None:
            missing.append("search.temporal_windows")
        elif not isinstance(windows, Mapping) or not windows:
            invalid.append("search.temporal_windows")
        capital = search.get("paper_capital_usd")
        if capital is None:
            missing.append("search.paper_capital_usd")
        elif capital != 200.0:
            invalid.append("search.paper_capital_usd")

    trial = require("trial_accounting", lambda value: isinstance(value, Mapping))
    if isinstance(trial, Mapping):
        for field, predicate in (
            ("trial_number", _positive_int),
            ("attempt_receipt_sha256", _sha256),
            ("trial_receipt_sha256", _sha256),
        ):
            path = f"trial_accounting.{field}"
            if field not in trial:
                missing.append(path)
            elif not predicate(trial[field]):
                invalid.append(path)

    freeze = require("candidate_freeze", lambda value: isinstance(value, Mapping))
    if isinstance(freeze, Mapping):
        freeze_data = freeze.get("freeze")
        if not isinstance(freeze_data, Mapping):
            missing.append("candidate_freeze.freeze")
        else:
            parameters = freeze_data.get("parameters")
            if parameters is None:
                missing.append("candidate_freeze.freeze.parameters")
            elif not isinstance(parameters, Mapping) or not parameters:
                invalid.append("candidate_freeze.freeze.parameters")
            parameter_sha = freeze_data.get("parameters_sha256")
            if parameter_sha is None:
                missing.append("candidate_freeze.freeze.parameters_sha256")
            elif not _sha256(parameter_sha):
                invalid.append("candidate_freeze.freeze.parameters_sha256")

    artifacts = require("artifacts", lambda value: isinstance(value, Mapping))
    artifact_hashes = require("artifacts_sha256", lambda value: isinstance(value, Mapping))
    if isinstance(artifacts, Mapping) and isinstance(artifact_hashes, Mapping):
        for field in _ARTIFACTS:
            value_path = f"artifacts.{field}"
            hash_path = f"artifacts_sha256.{field}"
            if field not in artifacts or artifacts[field] in (None, {}, [], ""):
                missing.append(value_path)
            if field not in artifact_hashes:
                missing.append(hash_path)
            elif not _sha256(artifact_hashes[field]):
                invalid.append(hash_path)
        receipt = artifacts.get("restoration_receipt")
        if isinstance(receipt, Mapping):
            status = str(receipt.get("status") or "").upper()
            if status not in {"RESTORABLE", "RESTORED", "VERIFIED"}:
                invalid.append("artifacts.restoration_receipt.status")

    missing = list(dict.fromkeys(missing))
    invalid = list(dict.fromkeys(invalid))
    return {
        "schema": schema,
        "status": PROVEN if not missing and not invalid else NOT_PROVEN,
        "missing": missing,
        "invalid": invalid,
        "paper_read_only": paper_read_only,
        "real_execution": real_execution,
        "restoration_missing_requirements": missing_requirements,
    }


__all__ = ["NOT_PROVEN", "PROVEN", "SCHEMA", "verify_snapshot_contract"]
