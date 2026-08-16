from __future__ import annotations

import gzip
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from hl_observer.datasets.research_lab_stream import (
    REPORT_JSON,
    REPORT_MD,
    _bounded_increment,
    _counter_from,
    _first_value,
    _gib,
    _merge_metric_aggregate,
    _metric_add,
    _metric_candidates,
    _metric_state,
    _metrics_from,
    _new_state,
    _relative,
    _serialize_metric,
    _source_signature,
    _timestamp_from_row,
    discover_research_jsonl,
    profile_research_jsonl,
    render_research_markdown,
)


def _progress_percent(physical_offset: int, source_size: int) -> float | None:
    if source_size <= 0:
        return None
    return round(min(100.0, max(0.0, physical_offset / source_size * 100.0)), 4)


def _normalize_plain_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(profile)
    scanned = int(result.get("scanned_bytes") or result.get("offset") or 0)
    source_size = int(result.get("source_size") or 0)
    result.setdefault("logical_scanned_bytes", scanned)
    result.setdefault("logical_scanned_gib", _gib(scanned))
    result.setdefault("scanned_physical_bytes", scanned)
    result.setdefault("scanned_physical_gib", _gib(scanned))
    result.setdefault("physical_offset", int(result.get("offset") or scanned))
    result.setdefault("progress_basis", "source_bytes")
    result.setdefault("progress_percent", _progress_percent(scanned, source_size))
    return result


def profile_research_jsonl_safe(
    root: str | Path,
    path: str | Path,
    *,
    resume: bool = True,
    max_bytes: int = 0,
    max_lines: int = 0,
    sample_every: int = 100_000,
    sample_limit: int = 5_000,
    heartbeat_seconds: float = 5.0,
    checkpoint_seconds: float = 30.0,
) -> dict[str, Any]:
    """Profile a Research Lab JSONL without mixing compressed and logical offsets.

    Plain JSONL files keep the existing resumable scanner. For ``.jsonl.gz`` files,
    ``GzipFile.tell()`` is a logical/decompressed offset while the source file size is
    compressed. This wrapper therefore tracks both values and bases percent/ETA only
    on the underlying compressed file position.
    """

    source = Path(path).resolve()
    if not source.name.casefold().endswith(".gz"):
        return _normalize_plain_profile(
            profile_research_jsonl(
                root,
                source,
                resume=resume,
                max_bytes=max_bytes,
                max_lines=max_lines,
                sample_every=sample_every,
                sample_limit=sample_limit,
                heartbeat_seconds=heartbeat_seconds,
                checkpoint_seconds=checkpoint_seconds,
            )
        )

    resolved_root = Path(root).resolve()
    relative = _relative(resolved_root, source)
    signature = _source_signature(source)
    state = _new_state(relative, signature)
    state["complete"] = False
    key_counts = _counter_from(state.get("key_counts"))
    family_counts = _counter_from(state.get("family_counts"))
    event_counts = _counter_from(state.get("event_counts"))
    coin_counts = _counter_from(state.get("coin_counts"))
    metrics = _metrics_from(state.get("metrics"))
    samples: list[dict[str, Any]] = []
    started = time.monotonic()
    last_heartbeat = started
    stop_reason = "EOF"
    logical_at_start = 0
    source_size = int(signature["size"])

    with source.open("rb") as raw_handle:
        with gzip.GzipFile(fileobj=raw_handle, mode="rb") as handle:
            while True:
                logical_before = int(handle.tell())
                raw_line = handle.readline()
                physical_after = min(source_size, max(0, int(raw_handle.tell())))
                if not raw_line:
                    state["complete"] = True
                    stop_reason = "EOF"
                    state["physical_offset"] = source_size
                    break

                logical_after = int(handle.tell())
                state["offset"] = logical_after
                state["physical_offset"] = physical_after
                state["lines"] = int(state.get("lines") or 0) + 1
                try:
                    decoded = raw_line.decode("utf-8")
                    parsed = json.loads(decoded)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    state["invalid_json"] = int(state.get("invalid_json") or 0) + 1
                    parsed = None
                else:
                    state["valid_json"] = int(state.get("valid_json") or 0) + 1

                if isinstance(parsed, Mapping):
                    state["object_rows"] = int(state.get("object_rows") or 0) + 1
                    for key in parsed.keys():
                        _bounded_increment(key_counts, key)
                    family = _first_value(parsed, ("family", "strategy_family", "signal_family", "strategy", "engine", "module"))
                    event = _first_value(parsed, ("event_type", "type", "action", "decision", "status", "reason"))
                    coin = _first_value(parsed, ("coin", "symbol", "asset"))
                    if family:
                        _bounded_increment(family_counts, family)
                    if event:
                        _bounded_increment(event_counts, event)
                    if coin:
                        _bounded_increment(coin_counts, coin.upper())
                    ts_ms = _timestamp_from_row(parsed)
                    if ts_ms is not None:
                        current_min = state.get("timestamp_min_ms")
                        current_max = state.get("timestamp_max_ms")
                        state["timestamp_min_ms"] = ts_ms if current_min is None else min(int(current_min), ts_ms)
                        state["timestamp_max_ms"] = ts_ms if current_max is None else max(int(current_max), ts_ms)
                    for metric_name, raw_value in _metric_candidates(parsed):
                        try:
                            value = float(raw_value)
                        except (TypeError, ValueError, OverflowError):
                            continue
                        if value != value or value in (float("inf"), float("-inf")):
                            continue
                        metric_state = metrics.setdefault(metric_name, _metric_state())
                        _metric_add(metric_state, value)
                    line_number = int(state["lines"])
                    if sample_every > 0 and line_number % sample_every == 0 and len(samples) < sample_limit:
                        samples.append(
                            {
                                "line": line_number,
                                "offset": logical_before,
                                "physical_offset": physical_after,
                                "timestamp_ms": ts_ms,
                                "family": family,
                                "event": event,
                                "coin": coin,
                            }
                        )
                elif parsed is not None:
                    state["non_object_rows"] = int(state.get("non_object_rows") or 0) + 1

                logical_processed = max(0, logical_after - logical_at_start)
                if max_bytes > 0 and logical_processed >= max_bytes:
                    stop_reason = "MAX_BYTES"
                    break
                if max_lines > 0 and int(state["lines"]) >= max_lines:
                    stop_reason = "MAX_LINES"
                    break

                now = time.monotonic()
                if now - last_heartbeat >= max(0.2, heartbeat_seconds):
                    elapsed = max(0.001, now - started)
                    physical = min(source_size, max(0, int(raw_handle.tell())))
                    physical_speed = physical / elapsed
                    logical_speed = logical_processed / elapsed
                    percent = _progress_percent(physical, source_size)
                    remaining = max(0, source_size - physical)
                    eta = remaining / physical_speed if physical_speed > 0 else None
                    percent_text = "?" if percent is None else f"{percent:6.2f}%"
                    eta_text = "?" if eta is None else f"{eta:.0f}s"
                    print(
                        f"[RESEARCH-LAB-GZ] {relative} physique={percent_text} "
                        f"lignes={state['lines']} invalides={state['invalid_json']} "
                        f"compresse={physical_speed / (1024**2):.2f} MiB/s "
                        f"decompresse={logical_speed / (1024**2):.2f} MiB/s ETA={eta_text}",
                        flush=True,
                    )
                    last_heartbeat = now

            state["physical_offset"] = min(source_size, max(0, int(raw_handle.tell())))

    logical_scanned = int(state.get("offset") or 0)
    physical_scanned = source_size if state.get("complete") is True else int(state.get("physical_offset") or 0)
    state["key_counts"] = dict(key_counts.most_common(500))
    state["family_counts"] = dict(family_counts.most_common(500))
    state["event_counts"] = dict(event_counts.most_common(500))
    state["coin_counts"] = dict(coin_counts.most_common(500))
    state["metrics"] = {name: _serialize_metric(value) for name, value in sorted(metrics.items())}
    state["samples"] = samples
    state["stop_reason"] = stop_reason
    state["compressed"] = True
    state["resume_supported"] = False
    state["resumed"] = False
    state["cached_complete"] = False
    state["checkpoint"] = None
    state["logical_scanned_bytes"] = logical_scanned
    state["logical_scanned_gib"] = _gib(logical_scanned)
    state["scanned_physical_bytes"] = physical_scanned
    state["scanned_physical_gib"] = _gib(physical_scanned)
    # Compatibility: aggregate scanned_bytes now means bytes of the source file physically consumed.
    state["scanned_bytes"] = physical_scanned
    state["scanned_gib"] = _gib(physical_scanned)
    state["progress_basis"] = "compressed_physical_bytes"
    state["progress_percent"] = 100.0 if state.get("complete") else _progress_percent(physical_scanned, source_size)
    return state


def profile_research_workspace_safe(
    root: str | Path,
    *,
    resume: bool = True,
    max_files: int = 0,
    max_bytes_per_file: int = 0,
    max_lines_per_file: int = 0,
    sample_every: int = 100_000,
    heartbeat_seconds: float = 5.0,
) -> dict[str, Any]:
    resolved = Path(root).resolve()
    files = discover_research_jsonl(resolved)
    if max_files > 0:
        files = files[:max_files]

    profiles: list[dict[str, Any]] = []
    family_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    coin_counts: Counter[str] = Counter()
    metrics: dict[str, dict[str, Any]] = {}
    for index, path in enumerate(files, 1):
        print(f"[RESEARCH-LAB] fichier {index}/{len(files)}: {_relative(resolved, path)}", flush=True)
        profile = profile_research_jsonl_safe(
            resolved,
            path,
            resume=resume,
            max_bytes=max_bytes_per_file,
            max_lines=max_lines_per_file,
            sample_every=sample_every,
            heartbeat_seconds=heartbeat_seconds,
        )
        profiles.append(profile)
        family_counts.update(profile.get("family_counts") or {})
        event_counts.update(profile.get("event_counts") or {})
        coin_counts.update(profile.get("coin_counts") or {})
        raw_metrics = profile.get("metrics")
        if isinstance(raw_metrics, Mapping):
            for name, raw in raw_metrics.items():
                if not isinstance(raw, Mapping):
                    continue
                aggregate = metrics.setdefault(str(name), _metric_state())
                _merge_metric_aggregate(aggregate, raw)

    total_source_bytes = sum(int(profile.get("source_size") or 0) for profile in profiles)
    total_physical_bytes = sum(int(profile.get("scanned_physical_bytes") or profile.get("scanned_bytes") or 0) for profile in profiles)
    total_logical_bytes = sum(int(profile.get("logical_scanned_bytes") or profile.get("scanned_bytes") or 0) for profile in profiles)
    complete = sum(1 for profile in profiles if profile.get("complete") is True)
    result_metrics = {name: _serialize_metric(raw) for name, raw in sorted(metrics.items())}
    return {
        "schema": "hypersmart.research_lab_stream_profile.v2",
        "root": str(resolved),
        "read_only": True,
        "raw_event_values_exported": False,
        "file_count": len(profiles),
        "complete_file_count": complete,
        "partial_file_count": len(profiles) - complete,
        "source_bytes": total_source_bytes,
        "source_gib": _gib(total_source_bytes),
        "scanned_bytes": total_physical_bytes,
        "scanned_gib": _gib(total_physical_bytes),
        "logical_scanned_bytes": total_logical_bytes,
        "logical_scanned_gib": _gib(total_logical_bytes),
        "progress_basis": "physical_source_bytes",
        "lines": sum(int(profile.get("lines") or 0) for profile in profiles),
        "valid_json": sum(int(profile.get("valid_json") or 0) for profile in profiles),
        "invalid_json": sum(int(profile.get("invalid_json") or 0) for profile in profiles),
        "family_counts": dict(family_counts.most_common(200)),
        "event_counts": dict(event_counts.most_common(200)),
        "coin_counts": dict(coin_counts.most_common(200)),
        "metrics": result_metrics,
        "files": profiles,
    }


def write_research_stream_profile_safe(
    root: str | Path,
    *,
    resume: bool = True,
    max_files: int = 0,
    max_bytes_per_file: int = 0,
    max_lines_per_file: int = 0,
    sample_every: int = 100_000,
    heartbeat_seconds: float = 5.0,
) -> tuple[Path, Path, dict[str, Any]]:
    resolved = Path(root).resolve()
    profile = profile_research_workspace_safe(
        resolved,
        resume=resume,
        max_files=max_files,
        max_bytes_per_file=max_bytes_per_file,
        max_lines_per_file=max_lines_per_file,
        sample_every=sample_every,
        heartbeat_seconds=heartbeat_seconds,
    )
    json_path = resolved / REPORT_JSON
    md_path = resolved / REPORT_MD
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown = render_research_markdown(profile)
    markdown += (
        "\n## Sémantique de progression\n\n"
        "- Pour un JSONL normal, octets physiques et logiques sont identiques.\n"
        "- Pour un `.jsonl.gz`, le pourcentage et l'ETA utilisent uniquement les octets compressés réellement lus.\n"
        "- `logical_scanned_gib` mesure séparément le volume décompressé traité et peut dépasser la taille du fichier `.gz`.\n"
        "- Les `.gz` ne sont pas déclarés reprenables par offset; les JSONL non compressés gardent leurs checkpoints.\n"
    )
    md_path.write_text(markdown, encoding="utf-8")
    return json_path, md_path, profile


__all__ = [
    "profile_research_jsonl_safe",
    "profile_research_workspace_safe",
    "write_research_stream_profile_safe",
]
