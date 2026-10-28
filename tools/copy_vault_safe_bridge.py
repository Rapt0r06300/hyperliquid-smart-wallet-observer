#!/usr/bin/env python3
"""Offline, fail-closed AlinaSync SAFE tick-envelope -> Copy-Vault economic view.

This is NOT a quality upgrader. Only AlinaSync-certified, intact, causally
observed records become Copy-Vault inputs. No network, trading or collectors.
"""
from __future__ import annotations

import argparse
from collections import Counter
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

from hl_observer.backtesting.copy_vault_book_loader import MAX_TARGET_LAG_MS  # noqa: E402
from hl_observer.collection.userfills_live import parser_message_userfills  # noqa: E402
from hl_observer.normalization.instrument_identity import (  # noqa: E402
    preserve_native_instrument_symbol as canonical_copy_vault_coin,
)


class SafeBridgeError(RuntimeError):
    """A SAFE corpus is absent, inconsistent or unusable for Copy-Vault."""


def _windows_io_path(path: Path) -> Path:
    """Reuse the restore layer's extended-path handling for immutable shard names."""
    try:
        from tools.restore_alina import _windows_io_path as normalize
    except ModuleNotFoundError:
        from restore_alina import _windows_io_path as normalize
    return normalize(Path(path))


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


def _safe_paths(recovery: Path, relative: str) -> tuple[Path, Path, Path]:
    parsed = PurePosixPath(relative)
    parts = parsed.parts
    if (
        len(parts) != 4
        or parts[:2] != ("usable", "shards")
        or any(part in {"", ".", ".."} or "\\" in part or ":" in part for part in parts)
        or not parts[3].endswith(".jsonl.gz")
    ):
        raise SafeBridgeError(f"unsafe SAFE registry path: {relative}")
    archive = _windows_io_path(recovery.joinpath(*parts))
    extracted = _windows_io_path(
        recovery / "usable" / "unpacked" / parts[2] / parts[3][:-3]
    )
    seal = _windows_io_path(extracted.with_suffix(".jsonl.alina.json"))
    if any(path.is_symlink() for path in (
        _windows_io_path(recovery / "usable"), archive.parent, archive,
        _windows_io_path(recovery / "usable" / "unpacked"),
        extracted.parent, extracted, seal,
    )):
        raise SafeBridgeError(f"symlinked SAFE input: {relative}")
    return archive, extracted, seal


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
        "copy_vault_fills": {"hyperliquid_public_userfills"},
        "copy_vault_snapshot": {
            "hyperliquid_public_userfills",
            "hyperliquid_public_userfills_backfill",
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


def _fills(record: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    message, receive, exchange = _raw_envelope(record, "copy_vault_fills")
    data = message.get("data")
    vault = str(record.get("instrument") or "").strip().lower()
    if (
        message.get("channel") != "userFills"
        or not isinstance(data, dict)
        or not vault
        or (data.get("user") and str(data["user"]).lower() != vault)
    ):
        raise SafeBridgeError("Copy-Vault fill identity or message mismatch")
    if data.get("isSnapshot") is True:
        return [], len(data.get("fills") or [])
    if data.get("isSnapshot") is not False:
        raise SafeBridgeError("Copy-Vault fill snapshot flag missing")
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


def _historical_fills(record: dict[str, Any]) -> list[dict[str, Any]]:
    message, receive, exchange = _raw_envelope(record, "copy_vault_snapshot")
    data = message.get("data")
    vault = str(record.get("instrument") or "").strip().lower()
    provenance = record.get("provenance")
    if (
        message.get("channel") != "userFills"
        or not isinstance(data, dict)
        or data.get("isSnapshot") is not True
        or not vault
        or str(data.get("user") or "").lower() != vault
        or not isinstance(data.get("fills"), list)
        or not isinstance(provenance, dict)
    ):
        raise SafeBridgeError("invalid historical Copy-Vault snapshot envelope")
    source_id = str(record.get("source_id") or "")
    if source_id == "hyperliquid_public_userfills_backfill" and (
        provenance.get("historical_only") is not True
        or provenance.get("forward_evidence_allowed") is not False
        or provenance.get("transport") != "https"
    ):
        raise SafeBridgeError("REST fills lack historical-only provenance")
    normalized = parser_message_userfills(
        message,
        vault=vault,
        received_at_ms=receive,
        receive_mono_ns=record.get("local_monotonic_ns"),
        connection_id=str(record.get("connection_id") or ""),
    )
    raw_fills = data["fills"]
    if len(normalized) != len(raw_fills):
        raise SafeBridgeError("historical snapshot contains invalid or incomplete fills")
    if normalized and max(int(row["ts_ms"]) for row in normalized) != exchange:
        raise SafeBridgeError("historical snapshot exchange timestamp mismatch")
    if any(
        int(row["ts_ms"]) <= 0 or int(row["ts_ms"]) > receive
        or row.get("signe") not in (-1, 1)
        or not math.isfinite(float(row["px"])) or float(row["px"]) <= 0
        or not math.isfinite(float(row["sz"])) or float(row["sz"]) <= 0
        for row in normalized
    ):
        raise SafeBridgeError("invalid or noncausal historical fill")
    source = (
        "REST_BACKFILL"
        if source_id == "hyperliquid_public_userfills_backfill"
        else "WS_BOOTSTRAP"
    )
    return [
        {
            **row,
            "source": source,
            "isSnapshot": True,
            "is_snapshot": True,
            "observed_at_ms": None,
            "received_at_ms": receive,
            "source_id": source_id,
            "source_raw_sha256": record.get("raw_sha256"),
            "causal_forward_eligible": False,
        }
        for row in normalized
    ]


def _levels(side: Any, *, descending: bool) -> list[list[float]]:
    if not isinstance(side, list) or not side:
        raise SafeBridgeError("L2 side has no observed levels")
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
    coin = canonical_copy_vault_coin(record.get("instrument"))
    if (
        not coin or canonical_copy_vault_coin(data.get("coin")) != coin
        or data.get("time") != exchange
        or receive - exchange > MAX_TARGET_LAG_MS
    ):
        raise SafeBridgeError(
            "L2 missing identity, exchange timestamp or replay freshness"
        )
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
    connection_id = record.get("connection_id")
    if connection_id is not None and (
        not isinstance(connection_id, str) or not connection_id.strip()
    ):
        raise SafeBridgeError("invalid L2 connection identity")
    parsed_summary = record.get("parsed_summary")
    gap_epoch = (
        parsed_summary.get("l2_gap_epoch")
        if isinstance(parsed_summary, dict)
        else None
    )
    if gap_epoch is not None and (type(gap_epoch) is not int or gap_epoch < 0):
        raise SafeBridgeError("invalid L2 gap epoch")
    result = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": coin,
        "bid": bids[0][0],
        "ask": asks[0][0],
        "bids5": bids,
        "asks5": asks,
        "source_bid_levels": len(sides[0]),
        "source_ask_levels": len(sides[1]),
        "capacity_usd": capacity,
        "received_at_ms": receive,
        "exchange_ts_ms": exchange,
        "source": "HYPERLIQUID_L2_WS",
        "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
    }
    if connection_id is not None:
        result["connection_id"] = connection_id
    if gap_epoch is not None:
        result["l2_gap_epoch"] = gap_epoch
    return result


def _safe_registry_rows(
    recovery: Path, catalog_path: Path,
) -> tuple[str, list[tuple[str, int, str, tuple[int, int, int, int]]]]:
    restore = _read_json(recovery / "RESTORE_REPORT.json")
    unpack = _read_json(recovery / "UNPACK_REPORT.json")
    binding = restore.get("catalog_verification")
    classification = restore.get("classification")
    catalog = binding.get("source_index_sha256") if isinstance(binding, dict) else None
    if (
        restore.get("repository") != "Rapt0r06300/hyperliquid-smart-wallet-observer"
        or restore.get("status") != "REPLAY_READY_COMPLETE"
        or not isinstance(classification, dict)
        or classification.get("materialization_complete") is not True
        or classification.get("failures") not in (None, [])
        or unpack.get("status") != "SAFE_UNPACK_COMPLETE"
        or unpack.get("catalog_index_sha256") != catalog
        or not isinstance(catalog, str) or len(catalog) != 64
    ):
        raise SafeBridgeError("AlinaSync SAFE restoration and extraction are not certified")
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
    if (type(expected) is not int or expected <= 0 or len(raw) != expected
            or unpack.get("certified_shards") != expected):
        raise SafeBridgeError("SAFE archive, extraction and registry shard counts disagree")
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
    bridge_schema = "hypersmart.dataset_selection_provenance.v4"
    selection = hashlib.sha256()
    selection.update(bridge_schema.encode("ascii") + b"\0" + catalog.encode("ascii"))
    # A schema change gets a new immutable artifact directory instead of
    # conflicting with a prior result built from the same SAFE inputs.
    stage = Path(tempfile.mkdtemp(prefix=".copy-safe-", dir=parent))
    destination = stage / "runtime" / "data"
    destination.mkdir(parents=True)
    proof_dir = stage / "runtime" / "reports" / "datasets"
    proof_dir.mkdir(parents=True)
    decisions_path = proof_dir / "SAFE_INPUT_DECISIONS.jsonl"
    paths = {
        "copy_vault_fills": destination / "vault_fills_live.jsonl",
        "copy_vault_snapshot": destination / "vault_fills.jsonl",
        "copy_vault_l2": destination / "copy_vault_l2_tape.jsonl",
    }
    counts = {
        "copy_vault_fills": 0,
        "copy_vault_snapshot": 0,
        "historical_fill_observations": 0,
        "copy_vault_l2": 0,
        "snapshots_excluded_from_forward": 0,
    }
    inputs: list[dict[str, Any]] = []
    decision_reasons: Counter[str] = Counter()
    decision_totals = {"rows": 0, "quarantined": 0, "scope_excluded": 0}
    total = len(registry)
    processed_shards = 0
    try:
        with (
            paths["copy_vault_fills"].open("w", encoding="utf-8", newline="\n") as fill_out,
            paths["copy_vault_snapshot"].open("w", encoding="utf-8", newline="\n") as history_out,
            paths["copy_vault_l2"].open("w", encoding="utf-8", newline="\n") as l2_out,
            decisions_path.open("w", encoding="utf-8", newline="\n") as decisions_out,
        ):
            def record_decision(
                *, decision: str, reason_code: str, reason: str,
                relative: str, archive_sha: str, jsonl_sha: str,
                line_number: int, line: bytes,
            ) -> None:
                decisions_out.write(json.dumps({
                    "schema": "hypersmart.copy_vault_safe_input_decision.v1",
                    "decision": decision,
                    "reason_code": reason_code,
                    "reason": reason,
                    "source_relative_path": relative,
                    "source_archive_sha256": archive_sha,
                    "source_jsonl_sha256": jsonl_sha,
                    "line_number": line_number,
                    "frame_sha256": hashlib.sha256(line).hexdigest(),
                    "frame_bytes": len(line),
                }, sort_keys=True, allow_nan=False) + "\n")
                decision_totals["rows"] += 1
                decision_totals[
                    "quarantined" if decision == "QUARANTINE" else "scope_excluded"
                ] += 1
                decision_reasons[reason_code] += 1

            for i, (relative, size, sha, stat_identity) in enumerate(registry, 1):
                processed_shards = i
                archive, plain, seal_path = _safe_paths(recovery, relative)
                if not archive.is_file() or not plain.is_file() or not seal_path.is_file():
                    raise SafeBridgeError(f"missing registered SAFE shard: {relative}")
                stat = archive.stat()
                if (
                    (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns) != stat_identity
                    or stat.st_size != size
                ):
                    raise SafeBridgeError(f"registered SAFE shard was modified: {relative}")
                with plain.open("rb") as handle:
                    first = handle.readline()
                if not first:
                    raise SafeBridgeError(f"empty SAFE shard: {relative}")
                peek = _source_record(first)
                channel = peek.get("channel")
                seal = _read_json(seal_path)
                if (
                    seal.get("schema") != "alina.safe_jsonl_proof.v1"
                    or seal.get("compressed_sha256") != sha
                    or _digest(archive) != sha
                    or seal.get("jsonl_sha256") != _digest(plain)
                    or seal.get("jsonl_bytes") != plain.stat().st_size
                ):
                    raise SafeBridgeError(f"SAFE shard byte proof mismatch: {relative}")
                for identity in (relative, sha, str(seal["jsonl_sha256"])):
                    selection.update(identity.encode("utf-8") + b"\0")
                rows = admitted_frames = quarantined_frames = 0
                scope_excluded_frames = admitted_raw_bytes = 0
                with plain.open("rb") as stream:
                    for line_number, line in enumerate(stream, 1):
                        rows += 1
                        record = _source_record(line)
                        record_channel = record.get("channel")
                        if record_channel != channel:
                            raise SafeBridgeError(f"mixed channel in SAFE shard: {relative}")
                        if record_channel not in paths:
                            record_decision(
                                decision="SCOPE_EXCLUDED",
                                reason_code="CHANNEL_NOT_CONSUMED_BY_ECONOMIC_BRIDGE",
                                reason=f"channel {record_channel!r} is outside this bridge's input contract",
                                relative=relative, archive_sha=sha,
                                jsonl_sha=str(seal["jsonl_sha256"]),
                                line_number=line_number, line=line,
                            )
                            scope_excluded_frames += 1
                            continue
                        if record_channel == "copy_vault_fills":
                            try:
                                normalized, excluded = _fills(record)
                            except SafeBridgeError as exc:
                                record_decision(
                                    decision="QUARANTINE",
                                    reason_code="FILL_REPLAY_CONTRACT_REJECTED",
                                    reason=str(exc),
                                    relative=relative, archive_sha=sha,
                                    jsonl_sha=str(seal["jsonl_sha256"]),
                                    line_number=line_number, line=line,
                                )
                                quarantined_frames += 1
                                continue
                            counts["snapshots_excluded_from_forward"] += excluded
                            for fill in normalized:
                                fill_out.write(json.dumps(fill, sort_keys=True, allow_nan=False) + "\n")
                            counts[record_channel] += len(normalized)
                        elif record_channel == "copy_vault_snapshot":
                            try:
                                normalized = _historical_fills(record)
                            except SafeBridgeError as exc:
                                record_decision(
                                    decision="QUARANTINE",
                                    reason_code="SNAPSHOT_REPLAY_CONTRACT_REJECTED",
                                    reason=str(exc),
                                    relative=relative, archive_sha=sha,
                                    jsonl_sha=str(seal["jsonl_sha256"]),
                                    line_number=line_number, line=line,
                                )
                                quarantined_frames += 1
                                continue
                            for fill in normalized:
                                history_out.write(json.dumps(fill, sort_keys=True, allow_nan=False) + "\n")
                            counts[record_channel] += 1
                            counts["historical_fill_observations"] += len(normalized)
                        else:
                            try:
                                book = _book(record)
                            except SafeBridgeError as exc:
                                record_decision(
                                    decision="QUARANTINE",
                                    reason_code="L2_REPLAY_CONTRACT_REJECTED",
                                    reason=str(exc),
                                    relative=relative, archive_sha=sha,
                                    jsonl_sha=str(seal["jsonl_sha256"]),
                                    line_number=line_number, line=line,
                                )
                                quarantined_frames += 1
                                continue
                            l2_out.write(json.dumps(book, sort_keys=True, allow_nan=False) + "\n")
                            counts[record_channel] += 1
                        admitted_frames += 1
                        admitted_raw_bytes += len(line)
                inputs.append({
                    "relative_path": relative, "sha256": sha,
                    "jsonl_sha256": seal["jsonl_sha256"], "jsonl_bytes": seal["jsonl_bytes"],
                    "channel": channel, "frames": rows,
                    "admitted_frames": admitted_frames,
                    "quarantined_frames": quarantined_frames,
                    "scope_excluded_frames": scope_excluded_frames,
                    "admitted_jsonl_bytes": admitted_raw_bytes,
                })
                if i % 100 == 0 or i == total:
                    print(
                        f"ALINA_COPY_SAFE_PROGRESS={i}/{total} "
                        f"admitted_shards={sum(bool(row['admitted_frames']) for row in inputs)} "
                        f"quarantined={decision_totals['quarantined']} "
                        f"scope_excluded={decision_totals['scope_excluded']}",
                        flush=True,
                    )
        if not counts["copy_vault_fills"] or not counts["copy_vault_l2"]:
            missing = []
            if not counts["copy_vault_fills"]:
                missing.append("no causal live fills")
            if not counts["copy_vault_l2"]:
                missing.append("no replay-admissible L2")
            raise SafeBridgeError(
                "; ".join(missing)
                + f" (fills={counts['copy_vault_fills']}, L2={counts['copy_vault_l2']}, "
                + f"quarantined={decision_totals['quarantined']}, "
                + f"scope_excluded={decision_totals['scope_excluded']})"
            )
        digest = selection.hexdigest()
        outputs = {
            name: {"path": "runtime/data/" + path.name,
                   "sha256": _digest(path), "bytes": path.stat().st_size}
            for name, path in paths.items()
        }
        decisions = {
            "path": "runtime/reports/datasets/SAFE_INPUT_DECISIONS.jsonl",
            "sha256": _digest(decisions_path),
            "bytes": decisions_path.stat().st_size,
            "rows": decision_totals["rows"],
            "quarantined": decision_totals["quarantined"],
            "scope_excluded": decision_totals["scope_excluded"],
            "reasons": dict(sorted(decision_reasons.items())),
        }
        admitted_inputs = [row for row in inputs if row["admitted_frames"]]
        provenance = {
            "schema": bridge_schema,
            "source_kind": "alina-sync-safe-unpacked",
            "source_repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "catalog_sha256": catalog,
            "selection_digest": digest,
            "selected_files": len(admitted_inputs),
            "verified_safe_input_shards": len(inputs),
            "selected_raw_bytes": sum(row["admitted_jsonl_bytes"] for row in admitted_inputs),
            "verified_unpacked_bytes": sum(int(row["jsonl_bytes"]) for row in inputs),
            "safe_input_shards": inputs,
            "input_decisions": decisions,
            "outputs": outputs,
            "counts": counts,
            "paper_read_only": True,
            "real_execution": False,
            "snapshot_fills_train_only": True,
            "snapshot_fills_excluded_from_forward": True,
            "economic_proof": False,
        }
        provenance_path = proof_dir / "SELECTION_PROVENANCE.json"
        provenance_path.write_text(
            json.dumps(provenance, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        final = parent / digest[:24]
        if final.exists():
            existing = _read_json(final / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json")
            decision_output = final / decisions["path"]
            if (
                existing != provenance
                or any(_digest(final / row["path"]) != row["sha256"] for row in outputs.values())
                or _digest(decision_output) != decisions["sha256"]
            ):
                raise SafeBridgeError("existing Copy-Vault workspace is inconsistent")
            shutil.rmtree(stage)
        else:
            os.replace(stage, final)
        return {
            "status": "SAFE_COPY_WORKSPACE_READY", "workspace": str(final),
            "catalog_sha256": catalog, "selected_shards": len(admitted_inputs),
            "counts": counts, "outputs": outputs, "input_decisions": decisions,
            "economic_proof": False,
        }
    except Exception as exc:
        diagnostic_path = None
        try:
            diagnostic_root = parent / "diagnostics"
            diagnostic_root.mkdir(parents=True, exist_ok=True)
            diagnostic_dir = Path(tempfile.mkdtemp(prefix="no-go-", dir=diagnostic_root))
            ledger_copy = diagnostic_dir / "SAFE_INPUT_DECISIONS.jsonl"
            if decisions_path.is_file():
                shutil.copy2(decisions_path, ledger_copy)
                decision_artifact = {
                    "path": ledger_copy.name,
                    "sha256": _digest(ledger_copy),
                    "bytes": ledger_copy.stat().st_size,
                    "rows": decision_totals["rows"],
                    "quarantined": decision_totals["quarantined"],
                    "scope_excluded": decision_totals["scope_excluded"],
                    "reasons": dict(sorted(decision_reasons.items())),
                }
            else:
                decision_artifact = {
                    "path": None, "sha256": None, "bytes": 0,
                    "rows": 0, "quarantined": 0, "scope_excluded": 0,
                    "reasons": {},
                }
            diagnostic = {
                "schema": "hypersmart.copy_vault_safe_no_go.v1",
                "status": "SAFE_COPY_NO_GO",
                "catalog_sha256": catalog,
                "processed_shards": processed_shards,
                "total_shards": total,
                "verified_safe_input_shards": len(inputs),
                "counts": counts,
                "input_decisions": decision_artifact,
                "error": str(exc),
                "paper_read_only": True,
                "real_execution": False,
                "economic_proof": False,
            }
            temporary = diagnostic_dir / "NO_GO.json.partial"
            diagnostic_path = diagnostic_dir / "NO_GO.json"
            temporary.write_text(
                json.dumps(diagnostic, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(diagnostic_path)
        except OSError:
            diagnostic_path = None
        if stage.exists():
            shutil.rmtree(stage)
        if diagnostic_path is not None:
            raise SafeBridgeError(
                f"{exc}; diagnostic={diagnostic_path}"
            ) from exc
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
