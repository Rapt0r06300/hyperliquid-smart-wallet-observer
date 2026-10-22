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
from pathlib import Path

CANONICAL_REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
RESERVE_BYTES = 1024 ** 3
MAX_SINGLE_FILE_BYTES = (1 << 32) - 1


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


def expand_safe_corpus(destination: Path, *, catalog_sha256: str) -> dict:
    destination = Path(destination).resolve()
    certificate = destination / "RESTORE_REPORT.json"
    if certificate.is_symlink() or not certificate.is_file():
        raise SafeUnpackError("missing verified RESTORE_REPORT.json")
    restored = json.loads(certificate.read_text(encoding="utf-8"))
    classification = restored.get("classification")
    binding = restored.get("catalog_verification")
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
    # Invalidate any prior successful expansion proof before new work.
    _json_atomic(destination / "UNPACK_REPORT.json", {
        "schema": "alina.safe_unpack_report.v1",
        "status": "UNPACK_IN_PROGRESS_NOT_CERTIFIED",
        "catalog_index_sha256": catalog_sha256,
    })
    srcroot = destination / "usable" / "shards"
    outroot = destination / "usable" / "unpacked"
    if any(x.is_symlink() for x in (destination / "usable", srcroot, outroot)):
        raise SafeUnpackError("symlinked SAFE data root")
    sources = sorted(srcroot.glob("*/*.jsonl.gz"))
    if len(sources) != expected:
        raise SafeUnpackError(f"SAFE gzip count mismatch: {len(sources)} != {expected}")
    planned = []
    selected_targets: set[Path] = set()
    reused = 0
    required_bytes = 0
    for source in sources:
        if source.is_symlink() or source.parent.is_symlink() or not source.is_file():
            raise SafeUnpackError(f"unsafe source: {source}")
        directory = outroot / source.parent.name
        if directory.is_symlink():
            raise SafeUnpackError(f"symlinked unpack directory: {directory}")
        target = directory / source.name[:-3]
        seal = target.with_suffix(".jsonl.alina.json")
        selected_targets.add(target)
        if target.is_symlink() or seal.is_symlink():
            raise SafeUnpackError(f"symlinked unpack target: {target}")
        if target.exists() or seal.exists():
            if not target.is_file() or not seal.is_file():
                raise SafeUnpackError(f"unsealed previously extracted file: {target}")
            try:
                proof = json.loads(seal.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                raise SafeUnpackError(f"unreadable extracted proof: {target}") from exc
            if (proof.get("compressed_sha256") != _hash(source)
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
        planned.append((source, target, seal, announced_bytes))
    # Old previously-expanded SAFE files must never pollute a changed working
    # set. Quarantine only sealed byte-identical outputs; never destroy them.
    stale_outputs = 0
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
    for source, target, seal, announced_bytes in planned:
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
                while block := inp.read(8 * 1024 * 1024):
                    size += len(block)
                    if size > announced_bytes or size > MAX_SINGLE_FILE_BYTES:
                        raise SafeUnpackError(f"gzip size exceeds declared ISIZE: {source}")
                    out.write(block)
                    sha.update(block)
                    last = block[-1:]
            if size != announced_bytes or last != b"\n":
                raise SafeUnpackError(f"JSONL truncation or invalid gzip size: {source}")
            tmp.replace(target)
            _json_atomic(seal, {
                "schema": "alina.safe_jsonl_proof.v1",
                "compressed_sha256": _hash(source),
                "jsonl_sha256": sha.hexdigest(),
                "jsonl_bytes": size,
            })
        except (OSError, EOFError, gzip.BadGzipFile, SafeUnpackError):
            tmp.unlink(missing_ok=True)
            raise
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
        "certified_shards": expected,
        "created": created,
        "reused_verified": reused,
        "quarantined_stale_outputs": stale_outputs,
        "new_uncompressed_bytes": written_bytes,
        "compressed_safe_retained": True,
        "unpacked_directory": str(outroot),
    }
    _json_atomic(destination / "UNPACK_REPORT.json", result)
    return result
