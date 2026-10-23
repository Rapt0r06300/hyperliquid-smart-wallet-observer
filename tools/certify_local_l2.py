#!/usr/bin/env python3
"""Offline certification of downloaded SAFE L2, with lossless local re-anchoring.

Source shards and canonical dataset catalog are NEVER modified. A locally
generated secondary certificate distinguishes book snapshots from continuity.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

FAMILIES = {"l2", "l2book", "book", "copy_vault_l2", "l2book_snapshot"}
MAX_LINE = 64 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}\Z")


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class HashReader:
    """Hash compressed input during gzip CRC-verified parsing (one disk pass)."""
    def __init__(self, file):
        self.file = file
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, count=-1):
        block = self.file.read(count)
        self.digest.update(block)
        self.size += len(block)
        return block


def integer(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
        return number if str(value).strip() == str(number) and number >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def levels(value, *, snapshot):
    if value is None and not snapshot:
        return []
    if not isinstance(value, list) or (snapshot and not value):
        return None
    out = []
    for level in value:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            return None
        try:
            price, size = float(level[0]), float(level[1])
        except (ValueError, TypeError, OverflowError):
            return None
        if not math.isfinite(price) or not math.isfinite(size):
            return None
        if price <= 0 or size < 0 or (snapshot and size <= 0):
            return None
        out.append((price, size))
    return out


def native_frame(row, venue):
    raw = row.get("raw_payload")
    if not isinstance(raw, str):
        return None
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != row.get("raw_sha256"):
        return None
    try:
        message = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(message, dict):
        return None
    data = message.get("data")
    data = data[0] if isinstance(data, list) and data else data
    if not isinstance(data, dict):
        data = message.get("result")
    if not isinstance(data, dict):
        data = message
    summary = row.get("parsed_summary") or {}
    if not isinstance(summary, dict):
        summary = {}
    snap = str(row.get("event_kind") or "").upper() == "SNAPSHOT"
    if venue == "binance":
        snap = snap and "lastUpdateId" in message
        seq = integer(message.get("lastUpdateId") if snap else message.get("u"))
        prev = integer(message.get("pu")) if not snap else None
        low = integer(message.get("U")) if not snap else None
        bid = message.get("bids" if snap else "b")
        ask = message.get("asks" if snap else "a")
    elif venue == "bybit":
        snap = snap and str(message.get("type") or "").lower() == "snapshot"
        seq, prev, low = integer(data.get("u")), None, None
        bid, ask = data.get("b"), data.get("a")
    elif venue == "okx":
        snap = snap and str(message.get("action") or "").lower() == "snapshot"
        if summary.get("source_channel") == "books5":
            snap = True
        seq, prev, low = integer(data.get("seqId")), integer(data.get("prevSeqId")), None
        bid, ask = data.get("bids"), data.get("asks")
    elif venue == "bitget":
        snap = snap and str(message.get("action") or "").lower() == "snapshot"
        if summary.get("source_channel") in {"books5", "books15"}:
            snap = True
        seq = integer(data.get("seq"))
        prev = integer(data.get("pseq", data.get("prevSeqId")))
        low = None
        bid, ask = data.get("bids"), data.get("asks")
    elif venue == "gate":
        snap = snap and data.get("full") is True
        seq, prev, low = integer(data.get("u")), None, integer(data.get("U"))
        bid, ask = data.get("b", data.get("bids")), data.get("a", data.get("asks"))
    elif venue == "hyperliquid":
        book = message.get("data", message)
        snap = snap and isinstance(book, dict) and isinstance(book.get("levels"), list)
        if not snap or len(book["levels"]) != 2:
            return None
        try:
            bid = [[x["px"], x["sz"]] for x in book["levels"][0]]
            ask = [[x["px"], x["sz"]] for x in book["levels"][1]]
        except (TypeError, KeyError):
            return None
        seq, prev, low = None, None, None
    else:
        return None
    bids, asks = levels(bid, snapshot=snap), levels(ask, snapshot=snap)
    if bids is None or asks is None:
        return None
    return snap, seq, prev, low, bids, asks


def inspect_shard(path, entry):
    """Immutable SHA, full gzip/JSONL, native L2 sequences and actual anchors."""
    path = Path(path)
    venue = str(entry.get("venue") or "").lower()
    result = {"dataset_id": entry.get("dataset_id"), "venue": venue,
              "family": entry.get("family"), "source": str(path),
              "source_sha256": entry.get("sha256"), "status": "BLOCKED",
              "records": 0, "valid_records": 0, "reasons": {},
              "segments": [], "certifier": "alina.local_l2.v1"}
    reasons = result["reasons"]
    def reject(reason):
        reasons[reason] = reasons.get(reason, 0) + 1

    expected_sha = str(entry.get("sha256") or "").lower()
    expected_size = entry.get("bytes")
    if not SHA.fullmatch(expected_sha) or type(expected_size) is not int or expected_size <= 0:
        reject("CATALOG_IDENTITY_INVALID")
        return result
    if (path.is_symlink() or path.parent.is_symlink()
            or not path.is_file() or path.stat().st_size != expected_size):
        reject("SOURCE_MISSING_OR_SIZE_MISMATCH")
        return result
    if venue not in {"binance", "bybit", "okx", "bitget", "gate", "hyperliquid"}:
        reject("NO_NATIVE_VERIFIER")
        return result

    books = {}
    prior_sequence, prior_time, prior_received, prior_mono, last_connection = None, None, None, None, None
    active_start = None
    segments = []
    line_number = 0

    def close(*, include_current=False):
        nonlocal active_start
        if active_start is not None:
            end = line_number if include_current else line_number - 1
            if end >= active_start:
                segments.append({"first_line": active_start, "last_line": end,
                                 "records": end - active_start + 1})
            active_start = None

    try:
        with path.open("rb") as file:
            hashed = HashReader(file)
            with gzip.GzipFile(fileobj=hashed, mode="rb") as stream:
                for line in stream:
                    line_number += 1
                    if len(line) > MAX_LINE:
                        reject("RECORD_TOO_LARGE"); close(); books = {}; continue
                    try:
                        row = json.loads(line)
                    except (UnicodeError, ValueError):
                        reject("JSON_INVALID"); close(); books = {}; continue
                    result["records"] += 1
                    if not isinstance(row, dict) or str(row.get("venue") or venue).lower() != venue:
                        reject("ROW_VENUE_INVALID"); close(); books = {}; continue
                    stamp = integer(row.get("exchange_ts_ms"))
                    received = integer(row.get("received_ts_ms"))
                    mono = integer(row.get("local_monotonic_ns"))
                    if (stamp is None or received is None
                            or (prior_time is not None and stamp < prior_time)
                            or (prior_received is not None and received < prior_received)
                            or (mono is not None and prior_mono is not None and mono < prior_mono)):
                        reject("TIMESTAMP_INVALID_OR_REGRESSION"); close(); books = {}; continue
                    prior_time, prior_received = stamp, received
                    if mono is not None:
                        prior_mono = mono
                    channel = str(row.get("channel") or "l2Book").lower()
                    if channel not in FAMILIES or (
                            entry.get("symbol") and row.get("instrument")
                            and str(row["instrument"]).upper() != str(entry["symbol"]).upper()):
                        reject("L2_CHANNEL_OR_SYMBOL_MISMATCH"); close(); books = {}; continue
                    if integer(row.get("gap_count")) not in (0, None):
                        reject("RECORDED_SOURCE_GAP"); close(); books = {}; continue
                    summary = row.get("parsed_summary") or {}
                    if not isinstance(summary, dict):
                        summary = {}
                    if str(summary.get("book_state") or "").upper() in {
                        "DESYNC", "BUFFERING_SNAPSHOT", "UNMEASURABLE"
                    }:
                        reject("RECORDED_BOOK_UNUSABLE"); close(); books = {}; continue
                    frame = native_frame(row, venue)
                    if frame is None:
                        reject("NATIVE_FRAME_UNVERIFIABLE"); close(); books = {}; continue
                    snapshot, sequence, previous, low, bids, asks = frame
                    connection = row.get("connection_id")
                    if not snapshot and last_connection is not None and connection != last_connection:
                        reject("RECONNECT_WITHOUT_SNAPSHOT")
                        close(); books = {}; prior_sequence = None
                    last_connection = connection
                    if snapshot:
                        close()
                        books = {"bid": dict(bids), "ask": dict(asks)}
                        prior_sequence = sequence
                        active_start = line_number
                    else:
                        if not books or prior_sequence is None or sequence is None:
                            reject("DELTA_WITHOUT_PROVEN_ANCHOR")
                            close(); books = {}; continue
                        if sequence <= prior_sequence:
                            reject("SEQUENCE_DUPLICATE_OR_REGRESSION")
                            close(); books = {}; continue
                        if venue in {"binance", "gate"}:
                            if (low is None or low > prior_sequence + 1
                                    or sequence < prior_sequence + 1
                                    or (venue == "binance" and previous is not None
                                        and previous != prior_sequence)):
                                reject("SEQUENCE_GAP")
                                close(); books = {}; continue
                        elif venue in {"okx", "bitget"}:
                            if previous is None or previous != prior_sequence:
                                reject("SEQUENCE_GAP_OR_MISSING_PREVIOUS")
                                close(); books = {}; continue
                        elif venue == "bybit" and sequence != prior_sequence + 1:
                            reject("SEQUENCE_GAP")
                            close(); books = {}; continue
                        for side, changes in (("bid", bids), ("ask", asks)):
                            for price, quantity in changes:
                                if quantity == 0:
                                    books[side].pop(price, None)
                                else:
                                    books[side][price] = quantity
                        prior_sequence = sequence
                    if not books["bid"] or not books["ask"] or max(books["bid"]) >= min(books["ask"]):
                        reject("BOOK_EMPTY_OR_CROSSED")
                        close(); books = {}; continue
                    result["valid_records"] += 1
            if hashed.size != expected_size or hashed.digest.hexdigest() != expected_sha:
                reject("COMPRESSED_SHA256_MISMATCH")
                result["valid_records"] = 0
                return result
    except (OSError, EOFError, ValueError, gzip.BadGzipFile):
        reject("GZIP_TRUNCATED_OR_UNREADABLE")
        result["valid_records"] = 0
        return result
    close(include_current=True)
    result["segments"] = segments
    if not segments:
        result["status"] = "BLOCKED"
    elif venue == "hyperliquid" or len(segments) == result["valid_records"]:
        result["status"] = "SNAPSHOT_OBSERVATIONS_ONLY"
    elif (not reasons and len(segments) == 1
          and segments[0]["records"] == result["records"]):
        result["status"] = "CONTINUOUS_L2"
    else:
        result["status"] = "RECOVERABLE_ANCHORED_SPANS"
    return result


def atomic_json(path, value):
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("UNSAFE_REPORT_PATH")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".l2-report-", suffix=".tmp",
                                     delete=False) as output:
        tmp = Path(output.name)
        json.dump(value, output, indent=2, sort_keys=True, ensure_ascii=False)
        output.write("\n")
    os.replace(tmp, path)


def salvage(source, folder, record):
    """Immutable selected lines -> separate gzip and independently hashed proof."""
    if record["status"] != "RECOVERABLE_ANCHORED_SPANS":
        return None
    dataset_id = str(record["dataset_id"] or "")
    if not dataset_id:
        raise ValueError("UNSAFE_REPAIR_ID")
    identity = hashlib.sha256(dataset_id.encode("utf-8")).hexdigest()[:24]
    segments = record["segments"]
    fragment = hashlib.sha256(json.dumps(segments, sort_keys=True).encode()).hexdigest()[:12]
    target = folder / (identity + "." + record["source_sha256"][:16] +
                       "." + fragment + ".reanchored.jsonl.gz")
    proofpath = target.with_suffix(target.suffix + ".proof.json")
    folder.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or proofpath.is_symlink():
        raise ValueError("UNSAFE_REPAIR_SYMLINK")
    if target.exists() or proofpath.exists():
        if not target.is_file() or not proofpath.is_file():
            raise ValueError("UNSEALED_PREVIOUS_REPAIR")
        proof = json.loads(proofpath.read_text(encoding="utf-8"))
        if (proof.get("source_sha256") != record["source_sha256"]
                or proof.get("segments") != segments
                or proof.get("sha256") != digest_file(target)):
            raise ValueError("EXISTING_REPAIR_DIGEST_MISMATCH")
        return proof
    if digest_file(source) != record["source_sha256"]:
        raise ValueError("SOURCE_CHANGED_DURING_REPAIR")
    fd, tempname = tempfile.mkstemp(dir=folder, prefix=".l2-copy-", suffix=".tmp")
    os.close(fd)
    temp = Path(tempname)
    try:
        with gzip.open(source, "rb") as inp, temp.open("wb") as dest:
            with gzip.GzipFile(fileobj=dest, mode="wb", filename="", mtime=0) as gzout:
                segment_index = 0
                for i, line in enumerate(inp, 1):
                    while segment_index < len(segments) and i > segments[segment_index]["last_line"]:
                        segment_index += 1
                    if segment_index >= len(segments):
                        break
                    if i >= segments[segment_index]["first_line"]:
                        gzout.write(line)
        output_sha = digest_file(temp)
        temp.replace(target)
        proof = {"source_sha256": record["source_sha256"], "sha256": output_sha,
                 "path": str(target), "segments": segments,
                 "warning": "NOT_CROSS_SHARD_CONTINUITY_CERTIFIED"}
        atomic_json(proofpath, proof)
        return proof
    finally:
        temp.unlink(missing_ok=True)


def run(root, destination, *, workers=4, limit=0, repair=False, resume=False):
    """Verify canonical partitioned index before examining local SAFE objects."""
    root, destination = Path(root).resolve(), Path(destination).resolve()
    try:
        from tools.partitioned_data_index import read_index
        from tools.restore_alina import _safe_component
    except ModuleNotFoundError:
        from partitioned_data_index import read_index
        from restore_alina import _safe_component
    catalog = root / "catalog" / "DATA_INDEX.json"
    index = read_index(catalog)
    selected = []
    for row in index["shards"]:
        if (isinstance(row, dict) and row.get("quality_status") == "SAFE"
                and row.get("replay_compatible") is True
                and row.get("asset_verified") is not False
                and row.get("validation_allowed") is not False
                and str(row.get("family") or "").lower() in FAMILIES):
            path = (destination / "usable" / "shards" / _safe_component(row["release_tag"])
                    / (_safe_component(row["dataset_id"]) + ".jsonl.gz"))
            selected.append((path, row))
    if limit:
        selected = selected[:limit]
    if not selected:
        raise ValueError("NO_SAFE_L2_IN_CANONICAL_INDEX")
    # Before any work, retire a previous green run so interrupted runs fail closed.
    report_path = destination / "LOCAL_L2_CERTIFICATION.json"
    atomic_json(report_path, {
        "schema": "alina.local_l2_certification.v1",
        "status": "IN_PROGRESS_NOT_CERTIFIED", "selected_count": len(selected),
        "paper_only": True,
    })
    receipt_dir = destination / "LOCAL_L2_RECEIPTS"
    if receipt_dir.is_symlink():
        raise ValueError("UNSAFE_L2_RECEIPT_DIRECTORY")

    def inspect_with_receipt(path, row):
        ident = hashlib.sha256(
            (str(row["dataset_id"]) + "|" + str(row["sha256"])).encode("utf-8")
        ).hexdigest()
        receipt = receipt_dir / (ident + ".json")
        if path.is_file() and not path.is_symlink():
            stat = path.stat()
            if resume and receipt.is_file() and not receipt.is_symlink():
                try:
                    cached = json.loads(receipt.read_text(encoding="utf-8"))
                    if (cached.get("size") == stat.st_size
                            and cached.get("mtime_ns") == stat.st_mtime_ns
                            and cached.get("source_path") == str(path)
                            and cached.get("source_sha256") == row["sha256"]):
                        value = cached["result"]
                        if isinstance(value, dict):
                            return {**value, "stat_cache_reused_without_new_hash": True}
                except (OSError, ValueError, KeyError, TypeError):
                    pass
        value = inspect_shard(path, row)
        if path.is_file() and not path.is_symlink():
            # Receipt is an optimization hint, not an independent byte proof.
            # Only the optional --resume trusts unchanged file size+mtime.
            stat = path.stat()
            atomic_json(receipt, {
                "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                "source_path": str(path), "source_sha256": row["sha256"],
                "result": value,
            })
        return value

    print(f"ALINA_L2_SCAN shards={len(selected)} workers={workers} resume={resume}", flush=True)
    outputs = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 16))) as pool:
        futures = {pool.submit(inspect_with_receipt, path, row): path for path, row in selected}
        for index, future in enumerate(as_completed(futures), 1):
            item = future.result()
            if repair and item["status"] == "RECOVERABLE_ANCHORED_SPANS":
                try:
                    item["repair"] = salvage(
                        futures[future], destination / "usable" / "local_l2_repaired", item
                    )
                except (OSError, ValueError) as exc:
                    item["repair_error"] = str(exc)
            outputs.append(item)
            if index % 200 == 0 or index == len(futures):
                print(f"ALINA_L2_PROGRESS {index}/{len(futures)}", flush=True)
    outputs.sort(key=lambda x: str(x["dataset_id"]))
    totals = dict(Counter(x["status"] for x in outputs))
    repair_failures = sum("repair_error" in x for x in outputs)
    report = {
        "schema": "alina.local_l2_certification.v1",
        "catalog_sha256": digest_file(catalog),
        "status": "LOCAL_L2_AUDIT_COMPLETE_NOT_GLOBAL_REPLAY_CERTIFICATION",
        "totals": totals, "repair_failures": repair_failures,
        "cache_reused_without_new_hash": sum(x.get("stat_cache_reused_without_new_hash", False) for x in outputs),
        "l2_rows": outputs, "paper_only": True,
        "read_only_sources": True,
        "warning": "SAFE and SHA-256 are not proof of L2 continuity. "
                   "Recovered segments require native re-anchors; separate "
                   "cross-shard and economic validation remains mandatory.",
    }
    atomic_json(destination / "LOCAL_L2_CERTIFICATION.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    parser.add_argument("--limit", type=int, default=0, help="optional smoke-test cap")
    parser.add_argument("--repair", action="store_true", help="create separate proven spans")
    parser.add_argument("--resume", action="store_true", help="trust previous SHA-verified receipts only if source size+mtime unchanged; not a fresh byte validation")
    args = parser.parse_args(argv)
    if args.limit < 0 or args.workers <= 0 or args.workers > 16:
        parser.error("--limit must be >=0 and --workers must be 1..16")
    root = args.root.resolve()
    destination = args.destination or root / "runtime" / "recovery" / "full"
    try:
        report = run(root, destination, workers=args.workers, limit=args.limit,
                     repair=args.repair, resume=args.resume)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ALINA_L2_FAIL: {exc}", file=sys.stderr)
        return 2
    print("ALINA_L2_RESULT " + json.dumps(report["totals"], sort_keys=True))
    print("ALINA_L2_REPORT " + str(destination / "LOCAL_L2_CERTIFICATION.json"))
    return 0 if not report["totals"].get("BLOCKED") and not report["repair_failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
