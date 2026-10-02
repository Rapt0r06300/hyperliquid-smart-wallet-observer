#!/usr/bin/env python3
"""Build an instant, fail-closed view of Alina collection progress.

This is the fast operational counter. It reads durable campaign checkpoints
already committed on main, so it does not wait for Dataset V2 indexing.
catalog/DATA_METRICS.json remains the authoritative indexed/deduplicated view.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = ROOT / "catalog" / "campaigns"
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
                isinstance(observed, int)
                and not isinstance(observed, bool)
                and observed >= 0
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
    trade_count = 0
    record_count = 0
    trade_assets_seen = False
    if isinstance(assets, list):
        for row in assets:
            if not isinstance(row, Mapping):
                continue
            events = _int(row.get("event_count"))
            record_count += events
            if str(row.get("family") or "").lower() in TRADE_FAMILIES:
                trade_assets_seen = True
                trade_count += events

    reconciliation = summary.get("reconciliation")
    reference_fills = 0
    reconciliation_complete = False
    if isinstance(reconciliation, Mapping):
        reconciliation_complete = True
        for row in reconciliation.values():
            if not isinstance(row, Mapping):
                reconciliation_complete = False
                continue
            if str(row.get("status") or "").upper() != "MATCHED":
                reconciliation_complete = False
            reference_fills += _int(row.get("reference_count"))
    live_fills = summary.get("live_fill_counts")
    if isinstance(live_fills, Mapping):
        live_total = sum(_int(v) for v in live_fills.values())
        if reference_fills or reconciliation_complete:
            trade_count = reference_fills
        else:
            trade_count = live_total

    bundle = summary.get("bundle_index")
    if not isinstance(bundle, Mapping):
        bundle = summary.get("bundle")
    if not isinstance(bundle, Mapping):
        bundle = {}

    drops = summary.get("queue_drops")
    if isinstance(drops, Mapping):
        drops = sum(_int(v) for v in drops.values())

    fallback_trade_coverage = (
        reconciliation_complete
        if isinstance(reconciliation, Mapping)
        else not trade_assets_seen
    )

    return {
        "trade_count_observed": trade_count,
        "trade_count_coverage_complete": fallback_trade_coverage,
        "record_count_observed": record_count,
        "accepted_frames": _int(summary.get("accepted_frames")),
        "persisted_frames": _int(summary.get("persisted_frames")),
        "l2_frames": _int(summary.get("l2_frames")),
        "queue_drops": _int(drops),
        "shard_count": _int(bundle.get("shard_count")),
        "safe_count": _int(bundle.get("safe_count")),
        "partial_count": _int(bundle.get("partial_count")),
        "reject_count": _int(bundle.get("reject_count")),
        "compressed_bytes": _int(summary.get("compressed_bytes")),
        "trade_count_basis": (
            "copy_vault_reference_reconciliation"
            if isinstance(reconciliation, Mapping)
            else "collection_summary_trade_events"
        ),
    }


def _empty_bucket() -> dict[str, int]:
    return {
        "durable_units": 0,
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
        "compressed_bytes": 0,
        "uncompressed_bytes": 0,
        "units_missing_compact_metrics": 0,
        "units_uncompressed_coverage_incomplete": 0,
        "units_trade_count_coverage_incomplete": 0,
    }


def build() -> dict[str, Any]:
    totals = _empty_bucket()
    by_kind: dict[str, dict[str, int]] = {}
    campaign_statuses: Counter[str] = Counter()
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
            if result.get("durable_persisted") is not True and not result.get("release_tag"):
                continue

            compact = _summary_from_result(result)
            totals["durable_units"] += 1
            bucket["durable_units"] += 1
            if compact is None:
                totals["units_missing_compact_metrics"] += 1
                bucket["units_missing_compact_metrics"] += 1
                if kind != "event_intelligence_collection":
                    totals["units_trade_count_coverage_incomplete"] += 1
                    bucket["units_trade_count_coverage_incomplete"] += 1
                continue

            if compact.get("trade_count_coverage_complete") is not True:
                totals["units_trade_count_coverage_incomplete"] += 1
                bucket["units_trade_count_coverage_incomplete"] += 1
            if compact.get("uncompressed_size_coverage_complete") is not True:
                totals["units_uncompressed_coverage_incomplete"] += 1
                bucket["units_uncompressed_coverage_incomplete"] += 1

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
                value = _int(compact.get(source))
                totals[target] += value
                bucket[target] += value

    indexed: dict[str, Any] = {}
    try:
        doc = json.loads(DATA_METRICS.read_text(encoding="utf-8"))
        rows = doc.get("totals") if isinstance(doc, Mapping) else {}
        if isinstance(rows, Mapping):
            indexed = {
                "trades_indexed_exact": _int(rows.get("TOTAL_TRADES_COLLECTED")),
                "trades_replayable": _int(rows.get("TOTAL_TRADES_REPLAYABLE")),
                "trades_safe": _int(rows.get("TOTAL_TRADES_SAFE")),
                "global_unique_trades": (
                    int(rows["TOTAL_UNIQUE_TRADES_GLOBAL"])
                    if isinstance(rows.get("TOTAL_UNIQUE_TRADES_GLOBAL"), int)
                    else None
                ),
                "global_unique_coverage_complete": (
                    rows.get("GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE") is True
                ),
                "indexed_shards": _int(rows.get("TOTAL_SHARDS")),
            }
    except (OSError, ValueError, TypeError):
        indexed = {}

    payload = {
        "schema": "alina.collection_metrics.v1",
        "status": "OK",
        "stale": False,
        "dataset_generation": "V2_FRESH",
        "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "source": "durable_campaign_checkpoints_on_main",
        "latest_checkpoint_at_utc": latest_checkpoint_at,
        "collection_campaign_count": collection_campaigns,
        "campaign_status_counts": dict(sorted(campaign_statuses.items())),
        "instant": {
            "trades_collected_observed": totals["trades_observed"],
            "persisted_frames": totals["persisted_frames"],
            "shards_published": totals["shards"],
            "compressed_bytes_known": totals["compressed_bytes"],
            "uncompressed_bytes_known": totals["uncompressed_bytes"],
            "l2_frames": totals["l2_frames"],
            "bbo_frames": totals["bbo_frames"],
            "coverage_complete": totals["units_trade_count_coverage_incomplete"] == 0,
            "uncompressed_coverage_complete": (
                totals["units_uncompressed_coverage_incomplete"] == 0
            ),
            "all_collection_metrics_complete": totals["units_missing_compact_metrics"] == 0,
            "units_missing_compact_metrics": totals["units_missing_compact_metrics"],
            "units_trade_count_coverage_incomplete": (
                totals["units_trade_count_coverage_incomplete"]
            ),
        },
        "totals": totals,
        "by_kind": dict(sorted(by_kind.items())),
        "indexed_dataset": indexed,
        "semantics": {
            "trades_collected_observed": (
                "cumulative trade/fill events reported by durable collection checkpoints; "
                "may include cross-window overlap and is not a global-unique claim"
            ),
            "trades_indexed_exact": (
                "exact trade count from DATA_INDEX-backed Dataset V2 metrics"
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
            degraded["source"] = "last_known_good_snapshot"
            degraded["degraded_reason"] = error
            degraded["rebuild_required"] = True
        else:
            degraded = {
                "schema": "alina.collection_metrics.v1",
                "status": "DEGRADED",
                "stale": True,
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
        try:
            _write_atomic(degraded)
        except Exception:
            # Even persistence failure is non-fatal to collection. The JSON
            # emitted on stdout still exposes the degraded state to logs.
            pass
        return degraded


if __name__ == "__main__":
    print(json.dumps(safe_build(), sort_keys=True))
