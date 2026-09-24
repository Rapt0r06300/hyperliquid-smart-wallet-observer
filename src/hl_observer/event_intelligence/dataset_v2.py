"""GitHub-hosted, public/read-only Event Intelligence Dataset V2 collection."""

from __future__ import annotations

import gzip
import json
import time
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.datasets.v2_export import write_manifest
from hl_observer.datasets.v2_pipeline import build_bundle, finalize_manifest
from hl_observer.event_intelligence.archive import EventIntelligenceArchive
from hl_observer.event_intelligence.direct_sources import (
    DirectSourceReadOnlyClient,
    gdacs_query_params,
    gdelt_query_params,
    normalize_eonet,
    normalize_gdacs,
    normalize_gdelt_articles,
    normalize_usgs,
)
from hl_observer.event_intelligence.integration_registry import integration_contract
from hl_observer.event_intelligence.worldmonitor import WorldMonitorEvent

SOURCE_ORDER = ("usgs_earthquakes", "nasa_eonet", "gdacs", "gdelt_doc")


def _source_params(source_id: str) -> dict[str, object]:
    if source_id == "nasa_eonet":
        return {"status": "open", "limit": 100}
    if source_id == "gdacs":
        return gdacs_query_params()
    if source_id == "gdelt_doc":
        return gdelt_query_params(
            "(bitcoin OR ethereum OR crypto OR stablecoin)",
            max_records=250,
            timespan="15min",
        )
    return {}


def _normalize(
    source_id: str,
    payload: Mapping[str, Any],
    *,
    received_ts_ms: int,
) -> list[WorldMonitorEvent]:
    if source_id == "usgs_earthquakes":
        rows = normalize_usgs(payload, received_ts_ms=received_ts_ms)
    elif source_id == "nasa_eonet":
        rows = normalize_eonet(payload, received_ts_ms=received_ts_ms)
    elif source_id == "gdacs":
        rows = normalize_gdacs(payload, received_ts_ms=received_ts_ms)
    elif source_id == "gdelt_doc":
        rows = normalize_gdelt_articles(payload, received_ts_ms=received_ts_ms)
    else:  # pragma: no cover - SOURCE_ORDER is closed above
        raise ValueError("DIRECT_SOURCE_NOT_ALLOWLISTED")
    return [
        WorldMonitorEvent(
            event=row,
            kind=source_id,
            publisher=row.source,
            coverage_state="current",
        )
        for row in rows
    ]


def _slug(value: object) -> str:
    return "".join(
        char.lower() if char.isalnum() else "-" for char in str(value or "")
    ).strip("-") or "unknown"


def _write_source_shards(
    archive_path: Path,
    shard_root: Path,
    *,
    collection_run_id: str,
    monotonic_ns: int,
) -> int:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in archive_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        record = json.loads(raw)
        payload = record["payload"]
        source = str(payload["source"])
        received = int(payload["retrieval_ts_ms"])
        grouped[source].append(
            {
                "source_id": source,
                "channel": "external_events",
                "instrument": "GLOBAL",
                "received_ts_ms": received,
                # External-event source/publication times remain in the
                # structured payload.  They are not an exchange stream clock;
                # causal availability is the collector receive timestamp.
                "exchange_ts_ms": None,
                "local_monotonic_ns": int(monotonic_ns) + int(record["sequence"]),
                "connection_id": f"{collection_run_id}:{_slug(source)}",
                "sequence": int(record["sequence"]),
                "gap_count": 0,
                "reconnect_count": 0,
                "raw_sha256": record["record_sha256"],
                "parsed_summary": {
                    "archive_schema": record["schema"],
                    "archive_sequence": record["sequence"],
                    "previous_record_sha256": record["previous_record_sha256"],
                    "record_sha256": record["record_sha256"],
                    "external_event": payload,
                },
                "provenance": {
                    "access": "public_read_only",
                    "transport": "https",
                    "authenticated": False,
                    "timestamp_semantics": "causal_event_availability",
                },
                "real_execution": False,
            }
        )

    for source, rows in sorted(grouped.items()):
        target = shard_root / _slug(source) / "shards" / "events.jsonl.gz"
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wt", encoding="utf-8", newline="\n") as handle:
            for row in sorted(rows, key=lambda value: (value["received_ts_ms"], value["sequence"])):
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(grouped)


def build_public_event_bundle(
    *,
    output_root: str | Path,
    collector_version: str,
    collection_run_id: str,
    client: Any | None = None,
    received_ts_ms: int | None = None,
    monotonic_ns: int | None = None,
) -> dict[str, Any]:
    """Collect four keyless public sources and build an honest V2 bundle.

    Exact independent reconciliation does not exist for these heterogeneous
    external events, so every shard remains PARTIAL.  It may feed research but
    cannot authorize validation or PnL promotion.
    """

    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    now_ms = int(received_ts_ms if received_ts_ms is not None else time.time_ns() // 1_000_000)
    mono = int(monotonic_ns if monotonic_ns is not None else time.monotonic_ns())
    source_client = client or DirectSourceReadOnlyClient(timeout_s=20.0)
    archive = EventIntelligenceArchive(output / "raw" / "events_r2.jsonl")
    source_status: dict[str, dict[str, object]] = {}

    for source_id in SOURCE_ORDER:
        try:
            payload = source_client.get_json(
                source_id,
                params=_source_params(source_id),
                api_key="",
            )
            events = _normalize(source_id, payload, received_ts_ms=now_ms)
            results = archive.append_many(events)
            appended = sum(1 for result in results if result.appended)
            source_status[source_id] = {
                "status": "COLLECTED" if appended else "NO_DATA",
                "normalized": len(events),
                "appended": appended,
            }
        except Exception as exc:  # each independent public source degrades separately
            source_status[source_id] = {
                "status": "UNAVAILABLE",
                "reason": exc.__class__.__name__,
                "normalized": 0,
                "appended": 0,
            }

    if archive.count <= 0:
        raise RuntimeError("NO_EVENT_INTELLIGENCE_DATA")

    shard_count = _write_source_shards(
        archive.path,
        output / "raw_shards",
        collection_run_id=str(collection_run_id),
        monotonic_ns=mono,
    )
    if shard_count <= 0:
        raise RuntimeError("NO_EVENT_INTELLIGENCE_DATA")

    bundle = build_bundle(
        output / "raw_shards",
        output,
        collector_version=str(collector_version),
        collection_run_id=str(collection_run_id),
    )
    contract = integration_contract()
    manifests: list[dict[str, Any]] = []
    for relative in bundle["manifests"]:
        path = output / str(relative)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["reconciliation"] = {
            "status": "UNAVAILABLE",
            "reason": "NO_INDEPENDENT_EXACT_REFERENCE",
        }
        manifest["event_intelligence"] = contract
        manifest = finalize_manifest(manifest)
        write_manifest(manifest, path)
        manifests.append(manifest)

    bundle.update(
        {
            "shard_count": len(manifests),
            "safe_count": sum(row["quality_status"] == "SAFE" for row in manifests),
            "partial_count": sum(row["quality_status"] == "PARTIAL" for row in manifests),
            "reject_count": sum(row["quality_status"] == "REJECT" for row in manifests),
            "source_status": source_status,
            "event_intelligence": contract,
            "read_only": True,
            "real_execution": False,
        }
    )
    write_manifest(bundle, output / "BUNDLE_INDEX.json")
    return bundle


__all__ = ["SOURCE_ORDER", "build_public_event_bundle"]
