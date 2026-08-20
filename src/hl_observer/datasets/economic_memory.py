"""Immutable economic proof memory partitioned by code, family, data and config."""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.simulation.economic_objective import TARGET_NET_USD

SCHEMA = "alina.economic_memory.v1"
RELATIVE_PATH = Path("runtime") / "reports" / "economic_memory" / "ECONOMIC_MEMORY.json"
CANONICAL_FAMILIES = {"copy_vault", "lead_lag", "cross_venue_dislocation_v2"}


class EconomicMemoryError(RuntimeError):
    pass


def _sha(value: object, length: int, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != length or any(ch not in "0123456789abcdef" for ch in text):
        raise EconomicMemoryError(f"{label} must be {length} hexadecimal characters")
    return text


def _family(value: object) -> str:
    name = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "cross_venue_dislocation": "cross_venue_dislocation_v2",
        "cross_venue": "cross_venue_dislocation_v2",
    }
    name = aliases.get(name, name)
    if name not in CANONICAL_FAMILIES:
        raise EconomicMemoryError(f"non canonical family: {name}")
    return name


def _certified_net(value: object, *, label: str) -> float:
    try:
        net = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise EconomicMemoryError(f"{label} must be finite") from exc
    if not math.isfinite(net):
        raise EconomicMemoryError(f"{label} must be finite")
    if net < TARGET_NET_USD:
        raise EconomicMemoryError(
            f"{label} must be >= canonical target {TARGET_NET_USD:.2f} USD"
        )
    return net


def proof_key(
    *,
    project_sha: object,
    family: object,
    dataset_snapshot_sha256: object,
    config_sha256: object,
    suite: object,
) -> str:
    payload = {
        "project_sha": _sha(project_sha, 40, "project_sha"),
        "family": _family(family),
        "dataset_snapshot_sha256": _sha(dataset_snapshot_sha256, 64, "dataset_snapshot_sha256"),
        "config_sha256": _sha(config_sha256, 64, "config_sha256"),
        "suite": str(suite or "").strip(),
    }
    if not payload["suite"]:
        raise EconomicMemoryError("suite is required")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _empty() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "proofs": {},
        "paper_only": True,
        "real_execution": False,
    }


def _path(root: str | Path) -> Path:
    return Path(root).resolve() / RELATIVE_PATH


def load_memory(root: str | Path) -> dict[str, Any]:
    path = _path(root)
    if not path.is_file():
        return _empty()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EconomicMemoryError(f"economic memory unreadable: {path}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise EconomicMemoryError("economic memory schema mismatch")
    if raw.get("paper_only") is not True or raw.get("real_execution") is not False:
        raise EconomicMemoryError("economic memory lost paper/read-only guards")
    if not isinstance(raw.get("proofs"), dict):
        raise EconomicMemoryError("economic memory proofs mapping missing")
    return raw


def record_certified_proof(
    root: str | Path,
    *,
    project_sha: object,
    family: object,
    dataset_snapshot_sha256: object,
    config_sha256: object,
    suite: object,
    runtime_proof_sha256: object,
    net_pnl_usd: object,
    analysis_complete: bool,
    certified: bool,
    paper_only: bool = True,
    real_execution: bool = False,
) -> dict[str, Any]:
    if analysis_complete is not True or certified is not True:
        raise EconomicMemoryError("incomplete or uncertified proof cannot enter economic memory")
    if paper_only is not True or real_execution is not False:
        raise EconomicMemoryError("only paper/read-only proofs are accepted")
    net = _certified_net(net_pnl_usd, label="net_pnl_usd")
    project = _sha(project_sha, 40, "project_sha")
    fam = _family(family)
    snapshot = _sha(dataset_snapshot_sha256, 64, "dataset_snapshot_sha256")
    config = _sha(config_sha256, 64, "config_sha256")
    runtime = _sha(runtime_proof_sha256, 64, "runtime_proof_sha256")
    suite_name = str(suite or "").strip()
    key = proof_key(
        project_sha=project,
        family=fam,
        dataset_snapshot_sha256=snapshot,
        config_sha256=config,
        suite=suite_name,
    )
    record = {
        "key": key,
        "project_sha": project,
        "family": fam,
        "dataset_snapshot_sha256": snapshot,
        "config_sha256": config,
        "suite": suite_name,
        "runtime_proof_sha256": runtime,
        "net_pnl_usd": net,
        "analysis_complete": True,
        "certified": True,
        "paper_only": True,
        "real_execution": False,
    }
    memory = load_memory(root)
    proofs = dict(memory["proofs"])
    previous = proofs.get(key)
    if previous is not None:
        if previous != record:
            raise EconomicMemoryError(
                "certified proof is immutable; stale/different evidence cannot silently overwrite it"
            )
        return dict(previous)
    proofs[key] = record
    payload = {**memory, "proofs": proofs, "proof_count": len(proofs)}
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return record


def load_exact_proof(
    root: str | Path,
    *,
    project_sha: object,
    family: object,
    dataset_snapshot_sha256: object,
    config_sha256: object,
    suite: object,
    runtime_proof_sha256: object | None = None,
) -> dict[str, Any]:
    key = proof_key(
        project_sha=project_sha,
        family=family,
        dataset_snapshot_sha256=dataset_snapshot_sha256,
        config_sha256=config_sha256,
        suite=suite,
    )
    record = load_memory(root)["proofs"].get(key)
    if not isinstance(record, Mapping):
        raise EconomicMemoryError("no certified proof for this exact SHA/family/snapshot/config/suite")
    if runtime_proof_sha256 is not None:
        runtime = _sha(runtime_proof_sha256, 64, "runtime_proof_sha256")
        if record.get("runtime_proof_sha256") != runtime:
            raise EconomicMemoryError("runtime proof mismatch")
    if record.get("analysis_complete") is not True or record.get("certified") is not True:
        raise EconomicMemoryError("stored proof is not certified complete")
    _certified_net(record.get("net_pnl_usd"), label="stored net_pnl_usd")
    return dict(record)


__all__ = [
    "CANONICAL_FAMILIES",
    "EconomicMemoryError",
    "RELATIVE_PATH",
    "SCHEMA",
    "load_exact_proof",
    "load_memory",
    "proof_key",
    "record_certified_proof",
]
