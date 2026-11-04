"""ALPHA P57 — REPRODUCTIBILITÉ : empreinte complète par trial (même trial → même résultat).

Chaque trial garde code SHA, dataset hash, config hash, seed, version Python/deps, timestamps début/fin.
Deux trials avec la même empreinte (hors timestamps) doivent produire le même résultat. Pur, 0 réseau.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from importlib.metadata import PackageNotFoundError, version

UNMEASURABLE = "UNMEASURABLE"


def empreinte_repro(*, code_sha: str = UNMEASURABLE, dataset_hash: str = UNMEASURABLE,
                    config_hash: str = UNMEASURABLE, seed: Any = None,
                    start_ts_ms: Any = None, end_ts_ms: Any = None) -> dict[str, Any]:
    """Empreinte de repro d'un trial. `repro_key` = hash déterministe des champs HORS timestamps."""
    py = "%d.%d.%d" % sys.version_info[:3]
    base = "|".join(str(x) for x in (code_sha, dataset_hash, config_hash, seed, py, platform.machine()))
    repro_key = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    return {"code_sha": code_sha, "dataset_hash": dataset_hash, "config_hash": config_hash,
            "seed": seed, "python": py, "arch": platform.machine(),
            "start_ts_ms": start_ts_ms, "end_ts_ms": end_ts_ms, "repro_key": repro_key}


def meme_repro(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Deux empreintes sont reproductiblement identiques si même repro_key (timestamps ignorés)."""
    return a.get("repro_key") == b.get("repro_key")


def write_atomic_freeze_checkpoint(
    path: str | Path,
    payload: Mapping[str, Any],
    *,
    simulate_crash_before_replace: bool = False,
) -> dict[str, Any]:
    """Write a complete freeze checkpoint atomically, never a half-written champion."""
    if not isinstance(payload, Mapping) or not payload:
        raise ValueError("payload must be a non-empty mapping")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized = json.loads(json.dumps(dict(payload), sort_keys=True, allow_nan=False))
    text = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if simulate_crash_before_replace:
            raise RuntimeError("simulated crash before atomic replace")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "path": str(target),
        "committed": True,
        "payload_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "paper_only": True,
        "real_execution": False,
    }


def environment_freeze_receipt(
    packages: tuple[str, ...] = ("pytest", "numpy"),
    *,
    expected_versions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Capture local interpreter/dependency identity and flag divergence."""
    versions: dict[str, str] = {}
    missing: list[str] = []
    for package in packages:
        name = str(package).strip()
        if not name:
            return {"status": "UNMEASURABLE", "reason": "PACKAGE_NAME_EMPTY"}
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            missing.append(name)
    snapshot = {
        "python": "%d.%d.%d" % sys.version_info[:3],
        "arch": platform.machine(),
        "packages": dict(sorted(versions.items())),
    }
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    dependency_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    expected = dict(expected_versions or {})
    divergent = any(versions.get(name) != expected_version for name, expected_version in expected.items())
    status = "UNMEASURABLE" if missing else ("REJECTED" if divergent else "PROVEN")
    return {
        "status": status,
        "reason": "DEPENDENCY_VERSION_DIVERGENCE" if divergent else ("DEPENDENCY_MISSING" if missing else "ENVIRONMENT_FROZEN"),
        "snapshot": snapshot,
        "dependency_hash": dependency_hash,
        "missing_packages": tuple(missing),
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["empreinte_repro", "meme_repro", "UNMEASURABLE", "write_atomic_freeze_checkpoint", "environment_freeze_receipt"]
