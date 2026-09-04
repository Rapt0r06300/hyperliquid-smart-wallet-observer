"""Run the three active-family vNext TRAIN-only research selectors together.

The pack is deliberately downstream of the canonical economic campaigns.  It
never mutates their parameters, campaigns, scoreboards or certification.  Each
result is stored under a separate ``research_vnext`` directory and can only
produce a candidate for a later physical freeze.
"""
from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting.copy_vault_vnext_train import explore_copy_vault_vnext_train
from hl_observer.backtesting.cross_venue_certified import load_preferred_certified_atomic_series
from hl_observer.backtesting.cross_venue_v4_train import explore_cross_venue_v4_train
from hl_observer.backtesting.cross_venue_v5_persistence_train import (
    explore_cross_venue_v5_train,
)
from hl_observer.backtesting.lead_lag_multiasset_train import explore_lead_lag_multiasset_train
from hl_observer.backtesting.lead_lag_source_alignment import select_aligned_bbo_sources

SCHEMA_VERSION = "hypersmart.economic_vnext_pack.v1"
REPORT_DIR = Path("runtime") / "reports" / "economic_campaigns" / "research_vnext"


def _write_json(root: Path, name: str, payload: dict[str, Any]) -> Path:
    target = root / REPORT_DIR / f"{name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target


def _load_copy_raw(root: Path) -> dict[str, Any] | None:
    path = root / "runtime" / "reports" / "economic_campaigns" / "raw" / "copy_vault.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"copy-vault raw report unreadable: {path}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"copy-vault raw report must be an object: {path}")
    return raw


def run_economic_vnext_pack(
    root: str | Path,
    *,
    lead_sources: Sequence[str | Path],
) -> dict[str, Any]:
    project_root = Path(root).resolve()
    requested_lead_sources = list(lead_sources)
    # An empty dataset manifest means that no explicit source override was
    # available.  It must not silently disable the standard local discovery.
    aligned_lead_sources, lead_alignment = select_aligned_bbo_sources(
        project_root,
        candidates=requested_lead_sources or None,
    )
    lead_alignment = {
        **lead_alignment,
        "requested_sources": len(requested_lead_sources),
        "source_request_mode": (
            "EXPLICIT_DATASET_MANIFEST"
            if requested_lead_sources
            else "LOCAL_AUTO_DISCOVERY_FALLBACK"
        ),
    }
    lead = explore_lead_lag_multiasset_train(project_root, aligned_lead_sources)

    cross_series, cross_depth, cross_meta = load_preferred_certified_atomic_series(project_root)
    cross = explore_cross_venue_v4_train(
        cross_series,
        cross_depth,
        source_mode=str(cross_meta.get("source_mode") or ""),
    )
    cross["certified_source_meta"] = cross_meta
    cross_v5 = explore_cross_venue_v5_train(
        cross_series,
        cross_depth,
        source_mode=str(cross_meta.get("source_mode") or ""),
    )
    cross_v5["certified_source_meta"] = cross_meta

    copy_raw = _load_copy_raw(project_root)
    if copy_raw is None:
        copy = {
            "schema_version": "hypersmart.copy_vault_vnext_train.v1",
            "status": "COPY_RAW_REPORT_MISSING",
            "selection_eligible": False,
            "physical_freeze_allowed": False,
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
            "heldout_evaluated": False,
            "paper_read_only": True,
            "real_execution": False,
        }
    else:
        copy = explore_copy_vault_vnext_train(copy_raw)
    raw_copy_v4 = copy_raw.get("next_hypothesis_v4") if copy_raw is not None else None
    copy_v4 = (
        dict(raw_copy_v4)
        if isinstance(raw_copy_v4, dict)
        else {
            "schema_version": "hypersmart.copy_vault_v4_train.v1",
            "status": "COPY_VAULT_V4_REPORT_MISSING",
            "selection_eligible": False,
            "physical_freeze_allowed": False,
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
            "heldout_evaluated": False,
            "paper_read_only": True,
            "real_execution": False,
        }
    )
    raw_copy_v5 = copy_raw.get("next_hypothesis_v5") if copy_raw is not None else None
    copy_v5 = (
        dict(raw_copy_v5)
        if isinstance(raw_copy_v5, dict)
        else {
            "schema_version": "hypersmart.copy_vault_v5_lifecycle_train.v1",
            "status": "COPY_VAULT_V5_REPORT_MISSING",
            "selection_eligible": False,
            "physical_freeze_allowed": False,
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
            "heldout_evaluated": False,
            "paper_read_only": True,
            "real_execution": False,
        }
    )

    paths = {
        "lead_lag": _write_json(project_root, "lead_lag_multiasset_train", lead),
        "cross_venue": _write_json(project_root, "cross_venue_v4_train", cross),
        "cross_venue_persistence_v5": _write_json(
            project_root,
            "cross_venue_v5_persistence_train",
            cross_v5,
        ),
        "copy_vault": _write_json(project_root, "copy_vault_vnext_train", copy),
        "copy_vault_continuation_v4": _write_json(
            project_root, "copy_vault_v4_train", copy_v4
        ),
        "copy_vault_lifecycle_v5": _write_json(
            project_root, "copy_vault_v5_lifecycle_train", copy_v5
        ),
    }
    families = {
        "lead_lag": lead,
        "cross_venue": cross,
        "copy_vault": copy,
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "certification_status": "TRAIN_ONLY_NOT_CERTIFIED",
        "freeze_hash": None,
        "post_freeze_oos_consumed": False,
        "heldout_evaluated": False,
        "canonical_campaigns_mutated": False,
        "families": {
            family: {
                "status": value.get("status"),
                "selection_eligible": value.get("selection_eligible") is True,
                "physical_freeze_allowed": value.get("physical_freeze_allowed") is True,
                "freeze_candidate_sha256": value.get("freeze_candidate_sha256"),
            }
            for family, value in families.items()
        },
        "lead_source_alignment": lead_alignment,
        "research_variants": {
            "cross_venue_persistence_v5": {
                "status": cross_v5.get("status"),
                "selection_eligible": cross_v5.get("selection_eligible") is True,
                "physical_freeze_allowed": cross_v5.get("physical_freeze_allowed") is True,
                "freeze_candidate_sha256": cross_v5.get("freeze_candidate_sha256"),
                "heldout_evaluated": cross_v5.get("heldout_evaluated") is True,
            },
            "copy_vault_continuation_v4": {
                "status": copy_v4.get("status"),
                "selection_eligible": copy_v4.get("selection_eligible") is True,
                "physical_freeze_allowed": copy_v4.get("physical_freeze_allowed") is True,
                "freeze_candidate_sha256": copy_v4.get("freeze_candidate_sha256"),
                "heldout_evaluated": copy_v4.get("heldout_evaluated") is True,
            },
            "copy_vault_lifecycle_v5": {
                "status": copy_v5.get("status"),
                "selection_eligible": copy_v5.get("selection_eligible") is True,
                "physical_freeze_allowed": copy_v5.get("physical_freeze_allowed") is True,
                "freeze_candidate_sha256": copy_v5.get("freeze_candidate_sha256"),
                "heldout_evaluated": copy_v5.get("heldout_evaluated") is True,
            }
        },
        "reports": {
            key: path.relative_to(project_root).as_posix() for key, path in paths.items()
        },
        "paper_read_only": True,
        "real_execution": False,
    }
    summary_path = _write_json(project_root, "VNext_SUMMARY", summary)
    summary["summary_path"] = summary_path.relative_to(project_root).as_posix()
    return summary


__all__ = ["REPORT_DIR", "SCHEMA_VERSION", "run_economic_vnext_pack"]
