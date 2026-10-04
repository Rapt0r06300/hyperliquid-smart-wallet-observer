#!/usr/bin/env python3
"""Backfill exact trade counts from immutable GitHub Release assets.

This tool never estimates from bytes. It verifies the indexed asset size and SHA-256,
then scans gzip JSONL TickEnvelope records. Counts are persisted in a separate patch
catalog so future reconciliation can re-apply them without mutating historical release
manifests.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Mapping
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "catalog" / "DATA_INDEX.json"
PATCH_PATH = ROOT / "catalog" / "TRADE_COUNT_PATCH.json"
TRADE_FAMILIES = {
    "trades",
    "agg_trades",
    "fills",
    "userfills",
    "user_fills",
    "copy_vault_fills",
}


class BackfillError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _summary_trade_count(record: Mapping[str, Any]) -> int | None:
    parsed = record.get("parsed_summary")
    if isinstance(parsed, Mapping):
        for key in ("event_count", "fill_count"):
            value = parsed.get(key)
            if value is not None and not isinstance(value, bool):
                try:
                    return max(0, int(value))
                except (TypeError, ValueError, OverflowError):
                    pass
    return None


def _trade_increment(record: Mapping[str, Any]) -> int:
    return _summary_trade_count(record) or 1


def _raw_payload(record: Mapping[str, Any]) -> Any:
    raw = record.get("raw_payload")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw


def _native_trade_keys(
    record: Mapping[str, Any],
    *,
    venue: str,
    family: str,
    symbol: str,
) -> list[str] | None:
    """Return collision-resistant identities for every trade represented by one record.

    Native exchange identifiers are preferred.  Historical normalizers are not
    required to preserve the original websocket envelope, so direct mappings,
    list payloads and normalized TickEnvelope fields are also supported.  A
    deterministic composite is used only when time, price and size are present;
    otherwise the count remains fail-closed.
    """
    raw = _raw_payload(record)
    venue = venue.lower()
    family = family.lower()
    keys: list[str] = []

    def add(prefix: str, value: Any) -> None:
        if value is not None and str(value) != "":
            keys.append(f"{venue}|{family}|{symbol}|{prefix}|{value}")

    def rows_from(value: Any) -> list[Mapping[str, Any]]:
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)]
        if not isinstance(value, Mapping):
            return []

        # User-specific feeds may wrap identity-bearing events one level deeper.
        # Hyperliquid userFills is the important case: data is an envelope and
        # the actual fills live under data.fills.
        for nested_key in ("fills", "trades", "result"):
            nested = value.get(nested_key)
            if isinstance(nested, list):
                return [row for row in nested if isinstance(row, Mapping)]
            if isinstance(nested, Mapping):
                return [nested]

        data = value.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, Mapping)]
        if isinstance(data, Mapping):
            for nested_key in ("fills", "trades"):
                nested = data.get(nested_key)
                if isinstance(nested, list):
                    return [row for row in nested if isinstance(row, Mapping)]
            return [data]
        return [value]

    def composite(
        row: Mapping[str, Any],
        *,
        time_keys: tuple[str, ...],
        price_keys: tuple[str, ...],
        size_keys: tuple[str, ...],
        side_keys: tuple[str, ...],
        extra_keys: tuple[str, ...] = (),
    ) -> str | None:
        def first(names: tuple[str, ...]) -> Any:
            for name in names:
                value = row.get(name)
                if value is not None and str(value) != "":
                    return value
            return None

        timestamp = first(time_keys)
        price = first(price_keys)
        size = first(size_keys)
        if timestamp is None or price is None or size is None:
            return None
        values = [
            timestamp,
            price,
            size,
            first(side_keys),
            first(("symbol", "s", "coin", "instId")) or symbol,
        ]
        values.extend(row.get(name) for name in extra_keys)
        return "|".join("" if value is None else str(value) for value in values)

    # If a historical normalizer omitted raw_payload, its normalized envelope is
    # still immutable evidence and may contain the native id/composite fields.
    source: Any = raw if raw is not None else record
    rows = rows_from(source)

    if venue == "binance":
        for row in rows:
            # Binance official USD-M archives are sourced from aggTrades even
            # when the normalized Dataset V2 channel/family is named "trades".
            # Preserve the native aggregate-trade identity whenever the payload
            # exposes it; family naming must not erase authoritative identity.
            aggregate_native = (
                row.get("a")
                or row.get("agg_trade_id")
                or row.get("aggTradeId")
                or record.get("agg_trade_id")
            )
            if aggregate_native is not None:
                add("a", aggregate_native)
                continue
            native = (
                row.get("t")
                or row.get("trade_id")
                or row.get("tradeId")
                or row.get("id")
                or record.get("trade_id")
                or record.get("native_id")
            )
            if native is not None:
                add("t", native)
                continue
            fallback = composite(
                row,
                time_keys=("T", "time", "timestamp", "event_ts_ms", "ts"),
                price_keys=("p", "price", "px"),
                size_keys=("q", "qty", "quantity", "size", "sz"),
                side_keys=("side", "S", "isBuyerMaker"),
            )
            if fallback is None:
                return None
            add("fallback", fallback)
        return keys or None

    if venue == "hyperliquid":
        for row in rows:
            native = row.get("tid") or row.get("trade_id") or row.get("tradeId")
            if native is not None:
                add("tid", native)
                continue
            fallback = composite(
                row,
                time_keys=("time", "ts_ms", "timestamp", "event_ts_ms", "ts"),
                price_keys=("px", "price", "p"),
                size_keys=("sz", "size", "qty", "q"),
                side_keys=("side", "dir", "signe"),
                extra_keys=(
                    "hash",
                    "oid",
                    "stable_event_id",
                    "crossed",
                    "startPosition",
                    "start_position",
                    "fee",
                ),
            )
            if fallback is None:
                return None
            add("fallback", fallback)
        return keys or None

    if venue == "bybit":
        for row in rows:
            native = (
                row.get("i")
                or row.get("trdMatchID")
                or row.get("trade_id")
                or row.get("tradeId")
                or row.get("execId")
            )
            if native is not None:
                add("i", native)
                continue
            fallback = composite(
                row,
                time_keys=("T", "timestamp", "time", "event_ts_ms", "ts"),
                price_keys=("p", "price", "px"),
                size_keys=("v", "size", "qty", "q", "sz"),
                side_keys=("S", "side"),
            )
            if fallback is None:
                return None
            add("fallback", fallback)
        return keys or None

    if venue == "okx":
        for row in rows:
            native = row.get("tradeId") or row.get("trade_id")
            if native is not None:
                add("tradeId", native)
                continue
            fallback = composite(
                row,
                time_keys=("ts", "timestamp", "time", "event_ts_ms"),
                price_keys=("px", "price", "p"),
                size_keys=("sz", "size", "qty", "q"),
                side_keys=("side", "S"),
            )
            if fallback is None:
                return None
            add("fallback", fallback)
        return keys or None

    if venue == "gate":
        for row in rows:
            native = row.get("id") or row.get("trade_id") or row.get("tradeId")
            if native is not None:
                add("id", native)
                continue
            fallback = composite(
                row,
                time_keys=(
                    "create_time_ms",
                    "time_ms",
                    "create_time",
                    "time",
                    "timestamp",
                    "event_ts_ms",
                    "ts",
                ),
                price_keys=("price", "px", "p"),
                size_keys=("size", "sz", "qty", "q"),
                side_keys=("side", "S"),
                extra_keys=("contract",),
            )
            if fallback is None:
                return None
            add("fallback", fallback)
        return keys or None

    if venue == "bitget":
        for row in rows:
            native = row.get("tradeId") or row.get("trade_id")
            if native is not None:
                add("tradeId", native)
                continue
            fallback = composite(
                row,
                time_keys=("ts", "timestamp", "time", "event_ts_ms"),
                price_keys=("price", "px", "p"),
                size_keys=("size", "sz", "qty", "q"),
                side_keys=("side", "S"),
            )
            if fallback is None:
                return None
            add("fallback", fallback)
        return keys or None

    # Other trade-like families remain exact only when an explicit native id or
    # a complete deterministic time/price/size composite is available.
    for row in rows:
        native = (
            row.get("tid")
            or row.get("tradeId")
            or row.get("trade_id")
            or row.get("execId")
        )
        if native is not None:
            add("native", native)
            continue
        fallback = composite(
            row,
            time_keys=("time", "timestamp", "event_ts_ms", "ts", "T"),
            price_keys=("px", "price", "p"),
            size_keys=("sz", "size", "qty", "q", "v"),
            side_keys=("side", "S", "dir"),
            extra_keys=("hash", "oid"),
        )
        if fallback is None:
            return None
        add("fallback", fallback)
    return keys or None


def inspect_asset(path: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    expected_size = int(row.get("bytes") or 0)
    expected_sha = str(row.get("sha256") or "").lower()
    if expected_size <= 0 or path.stat().st_size != expected_size:
        raise BackfillError("asset size mismatch")
    actual_sha = _sha256(path)
    if len(expected_sha) != 64 or actual_sha != expected_sha:
        raise BackfillError("asset sha256 mismatch")

    trade_count = 0
    trade_count_exact = True
    # Exact identity strings, never truncated hashes: a collision would invalidate an exact count.
    unique_identities: set[str] = set()
    unique_proven = True
    records = 0
    venue = str(row.get("venue") or "unknown")
    family = str(row.get("family") or "")
    symbol = str(row.get("symbol") or "")

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            if not isinstance(raw, Mapping):
                continue
            records += 1
            keys = _native_trade_keys(
                raw,
                venue=venue,
                family=family,
                symbol=symbol,
            )
            if keys is None:
                summary_count = _summary_trade_count(raw)
                if summary_count is None:
                    trade_count_exact = False
                else:
                    trade_count += summary_count
                unique_proven = False
            else:
                trade_count += len(keys)
                unique_identities.update(keys)

    return {
        "trade_count": trade_count if trade_count_exact else None,
        "trade_count_exact": trade_count_exact,
        "unique_trade_count": len(unique_identities) if unique_proven else None,
        "unique_trade_count_exact": unique_proven,
        "unique_identity_method": "full_native_or_deterministic_composite_string_v3",
        "record_count_scanned": records,
        "asset_sha256": actual_sha,
    }


def _download(row: Mapping[str, Any], destination: Path) -> Path:
    repository = str(row.get("release_repository") or "")
    tag = str(row.get("release_tag") or "")
    asset = str(row.get("release_asset") or "")
    if not repository or not tag or not asset:
        raise BackfillError("release coordinates missing")
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / asset
    # Release assets have stable immutable download URLs. Fetching them directly
    # avoids spending one GitHub API request per shard and therefore keeps large
    # closure backfills within GitHub-hosted rate limits.
    direct_url = (
        f"https://github.com/{repository}/releases/download/"
        f"{quote(tag, safe='')}/{quote(asset, safe='')}"
    )
    headers: list[str] = []
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers = ["-H", f"Authorization: Bearer {token}"]
    result = subprocess.run(
        ["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "3",
         *headers, "--output", os.fspath(path), direct_url],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise BackfillError((result.stderr or result.stdout or "direct release download failed").strip())
    if not path.is_file():
        raise BackfillError("downloaded asset missing")
    return path


def _persist_manifest_counts(row: Mapping[str, Any], result: Mapping[str, Any]) -> None:
    manifest_path = ROOT / str(row.get("manifest_path") or "")
    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(manifest, dict):
        return
    for key in (
        "trade_count",
        "trade_count_exact",
        "unique_trade_count",
        "unique_trade_count_exact",
        "record_count_scanned",
        "asset_sha256",
        "unique_identity_method",
    ):
        if key in result:
            manifest[key] = result[key]
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, manifest_path)


def _load_patch() -> dict[str, Any]:
    if not PATCH_PATH.is_file():
        return {
            "schema": "alina.trade_count_patch.v1",
            "method": "verified_release_asset_scan_no_estimation",
            "counts": {},
        }
    value = json.loads(PATCH_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BackfillError("invalid patch catalog")
    value.setdefault("schema", "alina.trade_count_patch.v1")
    value.setdefault("method", "verified_release_asset_scan_no_estimation")
    value.setdefault("counts", {})
    return value


def _candidate(row: Mapping[str, Any], patch: Mapping[str, Any]) -> bool:
    family = str(row.get("family") or "").lower()
    if family not in TRADE_FAMILIES:
        return False
    dataset_id = str(row.get("dataset_id") or "")
    counts = patch.get("counts") if isinstance(patch, Mapping) else {}
    if not isinstance(counts, Mapping):
        counts = {}
    if not dataset_id or dataset_id in counts:
        return False
    if row.get("trade_count_exact") is True and int(row.get("trade_count") or 0) > 0:
        return False
    return bool(
        row.get("release_repository")
        and row.get("release_tag")
        and row.get("release_asset")
        and row.get("sha256")
        and row.get("bytes")
    )


def _candidate_priority(row: Mapping[str, Any]) -> tuple[int, int, str]:
    """Process the economically useful verified data first, without dropping any tier."""
    status = str(row.get("quality_status") or "").upper()
    replayable = row.get("replay_compatible") is True
    if status == "SAFE" and replayable:
        tier = 0
    elif status == "SAFE":
        tier = 1
    elif status == "PARTIAL":
        tier = 2
    elif status == "REJECT":
        tier = 3
    else:
        tier = 4
    try:
        end_ts = int(row.get("end_ts_ms") or 0)
    except (TypeError, ValueError, OverflowError):
        end_ts = 0
    return (tier, -end_ts, str(row.get("dataset_id") or ""))


def backfill(limit: int) -> dict[str, Any]:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    rows = index.get("shards")
    if not isinstance(rows, list):
        raise BackfillError("invalid data index")
    patch_doc = _load_patch()
    counts = patch_doc.get("counts")
    if not isinstance(counts, dict):
        raise BackfillError("invalid trade count patch counts")

    candidates = sorted(
        [
            row for row in rows
            if isinstance(row, Mapping) and _candidate(row, counts)
        ],
        key=_candidate_priority,
    )[: max(1, int(limit))]
    updated = 0
    failed: list[dict[str, str]] = []
    failure_reasons = patch_doc.get("failure_reasons")
    if not isinstance(failure_reasons, dict):
        failure_reasons = {}

    with tempfile.TemporaryDirectory(prefix="alina-trade-count-") as tmp:
        tmp_root = Path(tmp)
        for row in candidates:
            dataset_id = str(row["dataset_id"])
            try:
                path = _download(row, tmp_root / dataset_id)
                result = inspect_asset(path, row)
            except Exception as exc:
                failure = {"dataset_id": dataset_id, "error": type(exc).__name__}
                failed.append(failure)
                failure_reasons[dataset_id] = failure
                continue
            counts[dataset_id] = result
            failure_reasons.pop(dataset_id, None)
            row.update(result)
            _persist_manifest_counts(row, result)
            updated += 1
            shutil.rmtree(tmp_root / dataset_id, ignore_errors=True)

    patch_doc["counts"] = dict(sorted(counts.items()))
    patch_doc["failure_reasons"] = dict(sorted(failure_reasons.items()))
    patch_doc["processed_exact_shards"] = len(counts)
    patch_doc["remaining_candidate_shards"] = max(0, len([
        row for row in rows
        if isinstance(row, Mapping) and _candidate(row, counts)
    ]))
    PATCH_PATH.write_text(
        json.dumps(patch_doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    INDEX_PATH.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "updated": updated,
        "attempted": len(candidates),
        "failed": failed,
        "remaining_candidate_shards": patch_doc["remaining_candidate_shards"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    try:
        result = backfill(args.limit)
    except (BackfillError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"TRADE_COUNT_BACKFILL_NO_GO:{type(exc).__name__}:{exc}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
