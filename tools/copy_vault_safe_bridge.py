#!/usr/bin/env python3
"""Offline, fail-closed AlinaSync SAFE tick-envelope -> Copy-Vault economic view.

This is NOT a quality upgrader. Only AlinaSync-certified, intact, causally
observed records become Copy-Vault inputs. No network, trading or collectors.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.collection.userfills_live import parser_message_userfills  # noqa: E402


class SafeBridgeError(RuntimeError):
    """A SAFE corpus is absent, inconsistent or unusable for Copy-Vault."""


class StaleCopyVaultBook(SafeBridgeError):
    """A real L2 observation exists but is too old for economic replay."""


class ShallowCopyVaultBook(SafeBridgeError):
    """A real L2 observation lacks the five levels required for execution."""


def _windows_io_path(path: Path) -> Path:
    absolute = os.path.abspath(path)
    if os.name == "nt" and not absolute.startswith("\\\\?\\"):
        return Path("\\\\?\\" + absolute)
    return Path(absolute)


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SafeBridgeError(f"missing or symlinked evidence: {path}")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SafeBridgeError(f"invalid evidence: {path}") from exc
    if not isinstance(result, dict):
        raise SafeBridgeError(f"non-object evidence: {path}")
    return result


def _safe_archive(recovery: Path, relative: str) -> Path:
    parsed = PurePosixPath(relative)
    parts = parsed.parts
    if (
        len(parts) != 4
        or parts[:2] != ("usable", "shards")
        or any(part in {"", ".", ".."} or "\\" in part or ":" in part for part in parts)
        or not parts[3].endswith(".jsonl.gz")
    ):
        raise SafeBridgeError(f"unsafe SAFE registry path: {relative}")
    archive = recovery.joinpath(*parts)
    if any(path.is_symlink() for path in (recovery / "usable", archive.parent, archive)):
        raise SafeBridgeError(f"symlinked SAFE input: {relative}")
    return _windows_io_path(archive)


def _source_record(line: bytes) -> dict[str, Any]:
    try:
        record = json.loads(line)
    except (ValueError, UnicodeError) as exc:
        raise SafeBridgeError("invalid SAFE JSONL frame") from exc
    if not isinstance(record, dict):
        raise SafeBridgeError("non-object SAFE JSONL frame")
    return record


def _raw_envelope(record: dict[str, Any], channel: str) -> tuple[dict[str, Any], int, int]:
    expected_sources = {
        "copy_vault_fills": {
            "hyperliquid_public_userfills",
            "hyperliquid_info_user_fills_by_time",
            "hyperliquid_info_user_fills_by_time_history",
        },
        "copy_vault_snapshot": {
            "hyperliquid_public_userfills",
            "hyperliquid_info_user_fills_by_time_history",
            # Historical windows were published under the legacy fills family
            # before the TRAIN-only snapshot channel was introduced.
            "hyperliquid_info_user_fills_by_time",
        },
        "copy_vault_l2": {"hyperliquid_public_copy_l2"},
    }[channel]
    provenance = record.get("provenance")
    raw = record.get("raw_payload")
    if (
        record.get("schema_version") != "hypersmart.tick.v1"
        or record.get("channel") != channel
        or record.get("source_id") not in expected_sources
        or record.get("read_only") is not True
        or record.get("real_execution") is not False
        or not isinstance(provenance, dict)
        or provenance.get("access") != "read_only"
        or provenance.get("authenticated") is not False
        or not isinstance(raw, str)
        or hashlib.sha256(raw.encode("utf-8")).hexdigest() != record.get("raw_sha256")
        or type(record.get("received_ts_ms")) is not int
        or type(record.get("exchange_ts_ms")) is not int
    ):
        raise SafeBridgeError("unverifiable or non-public causal Copy-Vault envelope")
    receive = record["received_ts_ms"]
    exchange = record["exchange_ts_ms"]
    if not 0 < exchange <= receive:
        raise SafeBridgeError("Copy-Vault receive/exchange clocks are noncausal")
    try:
        message = json.loads(raw)
    except ValueError as exc:
        raise SafeBridgeError("invalid Copy-Vault raw payload") from exc
    if not isinstance(message, dict):
        raise SafeBridgeError("invalid Copy-Vault raw message")
    return message, receive, exchange


def _fills(
    record: dict[str, Any], *, channel: str = "copy_vault_fills",
) -> tuple[list[dict[str, Any]], int]:
    if channel not in {"copy_vault_fills", "copy_vault_snapshot"}:
        raise SafeBridgeError("invalid Copy-Vault fill family")
    message, receive, exchange = _raw_envelope(record, channel)
    provenance = record["provenance"]
    vault = str(record.get("instrument") or "").strip().lower()
    source_id = str(record.get("source_id") or "")
    if source_id in {
        "hyperliquid_info_user_fills_by_time",
        "hyperliquid_info_user_fills_by_time_history",
    }:
        history_flag = provenance.get("history_bootstrap")
        historical_bootstrap = (
            True if source_id.endswith("_history") else history_flag is True
        )
        expected_channels = (
            {"copy_vault_snapshot", "copy_vault_fills"}
            if historical_bootstrap else {"copy_vault_fills"}
        )
        request = message.get("request")
        raw_fills = message.get("fills")
        if (
            channel not in expected_channels
            or provenance.get("transport") != "https"
            or provenance.get("request_type") != "userFillsByTime"
            or provenance.get("window_reconciliation_complete") is not True
            or not isinstance(history_flag, bool)
            or history_flag is not historical_bootstrap
            or not isinstance(request, dict)
            or request.get("type") != "userFillsByTime"
            or str(request.get("user") or "").lower() != vault
            or not isinstance(raw_fills, list)
            or not raw_fills
        ):
            raise SafeBridgeError("REST fills lack a verified complete window")
        try:
            start_ms = int(request["startTime"])
            end_ms = int(request["endTime"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise SafeBridgeError("REST fills have invalid window bounds") from exc
        if start_ms <= 0 or end_ms < start_ms:
            raise SafeBridgeError("REST fills have invalid window bounds")
        normalized: list[dict[str, Any]] = []
        for raw_fill in raw_fills:
            if not isinstance(raw_fill, dict):
                raise SafeBridgeError("REST fill is not an object")
            fill = dict(raw_fill)
            try:
                ts_ms = int(fill["ts_ms"])
                px = float(fill["px"])
                sz = float(fill["sz"])
                signe = int(fill["signe"])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise SafeBridgeError("REST fill is missing normalized fields") from exc
            if (
                str(fill.get("vault") or "").lower() != vault
                or not start_ms <= ts_ms <= end_ms
                or ts_ms > receive
                or signe not in (-1, 1)
                or not math.isfinite(px) or px <= 0
                or not math.isfinite(sz) or sz <= 0
            ):
                raise SafeBridgeError("REST fill identity or window mismatch")
            fill.update({
                "ts_ms": ts_ms,
                "px": px,
                "sz": sz,
                "signe": signe,
                "received_at_ms": receive,
                "recv_mono_ns": record.get("local_monotonic_ns"),
                "connection_id": str(record.get("connection_id") or ""),
                "source": "REST_BACKFILL",
                "historical_bootstrap": historical_bootstrap,
                "window_reconciliation_complete": True,
                "isSnapshot": False,
            })
            normalized.append(fill)
        if max(int(fill["ts_ms"]) for fill in normalized) != exchange:
            raise SafeBridgeError("REST fill timestamp does not match envelope")
        return normalized, 0

    data = message.get("data")
    if (
        message.get("channel") != "userFills"
        or not isinstance(data, dict)
        or not vault
        or (data.get("user") and str(data["user"]).lower() != vault)
    ):
        raise SafeBridgeError("Copy-Vault fill identity or message mismatch")
    if channel == "copy_vault_snapshot":
        if (
            source_id != "hyperliquid_public_userfills"
            or data.get("isSnapshot") is not True
        ):
            raise SafeBridgeError("Copy-Vault snapshot family contains a non-snapshot event")
        return [], len(data.get("fills") or [])
    if data.get("isSnapshot") is True:
        return [], len(data.get("fills") or [])
    if data.get("isSnapshot") not in (None, False):
        raise SafeBridgeError("Copy-Vault fill snapshot flag invalid")
    # Older public userFills frames omit isSnapshot. The outer immutable
    # Alina envelope already classifies these bytes as copy_vault_fills;
    # snapshot frames use the distinct copy_vault_snapshot family.
    fills = parser_message_userfills(
        message, vault=vault, received_at_ms=receive,
        receive_mono_ns=record.get("local_monotonic_ns"),
        connection_id=str(record.get("connection_id") or ""),
    )
    if not fills or max(int(row["ts_ms"]) for row in fills) != exchange:
        raise SafeBridgeError("missing fills or mismatched exchange timestamp")
    if any(
        int(row["ts_ms"]) <= 0 or int(row["ts_ms"]) > receive
        or row.get("signe") not in (-1, 1)
        or not math.isfinite(float(row["px"])) or float(row["px"]) <= 0
        or not math.isfinite(float(row["sz"])) or float(row["sz"]) <= 0
        for row in fills
    ):
        raise SafeBridgeError("invalid or noncausal fill event")
    return fills, 0


def _levels(side: Any, *, descending: bool) -> list[list[float]]:
    if not isinstance(side, list) or len(side) < 5:
        raise ShallowCopyVaultBook("L2 has fewer than five levels")
    output: list[list[float]] = []
    previous: float | None = None
    for entry in side[:5]:
        if not isinstance(entry, dict):
            raise SafeBridgeError("invalid L2 level format")
        try:
            px, sz = float(entry["px"]), float(entry["sz"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SafeBridgeError("invalid L2 price or size") from exc
        if (
            not math.isfinite(px) or not math.isfinite(sz) or px <= 0 or sz <= 0
            or (previous is not None and ((px >= previous) if descending else (px <= previous)))
        ):
            raise SafeBridgeError("nonpositive or unordered L2")
        output.append([px, sz])
        previous = px
    return output


def _book(record: dict[str, Any]) -> dict[str, Any]:
    message, receive, exchange = _raw_envelope(record, "copy_vault_l2")
    data = message.get("data")
    if message.get("channel") != "l2Book" or not isinstance(data, dict):
        raise SafeBridgeError("invalid L2 websocket envelope")
    coin = str(record.get("instrument") or "").upper()
    if not coin or str(data.get("coin") or "").upper() != coin or data.get("time") != exchange:
        raise SafeBridgeError("L2 missing identity or exchange timestamp")
    if receive - exchange > 1_000:
        raise StaleCopyVaultBook("L2 observation exceeds one-second freshness gate")
    sides = data.get("levels")
    if not isinstance(sides, list) or len(sides) != 2:
        raise SafeBridgeError("invalid L2 book sides")
    bids, asks = _levels(sides[0], descending=True), _levels(sides[1], descending=False)
    if bids[0][0] >= asks[0][0]:
        raise SafeBridgeError("crossed L2 market")
    capacity = min(
        sum(px * size for px, size in bids),
        sum(px * size for px, size in asks),
    )
    return {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": coin,
        "bid": bids[0][0],
        "ask": asks[0][0],
        "bids5": bids,
        "asks5": asks,
        "capacity_usd": capacity,
        "received_at_ms": receive,
        "exchange_ts_ms": exchange,
        "source": "HYPERLIQUID_L2_WS",
        "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
    }


def _safe_registry_rows(
    recovery: Path, catalog_path: Path,
) -> tuple[str, list[tuple[str, int, str, tuple[int, int, int, int]]]]:
    restore = _read_json(recovery / "RESTORE_REPORT.json")
    binding = restore.get("catalog_verification")
    classification = restore.get("classification")
    catalog = binding.get("source_index_sha256") if isinstance(binding, dict) else None
    selection_families = restore.get("selection_families")
    if (
        restore.get("repository") != "Rapt0r06300/hyperliquid-smart-wallet-observer"
        or restore.get("status") != "REPLAY_READY_COMPLETE"
        or not isinstance(selection_families, list)
        or any(not isinstance(family, str) for family in selection_families)
        or not {"copy_vault_fills", "copy_vault_l2"}.issubset(selection_families)
        or set(selection_families) - {
            "copy_vault_fills", "copy_vault_l2", "copy_vault_snapshot",
        }
        or not isinstance(classification, dict)
        or classification.get("materialization_complete") is not True
        or classification.get("failures") not in (None, [])
        or not isinstance(catalog, str) or len(catalog) != 64
    ):
        raise SafeBridgeError("AlinaSync Copy-Vault SAFE restoration is not certified")
    if (
        catalog_path.is_symlink() or not catalog_path.is_file()
        or _digest(catalog_path) != catalog
    ):
        raise SafeBridgeError("active DATA_INDEX changed; synchronize AlinaSync before research")
    db_path = recovery / "SAFE_SHARDS.sqlite3"
    if db_path.is_symlink() or not db_path.is_file():
        raise SafeBridgeError("missing SAFE_SHARDS registry")
    try:
        with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            metadata = dict(db.execute(
                "SELECT key, value FROM safe_shard_registry_meta "
                "WHERE key IN ('run_status','active_catalog_sha256')"
            ))
            if metadata.get("run_status") != "COMPLETE" or metadata.get("active_catalog_sha256") != catalog:
                raise SafeBridgeError("SAFE registry does not match final catalog")
            raw = db.execute(
                "SELECT relative_path, bytes, sha256, stat_dev, stat_ino, "
                "stat_mtime_ns, stat_ctime_ns FROM current_safe_shards "
                "ORDER BY relative_path"
            ).fetchall()
    except sqlite3.Error as exc:
        raise SafeBridgeError("unreadable SAFE_SHARDS registry") from exc
    expected = classification.get("usable_shards")
    if type(expected) is not int or expected <= 0 or len(raw) != expected:
        raise SafeBridgeError("SAFE archive and registry shard counts disagree")
    return catalog, [
        (str(row[0]), int(row[1]), str(row[2]), tuple(int(v) for v in row[3:]))
        for row in raw
    ]


def build_safe_copy_workspace(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    recovery = root / "runtime" / "recovery" / "full"
    catalog, registry = _safe_registry_rows(recovery, root / "catalog" / "DATA_INDEX.json")
    parent = root / "runtime" / "research_lab" / "copy_vault_safe"
    if parent.is_symlink():
        raise SafeBridgeError("unsafe Copy-Vault workspace parent")
    parent.mkdir(parents=True, exist_ok=True)
    bridge_sha256 = _digest(Path(__file__).resolve())
    selection = hashlib.sha256()
    selection.update(catalog.encode("ascii"))
    selection.update(bridge_sha256.encode("ascii"))
    # Immutable artifact name is scoped to the certified input set; unchanged
    # inputs are reused only if the output byte digests still match.
    stage = Path(tempfile.mkdtemp(prefix=".copy-safe-", dir=parent))
    destination = stage / "runtime" / "data"
    destination.mkdir(parents=True)
    paths = {
        "copy_vault_fills": destination / "vault_fills_live.jsonl",
        "copy_vault_l2": destination / "copy_vault_l2_tape.jsonl",
        "copy_vault_snapshot": destination / "vault_fills.jsonl",
    }
    counts = {
        "copy_vault_fills": 0,
        "copy_vault_snapshot": 0,
        "historical_bootstrap_fills": 0,
        "copy_vault_l2": 0,
        "snapshots_excluded": 0,
        "stale_l2_excluded": 0,
        "shallow_l2_excluded": 0,
    }
    inputs: list[dict[str, Any]] = []
    total = len(registry)
    try:
        with paths["copy_vault_fills"].open("w", encoding="utf-8", newline="\n") as fill_out, paths["copy_vault_snapshot"].open("w", encoding="utf-8", newline="\n") as history_out, paths["copy_vault_l2"].open("w", encoding="utf-8", newline="\n") as l2_out:
            for i, (relative, size, sha, _registered_stat_identity) in enumerate(registry, 1):
                archive = _safe_archive(recovery, relative)
                if not archive.is_file():
                    raise SafeBridgeError(f"missing registered SAFE shard: {relative}")
                before_hash = archive.stat()
                if before_hash.st_size != size:
                    raise SafeBridgeError(f"registered SAFE shard was modified: size mismatch: {relative}")
                if _digest(archive) != sha:
                    raise SafeBridgeError(f"SAFE shard byte proof mismatch: {relative}")
                after_hash = archive.stat()
                if (
                    before_hash.st_dev, before_hash.st_ino, before_hash.st_size,
                    before_hash.st_mtime_ns, before_hash.st_ctime_ns,
                ) != (
                    after_hash.st_dev, after_hash.st_ino, after_hash.st_size,
                    after_hash.st_mtime_ns, after_hash.st_ctime_ns,
                ):
                    raise SafeBridgeError(f"SAFE shard changed while being verified: {relative}")
                selection.update(relative.encode("utf-8"))
                selection.update(sha.encode("ascii"))
                rows = 0
                raw_bytes = 0
                channel = None
                try:
                    stream = gzip.open(archive, "rb")
                    with stream:
                        for line in stream:
                            raw_bytes += len(line)
                            record = _source_record(line)
                            record_channel = record.get("channel")
                            if channel is None:
                                channel = record_channel
                                if channel not in paths:
                                    raise SafeBridgeError(
                                        f"non-Copy-Vault shard in scoped registry: {relative}"
                                    )
                            if record_channel != channel:
                                raise SafeBridgeError(f"mixed channel in SAFE shard: {relative}")
                            rows += 1
                            if channel in {"copy_vault_fills", "copy_vault_snapshot"}:
                                normalized, excluded = _fills(record, channel=channel)
                                counts["snapshots_excluded"] += excluded
                                for fill in normalized:
                                    historical = fill.get("historical_bootstrap") is True
                                    target = history_out if historical else fill_out
                                    target.write(json.dumps(fill, sort_keys=True, allow_nan=False) + "\n")
                                    counts[
                                        "copy_vault_snapshot" if historical else "copy_vault_fills"
                                    ] += 1
                                    counts["historical_bootstrap_fills"] += int(
                                        historical
                                    )
                            else:
                                try:
                                    book = _book(record)
                                except StaleCopyVaultBook:
                                    counts["stale_l2_excluded"] += 1
                                    continue
                                except ShallowCopyVaultBook:
                                    counts["shallow_l2_excluded"] += 1
                                    continue
                                l2_out.write(json.dumps(book, sort_keys=True, allow_nan=False) + "\n")
                                counts[channel] += 1
                except (OSError, EOFError) as exc:
                    raise SafeBridgeError(f"invalid compressed SAFE shard: {relative}") from exc
                if rows == 0 or channel is None:
                    raise SafeBridgeError(f"empty SAFE shard: {relative}")
                inputs.append({
                    "relative_path": relative, "sha256": sha,
                    "compressed_bytes": size, "jsonl_bytes": raw_bytes,
                    "channel": channel, "frames": rows,
                })
                if len(inputs) % 100 == 0 or i == total:
                    print(f"ALINA_COPY_SAFE_PROGRESS={i}/{total} selected={len(inputs)}", flush=True)
        if not (counts["copy_vault_fills"] + counts["copy_vault_snapshot"]) or not counts["copy_vault_l2"]:
            raise SafeBridgeError("SAFE corpus lacks both causal fills and subsecond L2")
        digest = selection.hexdigest()
        outputs = {name: {"path": "runtime/data/" + path.name,
                          "sha256": _digest(path), "bytes": path.stat().st_size}
                   for name, path in paths.items()}
        provenance = {
            "schema": "hypersmart.dataset_selection_provenance.v4",
            "source_kind": "alina-sync-safe-compressed",
            "source_repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "catalog_sha256": catalog,
            "bridge_sha256": bridge_sha256,
            "selection_digest": digest,
            "selected_files": len(inputs),
            "selected_raw_bytes": sum(int(row["jsonl_bytes"]) for row in inputs),
            "safe_input_shards": inputs,
            "outputs": outputs,
            "counts": counts,
            "paper_read_only": True,
            "real_execution": False,
            "snapshot_fills_excluded": True,
            "historical_bootstrap_fills_separate": True,
            "historical_bootstrap_fills": counts["historical_bootstrap_fills"],
            "forward_proof_from_historical_bootstrap": False,
            "economic_proof": False,
        }
        proof_dir = stage / "runtime" / "reports" / "datasets"
        proof_dir.mkdir(parents=True)
        (proof_dir / "SELECTION_PROVENANCE.json").write_text(
            json.dumps(provenance, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        (stage / "SAFE_INPUT_MANIFEST.json").write_text(
            json.dumps({
                "schema_version": "hypersmart.copy_vault_safe_input_manifest.v1",
                "status": "READY",
                "catalog_sha256": catalog,
                "selection_digest": digest,
                "selected_shards": len(inputs),
                "selected_raw_bytes": sum(int(row["jsonl_bytes"]) for row in inputs),
                "counts": counts,
                "paper_read_only": True,
                "real_execution": False,
            }, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        final = parent / digest[:24]
        if final.exists():
            existing = _read_json(final / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json")
            if existing != provenance or any(
                _digest(final / row["path"]) != row["sha256"]
                for row in outputs.values()
            ):
                raise SafeBridgeError("existing Copy-Vault workspace is inconsistent")
            shutil.rmtree(stage)
        else:
            os.replace(stage, final)
        return {
            "status": "SAFE_COPY_WORKSPACE_READY", "workspace": str(final),
            "catalog_sha256": catalog, "selected_shards": len(inputs),
            "selection_digest": digest,
            "selected_raw_bytes": sum(int(row["jsonl_bytes"]) for row in inputs),
            "counts": counts, "outputs": outputs, "economic_proof": False,
        }
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    try:
        result = build_safe_copy_workspace(Path(args.root))
    except (SafeBridgeError, OSError, ValueError, TypeError) as exc:
        print(f"SAFE_COPY_NO_GO: {exc}", flush=True)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
