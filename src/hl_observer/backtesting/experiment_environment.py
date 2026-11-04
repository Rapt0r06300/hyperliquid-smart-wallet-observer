"""Immutable, deterministic environment freeze for Copy-Vault experiments."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from collections.abc import Mapping
import re
from typing import Any


SCHEMA_VERSION = "hypersmart.copy_vault.experiment_environment.v1"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _required_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return value.lower()


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _canonical_payload(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def build_environment_freeze(
    *,
    code_sha256: str,
    dependency_lock_sha256: str,
    dependencies: Mapping[str, str],
    python_version: str | None = None,
    platform_name: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    """Build a stable environment manifest from explicit immutable inputs."""
    if not isinstance(dependencies, Mapping) or not dependencies:
        raise ValueError("dependencies must be a non-empty mapping")
    normalized_dependencies: dict[str, str] = {}
    for name, version in dependencies.items():
        key = _required_text(name, "dependency name")
        normalized_dependencies[key] = _required_text(version, f"dependency {key}")
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "code_sha256": _required_sha(code_sha256, "code_sha256"),
        "dependency_lock_sha256": _required_sha(
            dependency_lock_sha256, "dependency_lock_sha256"
        ),
        "dependencies": dict(sorted(normalized_dependencies.items())),
        "python_version": _required_text(
            python_version if python_version is not None else platform.python_version(),
            "python_version",
        ),
        "platform": _required_text(
            platform_name if platform_name is not None else sys.platform,
            "platform",
        ),
        "architecture": _required_text(
            architecture if architecture is not None else platform.machine(),
            "architecture",
        ),
    }
    payload["environment_sha256"] = hashlib.sha256(
        _canonical_payload(payload)
    ).hexdigest()
    return payload


def verify_environment_freeze(payload: Mapping[str, Any]) -> bool:
    """Return true only when the manifest is complete and self-consistent."""
    if not isinstance(payload, Mapping):
        return False
    expected = payload.get("environment_sha256")
    if not isinstance(expected, str) or _SHA256_RE.fullmatch(expected) is None:
        return False
    body = dict(payload)
    body.pop("environment_sha256", None)
    try:
        rebuilt = build_environment_freeze(
            code_sha256=body["code_sha256"],
            dependency_lock_sha256=body["dependency_lock_sha256"],
            dependencies=body["dependencies"],
            python_version=body["python_version"],
            platform_name=body["platform"],
            architecture=body["architecture"],
        )
    except (KeyError, TypeError, ValueError):
        return False
    return body.get("schema_version") == SCHEMA_VERSION and rebuilt == dict(payload)


__all__ = ["SCHEMA_VERSION", "build_environment_freeze", "verify_environment_freeze"]
