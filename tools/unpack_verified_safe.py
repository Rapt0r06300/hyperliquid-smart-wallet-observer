#!/usr/bin/env python3
"""Optional fail-closed expansion of an already SHA-certified SAFE corpus.

Invoked only by ALINA_SYNC_COMPLETE after RESTORE_REPORT proves exact SAFE
materialization. Never touches GitHub, private keys, trading, or unselected assets.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sys
import zlib
import re
from pathlib import Path

CANONICAL_REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
RESERVE_BYTES = 1024 ** 3
MAX_SINGLE_FILE_BYTES = (1 << 32) - 1


def _windows_io_path(path: Path) -> Path:
    """Reuse the restore layer's extended-path handling for every corpus file."""
    try:
        from tools.restore_alina import _windows_io_path as normalize
    except ModuleNotFoundError:
        from restore_alina import _windows_io_path as normalize
    return normalize(Path(path))


class SafeUnpackError(RuntimeError):
    pass


def _hash(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def _json_atomic(path: Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".partial")
    if path.is_symlink() or tmp.is_symlink():
        raise SafeUnpackError(f"unsafe output symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _catalog_safe_bytes(
    index_path: Path,
    destination: Path,
    digest: str,
    *,
    family_prefix: str | None = None,
) -> tuple[dict[Path, tuple[int, str]], list[str]]:
    """Re-derive the selected gzip identities from the SHA-bound catalog."""
    if index_path.is_symlink() or not index_path.is_file():
        raise SafeUnpackError("canonical catalog missing or symlinked")
    if _hash(index_path) != digest:
        raise SafeUnpackError("canonical DATA_INDEX changed after SAFE restoration")
    try:
        from tools.partitioned_data_index import select_index_rows
        from tools.restore_alina import _safe_component
    except ModuleNotFoundError:
        from partitioned_data_index import select_index_rows
        from restore_alina import _safe_component
    try:
        _metadata, rows = select_index_rows(
            index_path,
            lambda row: (
                row.get("quality_status") == "SAFE"
                and (
                    family_prefix is None
                    or str(row.get("family") or "").startswith(family_prefix)
                )
            ),
        )
    except (ValueError, OSError, TypeError) as exc:
        raise SafeUnpackError(f"canonical catalog partition verification failed: {exc}") from exc
    if _hash(index_path) != digest:
        raise SafeUnpackError("canonical DATA_INDEX changed during SAFE selection")
    expected: dict[Path, tuple[int, str]] = {}
    families: set[str] = set()
    for row in rows:
        if (row.get("replay_compatible") is not True
                or row.get("validation_allowed") is False
                or row.get("asset_verified") is False):
            raise SafeUnpackError("SAFE catalog row is not replay-admissible")
        sha = str(row.get("sha256") or "").lower()
        size = row.get("bytes")
        tag = str(row.get("release_tag") or "")
        ident = str(row.get("dataset_id") or "")
        if (not tag or not ident or type(size) is not int or size <= 0
                or re.fullmatch(r"[0-9a-f]{64}", sha) is None):
            raise SafeUnpackError("SAFE catalog row has no valid compressed byte identity")
        path = (
            destination / "usable" / "shards" / _safe_component(tag)
            / (_safe_component(ident) + ".jsonl.gz")
        )
        if path in expected:
            raise SafeUnpackError(f"duplicated SAFE shard output path: {path}")
        expected[path] = (size, sha)
        families.add(str(row.get("family") or ""))
    return expected, sorted(families)


def expand_safe_corpus(
    destination: Path, *, catalog_sha256: str, catalog_path: Path,
) -> dict:
    destination_display = Path(destination).resolve()
    destination = _windows_io_path(destination_display)
    catalog_path = _windows_io_path(Path(catalog_path).absolute())
    # All paths derived from destination now retain the extended Windows
    # prefix, including deeply nested immutable Release and dataset names.
    # Invalidate any prior success before every validation, including missing
    # or mismatched RESTORE_REPORT/catalog. No stale green report may survive.
    _json_atomic(destination / "UNPACK_REPORT.json", {
        "schema": "alina.safe_unpack_report.v1",
        "status": "UNPACK_IN_PROGRESS_NOT_CERTIFIED",
        "catalog_index_sha256": catalog_sha256,
    })
    certificate = destination / "RESTORE_REPORT.json"
    if certificate.is_symlink() or not certificate.is_file():
        raise SafeUnpackError("missing verified RESTORE_REPORT.json")
    restored = json.loads(certificate.read_text(encoding="utf-8"))
    classification = restored.get("classification")
    binding = restored.get("catalog_verification")
    selection_scope = str(
        restored.get("selection_scope")
        or (binding.get("selection_scope") if isinstance(binding, dict) else "")
        or "ALL_SAFE_REPLAYABLE"
    )
    if (restored.get("status") != "REPLAY_READY_COMPLETE"
            or restored.get("repository") != CANONICAL_REPOSITORY
            or not isinstance(classification, dict)
            or classification.get("materialization_complete") is not True
            or not isinstance(binding, dict)
            or binding.get("source_index_sha256") != catalog_sha256):
        raise SafeUnpackError("compressed SAFE corpus is not certified for this catalog")
    expected = classification.get("usable_shards")
    if type(expected) is not int or expected <= 0:
        raise SafeUnpackError("no certified SAFE shards to unpack")
    if selection_scope not in {"ALL_SAFE_REPLAYABLE", "COPY_VAULT_ONLY"}:
        raise SafeUnpackError("unsupported SAFE restoration scope")
    srcroot = destination / "usable" / "shards"
    outroot = destination / "usable" / "unpacked"
    if any(x.is_symlink() for x in (destination / "usable", srcroot, outroot)):
        raise SafeUnpackError("symlinked SAFE data root")
    expected_gz, catalog_families = _catalog_safe_bytes(
        Path(catalog_path), destination, catalog_sha256,
        family_prefix="copy_vault_" if selection_scope == "COPY_VAULT_ONLY" else None,
    )
    declared_families = restored.get("selection_families")
    if declared_families is None and isinstance(binding, dict):
        declared_families = binding.get("selection_families")
    if declared_families is not None and declared_families != catalog_families:
        raise SafeUnpackError("restore report SAFE family scope does not match canonical catalog")
    if len(expected_gz) != expected:
        raise SafeUnpackError(
            f"certified SAFE catalog count mismatch: {len(expected_gz)} != {expected}"
        )
    sources = sorted(expected_gz)
    if len(sources) != expected:
        raise SafeUnpackError(f"SAFE gzip count mismatch: {len(sources)} != {expected}")
    planned = []
    selected_targets: set[Path] = set()
    reused = 0
    quarantined_unsealed = 0
    required_bytes = 0
    for source in sources:
        if source.is_symlink() or source.parent.is_symlink() or not source.is_file():
            raise SafeUnpackError(f"unsafe source: {source}")
        catalog_identity = expected_gz.get(source)
        if catalog_identity is None:
            raise SafeUnpackError(f"non-SAFE gzip in usable corpus: {source}")
        expected_size, expected_sha = catalog_identity
        if source.stat().st_size != expected_size:
            raise SafeUnpackError(f"SAFE gzip size changed: {source}")
        compressed_sha = _hash(source)
        if compressed_sha != expected_sha:
            raise SafeUnpackError(f"SAFE gzip SHA-256 changed after restore: {source}")
        directory = outroot / source.parent.name
        if directory.is_symlink():
            raise SafeUnpackError(f"symlinked unpack directory: {directory}")
        target = directory / source.name[:-3]
        seal = target.with_suffix(".jsonl.alina.json")
        selected_targets.add(target)
        if target.is_symlink() or seal.is_symlink():
            raise SafeUnpackError(f"symlinked unpack target: {target}")
        if target.exists() != seal.exists():
            # Interrupted crashes can occur between renaming a JSONL and
            # publishing its independent hash receipt. Never trust or delete
            # this unsealed output: preserve it and rebuild from the SHA-bound
            # compressed source on the next attempt.
            found = target if target.exists() else seal
            if not found.is_file() or found.is_symlink():
                raise SafeUnpackError(f"unverifiable unsealed extraction: {found}")
            quarantine_dir = (
                destination / "quarantine" / "unsealed_unpacked" / source.parent.name
            )
            if quarantine_dir.is_symlink():
                raise SafeUnpackError(f"unsafe extraction quarantine: {quarantine_dir}")
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            quarantine_path = quarantine_dir / (
                found.name + "." + _hash(found)[:16] + ".unsealed"
            )
            if quarantine_path.exists() or quarantine_path.is_symlink():
                raise SafeUnpackError(f"unsealed quarantine collision: {quarantine_path}")
            found.replace(quarantine_path)
            quarantined_unsealed += 1
        if target.exists() or seal.exists():
            if not target.is_file() or not seal.is_file():
                raise SafeUnpackError(f"unsealed previously extracted file: {target}")
            try:
                proof = json.loads(seal.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                raise SafeUnpackError(f"unreadable extracted proof: {target}") from exc
            if (proof.get("compressed_sha256") != compressed_sha
                    or proof.get("jsonl_sha256") != _hash(target)
                    or proof.get("jsonl_bytes") != target.stat().st_size):
                raise SafeUnpackError(f"previous extracted file changed: {target}")
            reused += 1
            continue
        with source.open("rb") as stream:
            stream.seek(-4, 2)
            announced_bytes = int.from_bytes(stream.read(4), "little")
        if announced_bytes == 0:
            raise SafeUnpackError(f"invalid or ambiguous gzip ISIZE: {source}")
        required_bytes += announced_bytes
        planned.append((source, target, seal, announced_bytes, compressed_sha))
    # Old previously-expanded SAFE files must never pollute a changed working
    # set. Quarantine only sealed byte-identical outputs; never destroy them.
    stale_outputs = 0
    if selection_scope == "ALL_SAFE_REPLAYABLE":
        for stale in sorted(outroot.glob("*/*.jsonl")):
            if stale in selected_targets:
                continue
            seal = stale.with_suffix(".jsonl.alina.json")
            if (stale.is_symlink() or stale.parent.is_symlink() or seal.is_symlink()
                    or not stale.is_file() or not seal.is_file()):
                raise SafeUnpackError(f"unverifiable stale JSONL: {stale}")
            proof = json.loads(seal.read_text(encoding="utf-8"))
            if (proof.get("jsonl_sha256") != _hash(stale)
                    or proof.get("jsonl_bytes") != stale.stat().st_size):
                raise SafeUnpackError(f"modified stale JSONL: {stale}")
            quarantine_dir = destination / "quarantine" / "stale_unpacked" / stale.parent.name
            if quarantine_dir.is_symlink():
                raise SafeUnpackError(f"symlinked stale quarantine: {quarantine_dir}")
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            archived = quarantine_dir / (stale.name + "." + _hash(stale)[:16] + ".stale")
            archived_seal = archived.with_suffix(archived.suffix + ".alina.json")
            if archived.exists() or archived_seal.exists():
                raise SafeUnpackError(f"stale quarantine destination already exists: {archived}")
            stale.replace(archived)
            seal.replace(archived_seal)
            stale_outputs += 1
    free = shutil.disk_usage(destination).free
    if required_bytes + RESERVE_BYTES > free:
        raise SafeUnpackError(
            f"insufficient disk for JSONL expansion: need {required_bytes + RESERVE_BYTES} "
            f"bytes, free {free}; compressed verified corpus preserved"
        )
    print(
        f"ALINA_UNPACK_START files={len(planned)} reused={reused} bytes={required_bytes}",
        file=sys.stderr, flush=True,
    )
    created = 0
    written_bytes = 0
    for source, target, seal, announced_bytes, compressed_sha in planned:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".jsonl.partial")
        if tmp.is_symlink():
            raise SafeUnpackError(f"symlinked partial JSONL: {tmp}")
        tmp.unlink(missing_ok=True)
        sha = hashlib.sha256()
        size = 0
        last = b""
        try:
            with gzip.open(source, "rb") as inp, tmp.open("xb") as out:
                for line in inp:
                    size += len(line)
                    if size > announced_bytes or size > MAX_SINGLE_FILE_BYTES:
                        raise SafeUnpackError(f"gzip size exceeds declared ISIZE: {source}")
                    if len(line) > 64 * 1024 * 1024:
                        raise SafeUnpackError(f"oversized JSONL record: {source}")
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeError) as exc:
                        raise SafeUnpackError(f"invalid JSONL record: {source}") from exc
                    if not isinstance(event, dict):
                        raise SafeUnpackError(f"non-object JSONL record: {source}")
                    out.write(line)
                    sha.update(line)
                    last = line[-1:]
            if size != announced_bytes or last != b"\n":
                raise SafeUnpackError(f"JSONL truncation or invalid gzip size: {source}")
            # Protect against replacement/modification between the initial
            # catalog-bound SHA check and the end of a long extraction.
            if _hash(source) != compressed_sha:
                raise SafeUnpackError(f"SAFE gzip modified during extraction: {source}")
            tmp.replace(target)
            _json_atomic(seal, {
                "schema": "alina.safe_jsonl_proof.v1",
                "compressed_sha256": compressed_sha,
                "jsonl_sha256": sha.hexdigest(),
                "jsonl_bytes": size,
            })
        except (OSError, EOFError, zlib.error, SafeUnpackError) as exc:
            tmp.unlink(missing_ok=True)
            if isinstance(exc, SafeUnpackError):
                raise
            raise SafeUnpackError(f"SAFE gzip extraction failed: {source}: {exc}") from exc
        created += 1
        written_bytes += size
        if created == 1 or created % 100 == 0 or created == len(planned):
            print(
                f"ALINA_UNPACK_PROGRESS={created}/{len(planned)} bytes={written_bytes}",
                file=sys.stderr, flush=True,
            )
    result = {
        "schema": "alina.safe_unpack_report.v1",
        "status": "SAFE_UNPACK_COMPLETE",
        "catalog_index_sha256": catalog_sha256,
        "selection_scope": selection_scope,
        "selection_families": catalog_families,
        "certified_shards": expected,
        "created": created,
        "reused_verified": reused,
        "quarantined_stale_outputs": stale_outputs,
        "quarantined_unsealed_outputs": quarantined_unsealed,
        "new_uncompressed_bytes": written_bytes,
        "compressed_safe_retained": True,
        "unpacked_directory": str(destination_display / "usable" / "unpacked"),
    }
    _json_atomic(destination / "UNPACK_REPORT.json", result)
    return result
