#!/usr/bin/env python3
"""Build an instant, fail-closed view of Alina collection progress.

This is the fast operational counter. It reads durable campaign checkpoints
already committed on main, so it does not wait for Dataset V2 indexing.
catalog/DATA_METRICS.json remains the authoritative indexed/deduplicated view.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = ROOT / "catalog" / "campaigns"
INDEX = ROOT / "catalog" / "DATA_INDEX.json"
DATA_METRICS = ROOT / "catalog" / "DATA_METRICS.json"
OUTPUT = ROOT / "catalog" / "COLLECTION_METRICS.json"

COLLECTION_KINDS = {
    "market_collection",
    "copy_vault_collection",
    "official_archive_collection",
    "event_intelligence_collection",
}
TRADE_FAMILIES = {
    "trades",
    "agg_trades",
    "fills",
    "userfills",
    "user_fills",
    "copy_vault_fills",
}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _exact_nonnegative_int(value: Any) -> int | None:
    if type(value) is not int or value < 0:
        return None
    return value


def _exact_queue_drop_total(value: Any) -> int | None:
    exact = _exact_nonnegative_int(value)
    if exact is not None:
        return exact
    if isinstance(value, Mapping):
        counts = [_exact_nonnegative_int(item) for item in value.values()]
        if all(count is not None for count in counts):
            return sum(counts)
    return None


FRAME_METRIC_FIELDS = (
    "accepted_frames",
    "persisted_frames",
    "l2_frames",
    "bbo_frames",
    "queue_drops",
)


def _frame_metrics_are_complete(metrics: Mapping[str, Any]) -> bool:
    return metrics.get("frame_metrics_complete") is True and all(
        _exact_nonnegative_int(metrics.get(field)) is not None
        for field in FRAME_METRIC_FIELDS
    )


def _summary_from_result(result: Mapping[str, Any]) -> dict[str, Any] | None:
    metrics = result.get("collection_metrics")
    if isinstance(metrics, Mapping):
        compact = dict(metrics)
        # A compact checkpoint carrying an explicit non-negative trade total
        # is itself exact count evidence unless the producer explicitly marks
        # its coverage incomplete.
        if "trade_count_coverage_complete" not in compact:
            observed = compact.get("trade_count_observed")
            compact["trade_count_coverage_complete"] = (
                _exact_nonnegative_int(observed) is not None
            )
        manifest_inventory_complete = (
            compact.get("manifest_inventory_complete") is True
        )
        manifest_counters = (
            _exact_nonnegative_int(compact.get("shard_count")),
            _exact_nonnegative_int(compact.get("safe_count")),
            _exact_nonnegative_int(compact.get("partial_count")),
            _exact_nonnegative_int(compact.get("reject_count")),
        )
        manifest_inventory_complete = (
            manifest_inventory_complete
            and all(value is not None for value in manifest_counters)
            and manifest_counters[1] + manifest_counters[2] + manifest_counters[3]
            == manifest_counters[0]
        )
        compact["manifest_inventory_complete"] = manifest_inventory_complete
        compact["record_count_coverage_complete"] = (
            compact.get("record_count_coverage_complete") is not False
            and _exact_nonnegative_int(compact.get("record_count_observed")) is not None
        )
        compact["compressed_size_coverage_complete"] = (
            compact.get("compressed_size_coverage_complete") is not False
            and _exact_nonnegative_int(compact.get("compressed_bytes")) is not None
        )
        compact["trade_count_coverage_complete"] = (
            compact.get("trade_count_coverage_complete") is True
            and _exact_nonnegative_int(compact.get("trade_count_observed")) is not None
        )
        compact["uncompressed_size_coverage_complete"] = (
            compact.get("uncompressed_size_coverage_complete") is True
            and _exact_nonnegative_int(compact.get("uncompressed_bytes")) is not None
        )
        frame_metrics_complete = _frame_metrics_are_complete(compact)
        if frame_metrics_complete:
            accepted = _exact_nonnegative_int(compact.get("accepted_frames"))
            persisted = _exact_nonnegative_int(compact.get("persisted_frames"))
            l2 = _exact_nonnegative_int(compact.get("l2_frames"))
            bbo = _exact_nonnegative_int(compact.get("bbo_frames"))
            record_count = _exact_nonnegative_int(compact.get("record_count_observed"))
            frame_metrics_complete = (
                accepted is not None
                and persisted is not None
                and l2 is not None
                and bbo is not None
                and record_count is not None
                and accepted >= persisted
                and persisted == record_count
                and l2 <= persisted
                and bbo <= persisted
            )
        compact["frame_metrics_complete"] = (
            manifest_inventory_complete and frame_metrics_complete
        )
        return compact

    raw = result.get("stdout")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        summary = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(summary, Mapping):
        return None

    assets = summary.get("assets")
    trade_count: int | None = 0
    record_count = 0
    trade_assets_seen = False
    asset_frame_counts_complete = isinstance(assets, list)
    asset_l2_frames = 0
    asset_bbo_frames = 0
    if isinstance(assets, list):
        for row in assets:
            if not isinstance(row, Mapping):
                asset_frame_counts_complete = False
                continue
            events = _exact_nonnegative_int(row.get("event_count"))
            if events is None:
                asset_frame_counts_complete = False
            else:
                record_count += events
            family = str(row.get("family") or "").lower()
            if not family:
                asset_frame_counts_complete = False
            if family in {"l2book", "copy_vault_l2", "native_market"}:
                if events is not None:
                    asset_l2_frames += events
            elif family == "bbo":
                if events is not None:
                    asset_bbo_frames += events
            if family in TRADE_FAMILIES:
                trade_assets_seen = True
                if events is None:
                    trade_count = None
                elif trade_count is not None:
                    trade_count += events

    explicit_record_count = _exact_nonnegative_int(
        summary.get("record_count_observed")
    )

    reconciliation = summary.get("reconciliation")
    reference_fills = 0
    reconciliation_complete = False
    if isinstance(reconciliation, Mapping):
        reconciliation_complete = bool(reconciliation)
        for row in reconciliation.values():
            if not isinstance(row, Mapping):
                reconciliation_complete = False
                continue
            reference = _exact_nonnegative_int(row.get("reference_count"))
            matched = _exact_nonnegative_int(row.get("matched_count"))
            live = _exact_nonnegative_int(row.get("live_count"))
            missing = _exact_nonnegative_int(row.get("missing_from_live"))
            live_only = _exact_nonnegative_int(row.get("live_only"))
            duplicate_keys = _exact_nonnegative_int(row.get("duplicate_live_keys"))
            audit = row.get("audit")
            if (
                str(row.get("status") or "").upper() != "MATCHED"
                or not isinstance(audit, Mapping)
                or str(audit.get("status") or "").upper() != "COMPLETE"
                or None in (reference, matched, live, missing, live_only, duplicate_keys)
                or reference != matched
                or reference != live
                or missing != 0
                or live_only != 0
                or duplicate_keys != 0
            ):
                reconciliation_complete = False
            elif reference is not None:
                reference_fills += reference
    live_fills = summary.get("live_fill_counts")
    live_fills_complete = isinstance(live_fills, Mapping) and bool(live_fills)
    live_total = 0
    if isinstance(live_fills, Mapping):
        for value in live_fills.values():
            count = _exact_nonnegative_int(value)
            if count is None:
                live_fills_complete = False
            else:
                live_total += count
    bundle = summary.get("bundle_index")
    if not isinstance(bundle, Mapping):
        bundle = summary.get("bundle")
    if not isinstance(bundle, Mapping):
        bundle = {}

    bundle_shards = _exact_nonnegative_int(bundle.get("shard_count"))
    bundle_safe = _exact_nonnegative_int(bundle.get("safe_count"))
    bundle_partial = _exact_nonnegative_int(bundle.get("partial_count"))
    bundle_reject = _exact_nonnegative_int(bundle.get("reject_count"))
    manifest_inventory_complete = (
        summary.get("manifest_inventory_complete") is True
        and None not in (bundle_shards, bundle_safe, bundle_partial, bundle_reject)
        and bundle_safe + bundle_partial + bundle_reject == bundle_shards
    )
    explicit_trade_count = _exact_nonnegative_int(
        summary.get("trade_count_observed")
    )
    explicit_trade_count_complete = (
        summary.get("trade_count_coverage_complete") is True
        and explicit_trade_count is not None
    )
    has_reconciliation = isinstance(reconciliation, Mapping)
    has_live_fill_counts = isinstance(live_fills, Mapping)
    has_asset_inventory = isinstance(assets, list)
    if has_reconciliation:
        source_trade_count = reference_fills if reconciliation_complete else None
        source_trade_count_complete = reconciliation_complete
    elif has_live_fill_counts:
        source_trade_count = live_total if live_fills_complete else None
        source_trade_count_complete = live_fills_complete
    elif has_asset_inventory:
        source_trade_count = trade_count if manifest_inventory_complete and asset_frame_counts_complete else None
        source_trade_count_complete = (
            manifest_inventory_complete and asset_frame_counts_complete
        )
    else:
        source_trade_count = None
        source_trade_count_complete = False
    if source_trade_count_complete and source_trade_count is not None:
        trade_count = source_trade_count
        trade_count_coverage_complete = (
            not explicit_trade_count_complete
            or explicit_trade_count == source_trade_count
        )
        if not trade_count_coverage_complete:
            trade_count = None
    elif not (has_reconciliation or has_live_fill_counts or has_asset_inventory):
        trade_count = explicit_trade_count if explicit_trade_count_complete else None
        trade_count_coverage_complete = explicit_trade_count_complete
    else:
        trade_count = None
        trade_count_coverage_complete = False

    explicit_record_count_valid = (
        summary.get("record_count_coverage_complete") is True
        and explicit_record_count is not None
        and (
            not asset_frame_counts_complete
            or explicit_record_count == record_count
        )
    )
    record_count_coverage_complete = explicit_record_count_valid or (
        asset_frame_counts_complete
        and manifest_inventory_complete
        and (explicit_record_count is None or explicit_record_count == record_count)
    )
    if record_count_coverage_complete and explicit_record_count is not None:
        record_count = explicit_record_count
    accepted_frames = _exact_nonnegative_int(summary.get("accepted_frames"))
    persisted_frames = _exact_nonnegative_int(summary.get("persisted_frames"))
    l2_frames = _exact_nonnegative_int(summary.get("l2_frames"))
    if l2_frames is None and asset_frame_counts_complete:
        l2_frames = asset_l2_frames
    bbo_frames = _exact_nonnegative_int(summary.get("bbo_frames"))
    if bbo_frames is None and asset_frame_counts_complete:
        bbo_frames = asset_bbo_frames
    drops = _exact_queue_drop_total(summary.get("queue_drops"))
    frame_metrics_complete = (
        summary.get("frame_metrics_complete") is True
        and accepted_frames is not None
        and persisted_frames is not None
        and l2_frames is not None
        and bbo_frames is not None
        and drops is not None
        and accepted_frames >= persisted_frames
        and l2_frames <= persisted_frames
        and bbo_frames <= persisted_frames
        and (
            not asset_frame_counts_complete
            or persisted_frames == record_count
        )
    )
    compressed_bytes = _exact_nonnegative_int(summary.get("compressed_bytes"))
    uncompressed_bytes = _exact_nonnegative_int(summary.get("uncompressed_bytes"))

    return {
        "trade_count_observed": trade_count,
        "trade_count_coverage_complete": trade_count_coverage_complete,
        "record_count_observed": record_count if record_count_coverage_complete else None,
        "accepted_frames": accepted_frames,
        "persisted_frames": persisted_frames,
        "l2_frames": l2_frames,
        "bbo_frames": bbo_frames,
        "queue_drops": drops,
        "manifest_inventory_complete": manifest_inventory_complete,
        "frame_metrics_complete": frame_metrics_complete,
        "shard_count": bundle_shards,
        "safe_count": bundle_safe,
        "partial_count": bundle_partial,
        "reject_count": bundle_reject,
        "compressed_size_coverage_complete": compressed_bytes is not None,
        "compressed_bytes": compressed_bytes,
        "uncompressed_size_coverage_complete": (
            summary.get("uncompressed_size_coverage_complete") is True
            and uncompressed_bytes is not None
        ),
        "uncompressed_bytes": uncompressed_bytes,
        "trade_count_basis": (
            "copy_vault_reference_reconciliation"
            if isinstance(reconciliation, Mapping)
            else "collection_summary_trade_events"
        ),
    }


def _empty_bucket() -> dict[str, int]:
    return {
        "durable_units": 0,
        "units_record_count_incomplete": 0,
        "trades_observed": 0,
        "records_observed": 0,
        "accepted_frames": 0,
        "persisted_frames": 0,
        "l2_frames": 0,
        "bbo_frames": 0,
        "queue_drops": 0,
        "shards": 0,
        "safe_shards": 0,
        "partial_shards": 0,
        "rejected_shards": 0,
        "zero_viable_units": 0,
        "known_excluded_shards": 0,
        "known_excluded_compressed_bytes": 0,
        "compressed_bytes": 0,
        "uncompressed_bytes": 0,
        "units_missing_compact_metrics": 0,
        "units_manifest_inventory_incomplete": 0,
        "units_frame_metrics_incomplete": 0,
        "units_compressed_coverage_incomplete": 0,
        "units_uncompressed_coverage_incomplete": 0,
        "units_trade_count_coverage_incomplete": 0,
    }


def _verify_index_binding(metrics: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the DATA_INDEX binding, refusing a stale derived view.

    COLLECTION_METRICS is intentionally a fast operational view, but its
    indexed counters must never silently describe an older DATA_INDEX.  Test
    fixtures may omit the binding; a real DATA_METRICS generated by
    ``build_catalog_metrics.py`` always carries it, so production builds are
    fail-closed without imposing a catalog on small unit fixtures.
    """
    source_sha = metrics.get("source_index_sha256")
    if not isinstance(source_sha, str) or len(source_sha) != 64:
        return None
    if not INDEX.is_file():
        raise ValueError("COLLECTION_METRICS_SOURCE_INDEX_MISSING")
    index_bytes = INDEX.read_bytes()
    actual_sha = hashlib.sha256(index_bytes).hexdigest()
    if source_sha != actual_sha:
        raise ValueError("COLLECTION_METRICS_STALE_INDEX_SHA")
    try:
        index = json.loads(index_bytes)
        index_shards = index["shard_count"]
        totals = metrics["totals"]
        indexed_shards = totals["TOTAL_SHARDS"]
        trades_collected = totals["TOTAL_TRADES_COLLECTED"]
        trades_replayable = totals["TOTAL_TRADES_REPLAYABLE"]
        trades_safe = totals["TOTAL_TRADES_SAFE"]
        unique_trades = totals.get("TOTAL_UNIQUE_TRADES_GLOBAL")
        unique_coverage_complete = (
            totals.get("GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE") is True
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("COLLECTION_METRICS_INDEX_BINDING_INVALID") from exc
    exact_counts = tuple(
        _exact_nonnegative_int(value)
        for value in (
            index_shards,
            indexed_shards,
            trades_collected,
            trades_replayable,
            trades_safe,
        )
    )
    if any(value is None for value in exact_counts):
        raise ValueError("COLLECTION_METRICS_INDEX_COUNTERS_INVALID")
    index_shards, indexed_shards, trades_collected, trades_replayable, trades_safe = exact_counts
    unique_count = _exact_nonnegative_int(unique_trades)
    if (
        trades_safe > trades_replayable
        or trades_replayable > trades_collected
        or (unique_coverage_complete and unique_count is None)
        or (unique_count is not None and unique_count > trades_collected)
    ):
        raise ValueError("COLLECTION_METRICS_INDEX_COUNTERS_INVALID")
    if index_shards != indexed_shards:
        raise ValueError("COLLECTION_METRICS_INDEX_SHARD_COUNT_MISMATCH")
    return {
        "source_index_sha256": actual_sha,
        "indexed_shards": index_shards,
    }


def build() -> dict[str, Any]:
    totals = _empty_bucket()
    by_kind: dict[str, dict[str, int]] = {}
    campaign_statuses: Counter[str] = Counter()
    admission_reasons: Counter[str] = Counter()
    admission_seen_units = 0
    admission_covered_units = 0
    collection_campaigns = 0
    latest_checkpoint_at: str | None = None

    for path in sorted(CAMPAIGNS.glob("*.json")):
        try:
            campaign = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(campaign, Mapping):
            continue
        kind = str(campaign.get("kind") or "")
        if kind not in COLLECTION_KINDS:
            continue

        collection_campaigns += 1
        campaign_statuses[str(campaign.get("status") or "UNKNOWN")] += 1
        updated_at = str(campaign.get("updated_at") or "")
        if updated_at and (latest_checkpoint_at is None or updated_at > latest_checkpoint_at):
            latest_checkpoint_at = updated_at

        bucket = by_kind.setdefault(kind, _empty_bucket())
        units = campaign.get("completed_units")
        if not isinstance(units, Mapping):
            continue

        for unit in units.values():
            if not isinstance(unit, Mapping):
                continue
            result = unit.get("result")
            if not isinstance(result, Mapping):
                continue
            admission_seen_units += 1
            source = result.get("source_admission")
            if isinstance(source, Mapping):
                excluded = source.get("excluded_shards")
                excluded_bytes = source.get("excluded_compressed_bytes")
                reasons = source.get("blocking_reasons")
                if (
                    type(excluded) is int and excluded >= 0
                    and type(excluded_bytes) is int and excluded_bytes >= 0
                    and isinstance(reasons, Mapping)
                    and source.get("no_rejected_payload_published") is True
                    and all(
                        isinstance(reason, str) and reason
                        and type(count) is int and count >= 0
                        for reason, count in reasons.items()
                    )
                ):
                    admission_covered_units += 1
                    for target, value in (
                        ("known_excluded_shards", excluded),
                        ("known_excluded_compressed_bytes", excluded_bytes),
                    ):
                        totals[target] += value
                        bucket[target] += value
                    admission_reasons.update(reasons)
            if result.get("reason") == "NO_REPLAY_ADMISSIBLE_SHARDS":
                totals["zero_viable_units"] += 1
                bucket["zero_viable_units"] += 1
            if result.get("durable_persisted") is not True and not result.get("release_tag"):
                continue

            compact = _summary_from_result(result)
            totals["durable_units"] += 1
            bucket["durable_units"] += 1
            if compact is None:
                totals["units_missing_compact_metrics"] += 1
                bucket["units_missing_compact_metrics"] += 1
                totals["units_manifest_inventory_incomplete"] += 1
                bucket["units_manifest_inventory_incomplete"] += 1
                totals["units_record_count_incomplete"] += 1
                bucket["units_record_count_incomplete"] += 1
                totals["units_frame_metrics_incomplete"] += 1
                bucket["units_frame_metrics_incomplete"] += 1
                totals["units_compressed_coverage_incomplete"] += 1
                bucket["units_compressed_coverage_incomplete"] += 1
                if kind != "event_intelligence_collection":
                    totals["units_trade_count_coverage_incomplete"] += 1
                    bucket["units_trade_count_coverage_incomplete"] += 1
                continue

            manifest_inventory_complete = (
                compact.get("manifest_inventory_complete") is True
            )
            if not manifest_inventory_complete:
                totals["units_manifest_inventory_incomplete"] += 1
                bucket["units_manifest_inventory_incomplete"] += 1

            if compact.get("trade_count_coverage_complete") is not True:
                totals["units_trade_count_coverage_incomplete"] += 1
                bucket["units_trade_count_coverage_incomplete"] += 1
            if compact.get("record_count_coverage_complete") is not True:
                totals["units_record_count_incomplete"] += 1
                bucket["units_record_count_incomplete"] += 1
            if compact.get("uncompressed_size_coverage_complete") is not True:
                totals["units_uncompressed_coverage_incomplete"] += 1
                bucket["units_uncompressed_coverage_incomplete"] += 1
            if compact.get("compressed_size_coverage_complete") is not True:
                totals["units_compressed_coverage_incomplete"] += 1
                bucket["units_compressed_coverage_incomplete"] += 1
            frame_metrics_complete = (
                manifest_inventory_complete
                and _frame_metrics_are_complete(compact)
            )
            if not frame_metrics_complete:
                totals["units_frame_metrics_incomplete"] += 1
                bucket["units_frame_metrics_incomplete"] += 1

            fields = {
                "trades_observed": "trade_count_observed",
                "records_observed": "record_count_observed",
                "accepted_frames": "accepted_frames",
                "persisted_frames": "persisted_frames",
                "l2_frames": "l2_frames",
                "bbo_frames": "bbo_frames",
                "queue_drops": "queue_drops",
                "shards": "shard_count",
                "safe_shards": "safe_count",
                "partial_shards": "partial_count",
                "rejected_shards": "reject_count",
                "compressed_bytes": "compressed_bytes",
                "uncompressed_bytes": "uncompressed_bytes",
            }
            for target, source in fields.items():
                if target == "records_observed":
                    if compact.get("record_count_coverage_complete") is not True:
                        continue
                    value = _exact_nonnegative_int(compact.get(source))
                    if value is None:
                        continue
                    totals[target] += value
                    bucket[target] += value
                    continue
                if target == "trades_observed":
                    if compact.get("trade_count_coverage_complete") is not True:
                        continue
                    value = _exact_nonnegative_int(compact.get(source))
                    if value is None:
                        continue
                    totals[target] += value
                    bucket[target] += value
                    continue
                if target == "compressed_bytes":
                    if compact.get("compressed_size_coverage_complete") is not True:
                        continue
                    value = _exact_nonnegative_int(compact.get(source))
                    if value is None:
                        continue
                    totals[target] += value
                    bucket[target] += value
                    continue
                if target == "uncompressed_bytes":
                    if compact.get("uncompressed_size_coverage_complete") is not True:
                        continue
                    value = _exact_nonnegative_int(compact.get(source))
                    if value is None:
                        continue
                    totals[target] += value
                    bucket[target] += value
                    continue
                if target in FRAME_METRIC_FIELDS:
                    if not frame_metrics_complete:
                        continue
                    value = _exact_nonnegative_int(compact.get(source))
                    if value is None:
                        continue
                else:
                    value = _int(compact.get(source))
                totals[target] += value
                bucket[target] += value

    indexed: dict[str, Any] = {}
    try:
        doc = json.loads(DATA_METRICS.read_text(encoding="utf-8"))
        index_binding = _verify_index_binding(doc)
        rows = doc.get("totals") if isinstance(doc, Mapping) else {}
        if isinstance(rows, Mapping):
            unique_trades = _exact_nonnegative_int(
                rows.get("TOTAL_UNIQUE_TRADES_GLOBAL")
            )
            indexed = {
                "trades_indexed_exact": _exact_nonnegative_int(
                    rows.get("TOTAL_TRADES_COLLECTED")
                ),
                "trades_replayable": _exact_nonnegative_int(
                    rows.get("TOTAL_TRADES_REPLAYABLE")
                ),
                "trades_safe": _exact_nonnegative_int(
                    rows.get("TOTAL_TRADES_SAFE")
                ),
                "global_unique_trades": unique_trades,
                "global_unique_coverage_complete": (
                    rows.get("GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE") is True
                    and unique_trades is not None
                ),
                "indexed_shards": _exact_nonnegative_int(
                    rows.get("TOTAL_SHARDS")
                ),
            }
            if index_binding is not None:
                indexed.update(index_binding)
    except (OSError, json.JSONDecodeError, TypeError):
        indexed = {}

    def public_bucket(bucket: Mapping[str, int]) -> dict[str, Any]:
        result: dict[str, Any] = dict(bucket)
        if bucket["units_manifest_inventory_incomplete"] > 0:
            for field in (
                "records_observed",
                "shards",
                "safe_shards",
                "partial_shards",
                "rejected_shards",
                "uncompressed_bytes",
            ):
                result[field] = None
        if bucket["units_record_count_incomplete"] > 0:
            result["records_observed"] = None
        if bucket["units_compressed_coverage_incomplete"] > 0:
            result["compressed_bytes"] = None
        if (
            bucket["durable_units"] == 0
            or bucket["units_frame_metrics_incomplete"] > 0
        ):
            for field in FRAME_METRIC_FIELDS:
                result[field] = None
        if (
            bucket["durable_units"] == 0
            or bucket["units_trade_count_coverage_incomplete"] > 0
        ):
            result["trades_observed"] = None
        if bucket["units_uncompressed_coverage_incomplete"] > 0:
            result["uncompressed_bytes"] = None
        return result

    totals_public = public_bucket(totals)
    by_kind_public = {
        kind: public_bucket(bucket) for kind, bucket in sorted(by_kind.items())
    }
    collection_metrics_complete = (
        totals["durable_units"] > 0
        and totals["units_missing_compact_metrics"] == 0
        and totals["units_record_count_incomplete"] == 0
        and totals["units_manifest_inventory_incomplete"] == 0
        and totals["units_frame_metrics_incomplete"] == 0
        and totals["units_compressed_coverage_incomplete"] == 0
        and totals["units_trade_count_coverage_incomplete"] == 0
        and totals["units_uncompressed_coverage_incomplete"] == 0
    )
    # Every durable result is an observed admission unit.  Even an empty
    # result must carry an explicit validated admission record before the
    # quality verdict can be COMPLETE.
    admission_complete = admission_seen_units == admission_covered_units
    quality_reasons: list[str] = []
    if not collection_metrics_complete:
        quality_reasons.append("COLLECTION_METRICS_INCOMPLETE")
    if not admission_complete:
        quality_reasons.append("SOURCE_ADMISSION_INCOMPLETE")
    quality_status = "COMPLETE" if not quality_reasons else "INCOMPLETE"

    payload = {
        "schema": "alina.collection_metrics.v1",
        "status": "OK",
        "stale": False,
        # ``status`` is the publication/build result for compatibility.  The
        # quality verdict must remain separate so an operationally published
        # report cannot be mistaken for complete dataset evidence.
        "quality_status": quality_status,
        "quality_reasons": quality_reasons,
        "dataset_generation": "V2_FRESH",
        "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "source": "durable_campaign_checkpoints_on_main",
        "source_index_sha256": indexed.get("source_index_sha256"),
        "latest_checkpoint_at_utc": latest_checkpoint_at,
        "collection_campaign_count": collection_campaigns,
        "campaign_status_counts": dict(sorted(campaign_statuses.items())),
        "instant": {
            "trades_collected_observed": totals_public["trades_observed"],
            "accepted_frames": totals_public["accepted_frames"],
            "persisted_frames": totals_public["persisted_frames"],
            "l2_frames": totals_public["l2_frames"],
            "bbo_frames": totals_public["bbo_frames"],
            "queue_drops": totals_public["queue_drops"],
            "shards_published": (
                None
                if totals["units_manifest_inventory_incomplete"] > 0
                else totals["shards"]
            ),
            "compressed_bytes_known": totals_public["compressed_bytes"],
            "uncompressed_bytes_known": (
                None
                if totals["units_uncompressed_coverage_incomplete"] > 0
                else totals["uncompressed_bytes"]
            ),
            "coverage_complete": (
                totals["durable_units"] > 0
                and totals["units_trade_count_coverage_incomplete"] == 0
            ),
            "uncompressed_coverage_complete": (
                totals["durable_units"] > 0
                and totals["units_uncompressed_coverage_incomplete"] == 0
            ),
            "all_collection_metrics_complete": collection_metrics_complete,
            "units_missing_compact_metrics": totals["units_missing_compact_metrics"],
            "units_manifest_inventory_incomplete": (
                totals["units_manifest_inventory_incomplete"]
            ),
            "units_frame_metrics_incomplete": (
                totals["units_frame_metrics_incomplete"]
            ),
            "units_trade_count_coverage_incomplete": (
                totals["units_trade_count_coverage_incomplete"]
            ),
        },
        "totals": totals_public,
        "by_kind": by_kind_public,
        "source_admission": {
            "status": (
                "COMPLETE" if admission_complete
                else "INCOMPLETE"
            ),
            "units_observed": admission_seen_units,
            "units_reported": admission_covered_units,
            "known_excluded_shards": totals["known_excluded_shards"],
            "known_excluded_compressed_bytes": totals["known_excluded_compressed_bytes"],
            "zero_viable_units": totals["zero_viable_units"],
            "blocking_reason_occurrences": dict(sorted(admission_reasons.items())),
            "reason_counts_may_overlap": True,
            "excluded_data_published": (
                False if admission_seen_units > 0
                and admission_seen_units == admission_covered_units
                else None
            ),
        },

        "indexed_dataset": indexed,
        "semantics": {
            "trades_collected_observed": (
                "cumulative trade/fill events reported by durable collection checkpoints; "
                "may include cross-window overlap and is not a global-unique claim"
            ),
            "trades_indexed_exact": (
                "exact trade count from DATA_INDEX-backed Dataset V2 metrics"
            ),
            "trades_replayable": (
                "exact count for SAFE shards that are replay-compatible; non-SAFE "
                "rows remain excluded even if structurally replayable. For the "
                "all-status replayable total, use "
                "REPLAY_COMPATIBILITY_REASONS.replayable_trade_count_exact"
            ),
            "global_unique_trades": (
                "only populated after deterministic cross-shard identity deduplication"
            ),
        },
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    _write_atomic(payload)
    return payload


def _write_atomic(payload: Mapping[str, Any]) -> None:
    """Persist metrics without ever exposing a partially written JSON file."""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    tmp.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(OUTPUT)


def _read_previous() -> dict[str, Any] | None:
    try:
        row = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return dict(row) if isinstance(row, Mapping) else None


def safe_build() -> dict[str, Any]:
    """Best-effort operational publication.

    Metrics must never be able to stop collection. On an unexpected metrics
    failure, preserve the last valid snapshot, mark it stale/degraded, and
    return success to the caller. If there is no previous snapshot, publish
    unknown values rather than inventing zero.
    """
    previous = _read_previous()
    try:
        return build()
    except Exception as exc:  # defensive boundary: observability cannot stop collection
        error = f"{type(exc).__name__}: {exc}"
        if previous is not None:
            degraded = dict(previous)
            degraded["status"] = "DEGRADED"
            degraded["stale"] = True
            degraded["quality_status"] = "DEGRADED"
            degraded["quality_reasons"] = ["METRICS_BUILD_FAILED"]
            degraded["source"] = "last_known_good_snapshot"
            degraded["degraded_reason"] = error
            degraded["rebuild_required"] = True
        else:
            degraded = {
                "schema": "alina.collection_metrics.v1",
                "status": "DEGRADED",
                "stale": True,
                "quality_status": "DEGRADED",
                "quality_reasons": ["METRICS_BUILD_FAILED"],
                "dataset_generation": "V2_FRESH",
                "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
                "source": "no_last_known_good_snapshot",
                "degraded_reason": error,
                "rebuild_required": True,
                "instant": {
                    "trades_collected_observed": None,
                    "persisted_frames": None,
                    "shards_published": None,
                    "compressed_bytes_known": None,
                    "coverage_complete": False,
                    "all_collection_metrics_complete": False,
                },
                "indexed_dataset": {},
                "paper_only": True,
                "read_only": True,
                "real_execution": False,
            }
        with suppress(Exception):
            _write_atomic(degraded)
        # Persistence failure is non-fatal to collection. The JSON emitted on
        # stdout still exposes the degraded state to logs.
        return degraded


if __name__ == "__main__":
    print(json.dumps(safe_build(), sort_keys=True))
