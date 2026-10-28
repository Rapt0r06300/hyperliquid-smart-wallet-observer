"""Presentation and immutable checkpoint evidence for Copy-Vault research."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from hl_observer.economics.numeric import decimal_value

CORRECTION_CYCLE_BUNDLE_SCHEMA = "hypersmart.copy_vault_correction_cycle_bundle.v2"
_SUPPORTED_CORRECTION_CYCLE_BUNDLE_SCHEMAS = frozenset({
    "hypersmart.copy_vault_correction_cycle_bundle.v1",
    CORRECTION_CYCLE_BUNDLE_SCHEMA,
})
CORRECTION_CYCLE_EVIDENCE_CATEGORIES = (
    "data", "code", "config", "parameters", "attempts", "costs", "ledger",
    "tests", "verdict", "restoration",
)
_EVIDENCE_STATUSES = frozenset({
    "VERIFIED", "NOT_RUN", "UNVERIFIED", "MORE_DATA", "UNMEASURABLE",
    "NOT_APPLICABLE", "FAILED",
})
_CYCLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FULL_COMMIT_SHA_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("evidence bundle must contain finite JSON values only") from exc


def _bundle_digest(bundle: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    return hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest()


def _bundle_structure_error(bundle: Mapping[str, Any]) -> str | None:
    schema = bundle.get("schema")
    if not isinstance(schema, str) or schema not in _SUPPORTED_CORRECTION_CYCLE_BUNDLE_SCHEMAS:
        return "unsupported correction cycle evidence schema"
    if not isinstance(bundle.get("cycle_id"), str) or not _CYCLE_ID_RE.fullmatch(
        bundle["cycle_id"],
    ):
        return "invalid correction cycle identifier"
    if not isinstance(bundle.get("head"), str) or not _FULL_COMMIT_SHA_RE.fullmatch(
        bundle["head"],
    ):
        return "head must be a full hexadecimal commit SHA"
    if bundle.get("paper_read_only") is not True or bundle.get("real_execution") is not False:
        return "paper/read-only invariant mismatch"
    evidence = bundle.get("evidence")
    if not isinstance(evidence, Mapping):
        return "evidence must contain all required categories"
    missing = set(CORRECTION_CYCLE_EVIDENCE_CATEGORIES) - set(evidence)
    unknown = set(evidence) - set(CORRECTION_CYCLE_EVIDENCE_CATEGORIES)
    if missing:
        return f"missing evidence categories: {', '.join(sorted(missing))}"
    if unknown:
        return f"unknown evidence categories: {', '.join(sorted(unknown))}"
    for category in CORRECTION_CYCLE_EVIDENCE_CATEGORIES:
        item = evidence[category]
        status = item.get("status") if isinstance(item, Mapping) else None
        if not isinstance(status, str) or status not in _EVIDENCE_STATUSES:
            return f"evidence category {category} has an invalid status"
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, list):
        return "artifacts must be a list"
    seen_paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            return "artifact record must be an object"
        artifact_path = artifact.get("path")
        if not isinstance(artifact_path, str):
            return "artifact path must be a relative path inside repository"
        normalized = artifact_path.replace("\\", "/")
        relative = PurePosixPath(normalized)
        windows_relative = PureWindowsPath(artifact_path)
        if (
            relative.is_absolute() or windows_relative.is_absolute() or windows_relative.drive
            or ".." in relative.parts or not relative.parts
        ):
            return "artifact path must be a relative path inside repository"
        canonical_path = relative.as_posix()
        if canonical_path in seen_paths:
            return f"duplicate evidence artifact path: {canonical_path}"
        seen_paths.add(canonical_path)
        size = artifact.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            return f"{canonical_path}: invalid artifact byte count"
        digest = artifact.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            return f"{canonical_path}: invalid artifact SHA-256"
        origin = artifact.get("origin")
        if origin is not None:
            try:
                _normalize_artifact_path(origin)
            except (TypeError, ValueError):
                return f"{canonical_path}: invalid artifact origin"
    for category in CORRECTION_CYCLE_EVIDENCE_CATEGORIES:
        item = evidence[category]
        status = item["status"]
        references = item.get("artifact_refs", [])
        if not isinstance(references, list) or any(not isinstance(ref, str) for ref in references):
            return f"evidence category {category} has invalid artifact references"
        if status == "VERIFIED" and schema == CORRECTION_CYCLE_BUNDLE_SCHEMA and not references:
            return f"verified evidence category {category} must reference listed artifacts"
        normalized_references: set[str] = set()
        for reference in references:
            try:
                canonical_reference = _normalize_artifact_path(reference)
            except ValueError:
                return f"evidence category {category} has an unsafe artifact reference"
            normalized_references.add(canonical_reference)
        if len(normalized_references) != len(references):
            return f"evidence category {category} has duplicate artifact references"
        if not normalized_references.issubset(seen_paths):
            return f"evidence category {category} must reference listed artifacts"
    try:
        _canonical_json_bytes(dict(bundle))
    except ValueError:
        return "evidence bundle contains non-JSON or non-finite values"
    return None


def _normalize_artifact_path(artifact_path: str) -> str:
    if not isinstance(artifact_path, str) or not artifact_path.strip():
        raise ValueError("artifact path must be a relative path inside repository")
    normalized = artifact_path.replace("\\", "/")
    relative = PurePosixPath(normalized)
    windows_relative = PureWindowsPath(artifact_path)
    if (
        relative.is_absolute() or windows_relative.is_absolute() or windows_relative.drive
        or ".." in relative.parts or not relative.parts
    ):
        raise ValueError("artifact path must be a relative path inside repository")
    return relative.as_posix()


def _resolve_evidence_artifact(repo_root: Path, artifact_path: str) -> tuple[Path, str]:
    relative_path = _normalize_artifact_path(artifact_path)
    relative = PurePosixPath(relative_path)

    root = repo_root.resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("evidence artifacts cannot traverse symbolic links")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("artifact path must resolve inside repository") from exc
    if not resolved.is_file():
        raise ValueError("evidence artifact must be a regular file")
    return resolved, relative.as_posix()


def _check_no_symlink_path(root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(_normalize_artifact_path(relative_path))
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("evidence artifact paths cannot traverse symbolic links")
    try:
        cursor.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError("evidence artifact path must resolve inside repository") from exc
    return cursor


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def snapshot_correction_cycle_artifacts(
    *,
    repo_root: str | os.PathLike[str],
    artifact_paths: tuple[str, ...] | list[str],
    snapshot_dir: str,
) -> list[dict[str, Any]]:
    """Copy artifact bytes into a create-only cycle snapshot and return their paths."""
    root = Path(repo_root).resolve(strict=True)
    snapshot_relative = _normalize_artifact_path(snapshot_dir)
    snapshot_root = _check_no_symlink_path(root, snapshot_relative)
    snapshot_root.mkdir(parents=True, exist_ok=True)
    _check_no_symlink_path(root, snapshot_relative)

    snapshots: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for source_path in artifact_paths:
        source, source_relative = _resolve_evidence_artifact(root, source_path)
        if source_relative in seen_sources:
            raise ValueError(f"duplicate evidence artifact path: {source_relative}")
        seen_sources.add(source_relative)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".artifact-snapshot.", suffix=".tmp", dir=snapshot_root,
        )
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(descriptor, "wb") as target_stream:
                with source.open("rb") as source_stream:
                    initial_stat = os.fstat(source_stream.fileno())
                    for chunk in iter(lambda: source_stream.read(1024 * 1024), b""):
                        target_stream.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    final_stat = os.fstat(source_stream.fileno())
                    if (
                        initial_stat.st_size != final_stat.st_size
                        or initial_stat.st_mtime_ns != final_stat.st_mtime_ns
                        or initial_stat.st_ino != final_stat.st_ino
                        or final_stat.st_size != size
                    ):
                        raise RuntimeError(f"artifact changed while snapshotting: {source_relative}")
                target_stream.flush()
                os.fsync(target_stream.fileno())
            sha256 = digest.hexdigest()
            source_name_digest = hashlib.sha256(source_relative.encode("utf-8")).hexdigest()[:12]
            target_name = f"{sha256}-{source_name_digest}.blob"
            target_relative = (PurePosixPath(snapshot_relative) / target_name).as_posix()
            target = _check_no_symlink_path(root, target_relative)
            try:
                os.link(temporary, target)
            except FileExistsError:
                existing_size, existing_sha256 = _sha256_file(target)
                if (existing_size, existing_sha256) != (size, sha256):
                    raise FileExistsError(
                        f"immutable artifact snapshot already differs: {target_relative}"
                    ) from None
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()
        snapshots.append({
            "source_path": source_relative,
            "snapshot_path": target_relative,
            "bytes": size,
            "sha256": sha256,
        })
    return snapshots


def build_correction_cycle_bundle(
    *,
    cycle_id: str,
    head: str,
    evidence: Mapping[str, Mapping[str, Any]],
    repo_root: str | os.PathLike[str],
    artifact_paths: tuple[str, ...] | list[str] = (),
    artifact_origins: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic checkpoint bound to a full Git SHA and exact files.

    Every proof domain is required, but its status may honestly remain NOT_RUN,
    UNVERIFIED, MORE_DATA, or UNMEASURABLE. This records evidence; it does not
    certify economic performance.
    """
    if not isinstance(cycle_id, str) or not _CYCLE_ID_RE.fullmatch(cycle_id):
        raise ValueError("cycle_id must be a safe, non-empty identifier")
    if not isinstance(head, str) or not _FULL_COMMIT_SHA_RE.fullmatch(head):
        raise ValueError("head must be a full hexadecimal commit SHA")
    if not isinstance(evidence, Mapping):
        raise ValueError("evidence must contain all required categories")
    missing = set(CORRECTION_CYCLE_EVIDENCE_CATEGORIES) - set(evidence)
    unknown = set(evidence) - set(CORRECTION_CYCLE_EVIDENCE_CATEGORIES)
    if missing:
        raise ValueError(f"missing evidence categories: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"unknown evidence categories: {', '.join(sorted(unknown))}")

    normalized_evidence: dict[str, dict[str, Any]] = {}
    for category in CORRECTION_CYCLE_EVIDENCE_CATEGORIES:
        item = evidence[category]
        if not isinstance(item, Mapping):
            raise ValueError(f"evidence category {category} must be an object")
        status = item.get("status")
        if not isinstance(status, str) or status not in _EVIDENCE_STATUSES:
            raise ValueError(f"evidence category {category} has an invalid status")
        normalized_item = json.loads(_canonical_json_bytes(dict(item)))
        normalized_evidence[category] = normalized_item

    root = Path(repo_root)
    artifacts = []
    seen_paths: set[str] = set()
    origins = {
        _normalize_artifact_path(path): _normalize_artifact_path(origin)
        for path, origin in (artifact_origins or {}).items()
    }
    for artifact_path in artifact_paths:
        artifact, relative_path = _resolve_evidence_artifact(root, artifact_path)
        if relative_path in seen_paths:
            raise ValueError(f"duplicate evidence artifact path: {relative_path}")
        seen_paths.add(relative_path)
        size, sha256 = _sha256_file(artifact)
        row = {"path": relative_path, "bytes": size, "sha256": sha256}
        if relative_path in origins:
            row["origin"] = origins[relative_path]
        artifacts.append(row)
    artifacts.sort(key=lambda row: row["path"])
    if not set(origins).issubset(seen_paths):
        raise ValueError("artifact origin must refer to a listed artifact")

    listed_artifact_paths = {artifact["path"] for artifact in artifacts}
    for category, item in normalized_evidence.items():
        status = item["status"]
        references = item.get("artifact_refs", [])
        if not isinstance(references, list) or any(not isinstance(ref, str) for ref in references):
            raise ValueError(f"evidence category {category} has invalid artifact references")
        canonical_references = [_normalize_artifact_path(ref) for ref in references]
        if len(set(canonical_references)) != len(canonical_references):
            raise ValueError(f"evidence category {category} has duplicate artifact references")
        if status == "VERIFIED" and not canonical_references:
            raise ValueError(f"verified evidence category {category} must reference listed artifacts")
        if not set(canonical_references).issubset(listed_artifact_paths):
            raise ValueError(f"evidence category {category} must reference listed artifacts")
        if "artifact_refs" in item:
            item["artifact_refs"] = canonical_references

    bundle: dict[str, Any] = {
        "schema": CORRECTION_CYCLE_BUNDLE_SCHEMA,
        "cycle_id": cycle_id,
        "head": head.lower(),
        "paper_read_only": True,
        "real_execution": False,
        "evidence": normalized_evidence,
        "artifacts": artifacts,
    }
    bundle["bundle_sha256"] = _bundle_digest(bundle)
    return bundle


def create_correction_cycle_bundle(
    bundle: Mapping[str, Any], destination: str | os.PathLike[str],
) -> Path:
    """Publish an immutable receipt; identical retries are safe, edits are refused."""
    if bundle.get("schema") != CORRECTION_CYCLE_BUNDLE_SCHEMA:
        raise ValueError("unsupported correction cycle evidence schema")
    structure_error = _bundle_structure_error(bundle)
    if structure_error is not None:
        raise ValueError(structure_error)
    if bundle.get("bundle_sha256") != _bundle_digest(bundle):
        raise ValueError("correction cycle evidence bundle hash mismatch")
    encoded = _canonical_json_bytes(dict(bundle)) + b"\n"
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # A hard-link publish is atomic and fails if the immutable name exists.
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() != encoded:
                raise
        return target
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def verify_correction_cycle_bundle(
    bundle_path: str | os.PathLike[str], *, repo_root: str | os.PathLike[str],
) -> dict[str, Any]:
    """Verify the receipt digest and every referenced local artifact hash/size."""
    path = Path(bundle_path)
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"valid": False, "bundle_error": f"cannot read evidence bundle: {exc}",
                "artifact_errors": []}
    if not isinstance(bundle, dict):
        return {"valid": False, "bundle_error": "evidence bundle must be an object",
                "artifact_errors": []}
    schema = bundle.get("schema")
    if not isinstance(schema, str) or schema not in _SUPPORTED_CORRECTION_CYCLE_BUNDLE_SCHEMAS:
        return {"valid": False, "bundle_error": "unsupported evidence bundle schema",
                "artifact_errors": []}
    structure_error = _bundle_structure_error(bundle)
    if structure_error is not None:
        return {"valid": False, "bundle_error": structure_error, "artifact_errors": []}
    expected_digest = bundle.get("bundle_sha256")
    try:
        digest_valid = isinstance(expected_digest, str) and _bundle_digest(bundle) == expected_digest
    except ValueError:
        digest_valid = False
    artifact_errors: list[str] = []
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, list):
        artifact_errors.append("artifacts: expected a list")
        artifacts = []
    root = Path(repo_root)
    for row in artifacts:
        if not isinstance(row, Mapping) or not isinstance(row.get("path"), str):
            artifact_errors.append("artifact: malformed record")
            continue
        artifact_path = row["path"]
        try:
            artifact, relative_path = _resolve_evidence_artifact(root, artifact_path)
            size, sha256 = _sha256_file(artifact)
        except (OSError, ValueError) as exc:
            artifact_errors.append(f"{artifact_path}: {exc}")
            continue
        if size != row.get("bytes") or sha256 != row.get("sha256"):
            artifact_errors.append(f"{relative_path}: SHA-256 or byte count mismatch")
    return {
        "valid": digest_valid and not artifact_errors,
        "bundle_sha256_valid": digest_valid,
        "artifact_errors": artifact_errors,
    }


def temporal_evidence(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    """Project an evaluation into the canonical temporal proof payload."""

    segments = evaluation.get("segments") if isinstance(evaluation.get("segments"), Mapping) else {}
    oos_summary = (segments.get("oos") or {}).get("summary") or {}
    forward_summary = (segments.get("forward") or {}).get("summary") or {}
    placebo_summary = (evaluation.get("placebo_inverted_oos") or {}).get("summary") or {}
    oos_count = int(oos_summary.get("positions_fermees") or 0)
    forward_count = int(forward_summary.get("positions_fermees") or 0)
    placebo_count = int(placebo_summary.get("positions_fermees") or 0)
    oos_net = oos_summary.get("net_pnl_usd") if oos_count > 0 else None
    placebo_net = placebo_summary.get("net_pnl_usd") if placebo_count > 0 else None
    oos_net_exact = (
        decimal_value(oos_summary.get("net_pnl_usd_exact_decimal"))
        if oos_count > 0 else None
    )
    placebo_net_exact = (
        decimal_value(placebo_summary.get("net_pnl_usd_exact_decimal"))
        if placebo_count > 0 else None
    )
    oos_net_comparable = (
        oos_net_exact if oos_net_exact is not None else decimal_value(oos_net)
    )
    placebo_net_comparable = (
        placebo_net_exact
        if placebo_net_exact is not None else decimal_value(placebo_net)
    )
    forward_trades = (
        (evaluation.get("trades") or {}).get("forward") or []
        if isinstance(evaluation.get("trades"), Mapping) else []
    )
    causal_forward = bool(forward_trades) and all(
        row.get("causal_forward_eligible") is True for row in forward_trades
    )
    no_lookahead = evaluation.get("causal_observation_required_all_segments") is True
    purged = evaluation.get("temporal_purge_verified") is True

    def proof_segment(summary: Mapping[str, Any], *, count: int) -> dict[str, Any]:
        return {key: summary.get(key) for key in (
            "gross_pnl_usd", "fees_usd", "spread_cost_usd", "slippage_cost_usd",
            "latency_cost_usd", "net_pnl_usd", "net_pnl_usd_exact_decimal",
            "trade_ids_count", "trade_ids_sha256",
            "duplicate_trade_ids",
        )} | {"sample_count": count, "liquidatable_net": summary.get("LIQUIDATABLE_NET") is True}

    return {
        "oos": {
            **proof_segment(oos_summary, count=oos_count),
            "no_lookahead": no_lookahead,
            "purged": purged,
        },
        "forward": {
            **proof_segment(forward_summary, count=forward_count),
            "post_freeze": causal_forward, "causal_live_only": causal_forward,
        },
        "placebos": {
            "beaten": (
                oos_net_comparable is not None
                and placebo_net_comparable is not None
                and oos_net_comparable > placebo_net_comparable
            ),
            "candidate_net_usd": oos_net, "placebo_net_usd": placebo_net,
            "candidate_net_usd_exact_decimal": (
                format(oos_net_exact, "f") if oos_net_exact is not None else None
            ),
            "placebo_net_usd_exact_decimal": (
                format(placebo_net_exact, "f") if placebo_net_exact is not None else None
            ),
            "method": "same_metaorders_inverted_direction",
        },
    }


__all__ = [
    "CORRECTION_CYCLE_BUNDLE_SCHEMA",
    "CORRECTION_CYCLE_EVIDENCE_CATEGORIES",
    "build_correction_cycle_bundle",
    "create_correction_cycle_bundle",
    "snapshot_correction_cycle_artifacts",
    "temporal_evidence",
    "verify_correction_cycle_bundle",
]
