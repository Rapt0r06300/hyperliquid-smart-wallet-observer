"""Reconcile the authoritative roadmap sources without inventing history.

This module is intentionally local and read-only.  It answers four governance
questions that are easy to conflate:

* is the sealed 1..775 registry present and honest about source loss;
* is the V5/776+ technical roadmap distinct from that registry;
* are the numbered complementary ideas inventoried without duplicates; and
* do current documents identify their historical documents and hashes.

It does not reconstruct missing historical labels, promote economic results,
or mutate any task manager state.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

_IDEA_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")


@dataclass(frozen=True)
class ReconciliationResult:
    """A bounded, hashable result of the four authority checks."""

    legacy_775: dict[str, Any]
    v5_776_plus: dict[str, Any]
    complementary_ideas: dict[str, Any]
    documentation: dict[str, Any]

    @property
    def complete(self) -> bool:
        return all(
            section.get("complete") is True
            for section in (
                self.legacy_775,
                self.v5_776_plus,
                self.complementary_ideas,
                self.documentation,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "alina.smart_flow.roadmap_authority_reconciliation.v1",
            "complete": self.complete,
            "legacy_775": self.legacy_775,
            "v5_776_plus": self.v5_776_plus,
            "complementary_ideas": self.complementary_ideas,
            "documentation": self.documentation,
        }


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_file(root: Path, relative: str) -> tuple[Path, str]:
    path = root / relative
    if not path.is_file():
        raise ValueError(f"required roadmap authority file is missing: {relative}")
    return path, _sha256_file(path)


def _read_json(root: Path, relative: str) -> tuple[dict[str, Any], str]:
    path, digest = _require_file(root, relative)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"roadmap authority JSON must be an object: {relative}")
    return value, digest


def _contains_all(text: str, markers: tuple[str, ...], *, label: str) -> None:
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise ValueError(f"{label} is missing required markers: {missing}")


def reconcile_legacy_775(root: Path) -> dict[str, Any]:
    """Verify the sealed registry and preserve its terminal source-loss state."""

    relative = "docs/PRE_RUN_775_CANONICAL_STATUS.json"
    status, digest = _read_json(root, relative)
    required = {
        "roadmap_id": "HYPERSMART_PNL_CANONICAL_775",
        "total": 775,
        "technical_completion_total": 775,
        "technical_completion_done": 775,
        "literal_source_unrecoverable": True,
        "exact_literal_reconstruction_claimed": False,
        "technical_completion_claimed": True,
        "recovery_state": "TERMINAL_SOURCE_LOSS_HONEST",
    }
    mismatches = {
        key: {"expected": expected, "actual": status.get(key)}
        for key, expected in required.items()
        if status.get(key) != expected
    }
    source_searches = status.get("source_searches_completed")
    complete = not mismatches and isinstance(source_searches, list) and bool(source_searches)
    return {
        "complete": complete,
        "status": "SOURCE_LOSS_CLOSED" if complete else "INVALID",
        "source": relative,
        "source_sha256": digest,
        "technical_control_count": status.get("technical_completion_done"),
        "recovered_literal_count": status.get("recovered_literal_count"),
        "source_searches_completed": source_searches,
        "literal_reconstruction_claimed": status.get("exact_literal_reconstruction_claimed"),
        "mismatches": mismatches,
    }


def reconcile_v5_776_plus(root: Path) -> dict[str, Any]:
    """Verify that the current V5/776+ authority is distinct and traceable."""

    current_path, current_digest = _require_file(root, "docs/CURRENT_STATE.md")
    constitution_path, constitution_digest = _require_file(root, "docs/HYPERSMART_CONSTITUTION.md")
    mapping_path, mapping_digest = _require_file(root, "docs/audit/ROADMAP_V5_LOT05_COPY_VAULT_MAPPING.md")
    current = current_path.read_text(encoding="utf-8")
    constitution = constitution_path.read_text(encoding="utf-8")
    mapping = mapping_path.read_text(encoding="utf-8")
    _contains_all(current, ("775 optimisations pré-run", "Roadmap technique cumulative V5 / 776+"), label="CURRENT_STATE")
    _contains_all(constitution, ("V5/776+", "roadmap technique"), label="HYPERSMART_CONSTITUTION")
    _contains_all(mapping, ("§10", "776+", "Copy-Vault"), label="Copy-Vault mapping")
    return {
        "complete": True,
        "status": "DISTINCT_CURRENT_AUTHORITY",
        "sources": {
            "docs/CURRENT_STATE.md": current_digest,
            "docs/HYPERSMART_CONSTITUTION.md": constitution_digest,
            "docs/audit/ROADMAP_V5_LOT05_COPY_VAULT_MAPPING.md": mapping_digest,
        },
        "pre_run_775_is_separate": True,
        "copy_vault_mapping_present": True,
    }


def inventory_complementary_ideas(root: Path) -> dict[str, Any]:
    """Inventory numbered ideas; keep them as a reservoir, not as Done work."""

    relative = "docs/IDEAS_BANK.md"
    path, digest = _require_file(root, relative)
    ideas: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _IDEA_RE.match(line)
        if match:
            number = int(match.group(1))
            if number in ideas:
                raise ValueError(f"duplicate complementary idea number: {number}")
            ideas[number] = match.group(2)
    expected = list(range(1, 101))
    missing = [number for number in expected if number not in ideas]
    unexpected = sorted(number for number in ideas if number not in expected)
    return {
        "complete": not missing and not unexpected,
        "status": "INVENTORIED_NOT_PROMOTED",
        "source": relative,
        "source_sha256": digest,
        "idea_count": len(ideas),
        "first_id": min(ideas) if ideas else None,
        "last_id": max(ideas) if ideas else None,
        "missing_ids": missing,
        "unexpected_ids": unexpected,
        "promotion_rule": "idea inventory is not implementation or economic proof",
    }


def reconcile_documentation(root: Path) -> dict[str, Any]:
    """Hash the current documentation and classify known historical surfaces."""

    current_relative = "docs/CURRENT_STATE.md"
    current_path, current_digest = _require_file(root, current_relative)
    current = current_path.read_text(encoding="utf-8")
    _contains_all(
        current,
        ("# Alina SmartFlow", "Documents historiques", "source de vérité"),
        label="CURRENT_STATE",
    )
    current_sources = (
        "docs/CURRENT_STATE.md",
        "docs/HYPERSMART_CONSTITUTION.md",
        "docs/CODEX_GOAL_RUNBOOK.md",
        "docs/TASKLIST_EVIDENCE_MATRIX.md",
        "docs/IDEAS_BANK.md",
        "docs/PRE_RUN_775_CANONICAL_STATUS.json",
        "docs/PRE_RUN_775_SOURCE_LOSS_CLOSURE.md",
    )
    historical_sources = (
        "docs/archive/root-history/TASKLIST.md",
        "docs/archive/root-history/TASKLIST.md.avant_cloture",
        "docs/TASKLIST_ACTIVE.md",
        "docs/ETAT_ET_FEUILLE_DE_ROUTE.md",
    )
    current_hashes = {relative: _sha256_file(_require_file(root, relative)[0]) for relative in current_sources}
    historical_hashes = {relative: _sha256_file(_require_file(root, relative)[0]) for relative in historical_sources}
    return {
        "complete": True,
        "status": "CURRENT_AND_HISTORICAL_CLASSIFIED",
        "current_source": current_relative,
        "current_source_sha256": current_digest,
        "current_sources": current_hashes,
        "historical_sources": historical_hashes,
        "historical_sources_are_not_current_authority": True,
    }


def reconcile_authority(root: Path) -> ReconciliationResult:
    """Run all four checks without network, writes, or task-manager calls."""

    root = root.resolve()
    return ReconciliationResult(
        legacy_775=reconcile_legacy_775(root),
        v5_776_plus=reconcile_v5_776_plus(root),
        complementary_ideas=inventory_complementary_ideas(root),
        documentation=reconcile_documentation(root),
    )

