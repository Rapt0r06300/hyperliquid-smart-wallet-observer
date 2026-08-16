from __future__ import annotations

import gzip
import hashlib
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Mapping

from hl_observer.datasets.source_discovery import load_family_source_paths

REPORT_JSON = Path("runtime") / "reports" / "datasets" / "RESEARCH_LAB_STREAM_PROFILE.json"
REPORT_MD = Path("runtime") / "reports" / "datasets" / "RESEARCH_LAB_STREAM_PROFILE.md"
CHECKPOINT_DIR = Path("runtime") / "reports" / "datasets" / "research_lab_checkpoints"

TIMESTAMP_KEYS = (
    "ts_ms",
    "timestamp_ms",
    "time_ms",
    "exchange_ts",
    "created_at_ms",
    "observed_at_ms",
    "received_at_ms",
    "ts",
    "time",
    "timestamp",
)
FAMILY_KEYS = ("family", "strategy_family", "signal_family", "strategy", "engine", "module")
EVENT_KEYS = ("event_type", "type", "action", "decision", "status", "reason")
COIN_KEYS = ("coin", "symbol", "asset")
NESTED_METRIC_CONTAINERS = ("metrics", "summary", "trade", "result", "objective", "costs")
METRIC_KEYS = (
    "net_pnl_usd",
    "net_usd",
    "pnl_usd",
    "closed_pnl",
    "closedPnl",
    "gross_pnl_usd",
    "gross_usd",
    "fees_usd",
    "fee_usd",
    "spread_cost_usd",
    "slippage_cost_usd",
    "latency_cost_usd",
    "drawdown_usd",
    "max_drawdown_usd",
    "roi_pct",
    "edge_remaining_bps",
    "net_bps",
    "gross_bps",
    "profit_factor",
)


def _gib(value: int | float) -> float:
    return round(float(value) / (1024**3), 4)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _source_signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _checkpoint_name(relative_path: str) -> str:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:24]
    stem = Path(relative_path).name.replace(".", "_")[:80]
    return f"{stem}_{digest}.json"


def _bounded_increment(counter: Counter[str], value: object, *, max_keys: int = 2000) -> None:
    text = str(value or "").strip()
    if not text:
        return
    if len(text) > 160:
        text = text[:157] + "..."
    counter[text] += 1
    if len(counter) > max_keys:
        keep = counter.most_common(max(100, max_keys // 2))
        counter.clear()
        counter.update(dict(keep))


def _numeric(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _normalize_timestamp_ms(value: object) -> int | None:
    parsed = _numeric(value)
    if parsed is None or parsed <= 0:
        return None
    # Normalize common seconds/ms/us/ns epochs. Reject values outside a broad modern range.
    if parsed >= 1e17:
        parsed /= 1e6
    elif parsed >= 1e14:
        parsed /= 1e3
    elif parsed < 1e11:
        parsed *= 1e3
    timestamp_ms = int(parsed)
    lower = int(datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    upper = int(datetime(2100, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    return timestamp_ms if lower <= timestamp_ms <= upper else None


def _timestamp_from_row(row: Mapping[str, Any]) -> int | None:
    for key in TIMESTAMP_KEYS:
        if key not in row:
            continue
        normalized = _normalize_timestamp_ms(row.get(key))
        if normalized is not None:
            return normalized
    for container_name in ("event", "data", "trade", "signal"):
        nested = row.get(container_name)
        if isinstance(nested, Mapping):
            for key in TIMESTAMP_KEYS:
                normalized = _normalize_timestamp_ms(nested.get(key))
                if normalized is not None:
                    return normalized
    return None


def _first_value(row: Mapping[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    for container_name in ("event", "data", "trade", "signal", "metrics"):
        nested = row.get(container_name)
        if not isinstance(nested, Mapping):
            continue
        for key in keys:
            value = nested.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _metric_candidates(row: Mapping[str, Any]) -> Iterable[tuple[str, object]]:
    for key in METRIC_KEYS:
        if key in row:
            yield key, row.get(key)
    for container_name in NESTED_METRIC_CONTAINERS:
        nested = row.get(container_name)
        if not isinstance(nested, Mapping):
            continue
        for key in METRIC_KEYS:
            if key in nested:
                yield key, nested.get(key)


def _metric_state() -> dict[str, float | int | None]:
    return {
        "count": 0,
        "sum": 0.0,
        "min": None,
        "max": None,
        "positive": 0,
        "negative": 0,
        "zero": 0,
    }


def _metric_add(state: dict[str, float | int | None], value: float) -> None:
    state["count"] = int(state["count"] or 0) + 1
    state["sum"] = float(state["sum"] or 0.0) + value
    state["min"] = value if state["min"] is None else min(float(state["min"]), value)
    state["max"] = value if state["max"] is None else max(float(state["max"]), value)
    if value > 0:
        state["positive"] = int(state["positive"] or 0) + 1
    elif value < 0:
        state["negative"] = int(state["negative"] or 0) + 1
    else:
        state["zero"] = int(state["zero"] or 0) + 1


def _serialize_metric(state: Mapping[str, float | int | None]) -> dict[str, Any]:
    count = int(state.get("count") or 0)
    total = float(state.get("sum") or 0.0)
    return {
        "count": count,
        "sum": round(total, 8),
        "mean": round(total / count, 8) if count else None,
        "min": state.get("min"),
        "max": state.get("max"),
        "positive": int(state.get("positive") or 0),
        "negative": int(state.get("negative") or 0),
        "zero": int(state.get("zero") or 0),
    }


def _new_state(relative: str, signature: Mapping[str, int]) -> dict[str, Any]:
    return {
        "schema": "hypersmart.research_lab_checkpoint.v1",
        "relative_path": relative,
        "source_size": int(signature["size"]),
        "source_mtime_ns": int(signature["mtime_ns"]),
        "offset": 0,
        "lines": 0,
        "valid_json": 0,
        "invalid_json": 0,
        "object_rows": 0,
        "non_object_rows": 0,
        "timestamp_min_ms": None,
        "timestamp_max_ms": None,
        "key_counts": {},
        "family_counts": {},
        "event_counts": {},
        "coin_counts": {},
        "metrics": {},
        "samples": [],
        "complete": False,
    }


def _load_checkpoint(path: Path, *, relative: str, signature: Mapping[str, int]) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("relative_path") != relative:
        return None
    if int(payload.get("source_size") or -1) != int(signature["size"]):
        return None
    if int(payload.get("source_mtime_ns") or -1) != int(signature["mtime_ns"]):
        return None
    return payload


def _save_checkpoint(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _open_source(path: Path) -> tuple[BinaryIO, bool]:
    if path.name.casefold().endswith(".gz"):
        return gzip.open(path, "rb"), False
    return path.open("rb"), True


def _counter_from(raw: object) -> Counter[str]:
    if not isinstance(raw, Mapping):
        return Counter()
    result: Counter[str] = Counter()
    for key, value in raw.items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def _metrics_from(raw: object) -> dict[str, dict[str, float | int | None]]:
    result: dict[str, dict[str, float | int | None]] = {}
    if not isinstance(raw, Mapping):
        return result
    for key, value in raw.items():
        if not isinstance(value, Mapping):
            continue
        state = _metric_state()
        for field in state:
            if field in value:
                state[field] = value[field]  # type: ignore[assignment]
        result[str(key)] = state
    return result


def profile_research_jsonl(
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
    resolved_root = Path(root).resolve()
    source = Path(path).resolve()
    relative = _relative(resolved_root, source)
    signature = _source_signature(source)
    checkpoint = resolved_root / CHECKPOINT_DIR / _checkpoint_name(relative)
    compressed = source.name.casefold().endswith(".gz")
    resumable = not compressed
    saved = _load_checkpoint(checkpoint, relative=relative, signature=signature) if resume and resumable else None
    if saved and saved.get("complete") is True:
        return {**saved, "checkpoint": str(checkpoint), "resumed": True, "cached_complete": True}
    state = saved or _new_state(relative, signature)
    state["complete"] = False
    start_offset = int(state.get("offset") or 0) if resumable else 0
    key_counts = _counter_from(state.get("key_counts"))
    family_counts = _counter_from(state.get("family_counts"))
    event_counts = _counter_from(state.get("event_counts"))
    coin_counts = _counter_from(state.get("coin_counts"))
    metrics = _metrics_from(state.get("metrics"))
    samples = list(state.get("samples") or []) if isinstance(state.get("samples"), list) else []
    started = time.monotonic()
    last_heartbeat = started
    last_checkpoint = started
    bytes_at_start = start_offset
    stop_reason = "EOF"

    handle, seek_supported = _open_source(source)
    try:
        if seek_supported and start_offset > 0:
            handle.seek(start_offset)
        elif start_offset > 0:
            start_offset = 0
            state = _new_state(relative, signature)
        while True:
            before = int(handle.tell())
            raw_line = handle.readline()
            if not raw_line:
                state["complete"] = True
                stop_reason = "EOF"
                break
            after = int(handle.tell())
            state["offset"] = after
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
                family = _first_value(parsed, FAMILY_KEYS)
                event = _first_value(parsed, EVENT_KEYS)
                coin = _first_value(parsed, COIN_KEYS)
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
                    value = _numeric(raw_value)
                    if value is None:
                        continue
                    metric_state = metrics.setdefault(metric_name, _metric_state())
                    _metric_add(metric_state, value)
                line_number = int(state["lines"])
                if sample_every > 0 and line_number % sample_every == 0 and len(samples) < sample_limit:
                    samples.append(
                        {
                            "line": line_number,
                            "offset": before,
                            "timestamp_ms": ts_ms,
                            "family": family,
                            "event": event,
                            "coin": coin,
                        }
                    )
            elif parsed is not None:
                state["non_object_rows"] = int(state.get("non_object_rows") or 0) + 1

            processed_this_run = max(0, int(state["offset"]) - bytes_at_start)
            if max_bytes > 0 and processed_this_run >= max_bytes:
                stop_reason = "MAX_BYTES"
                break
            if max_lines > 0 and int(state["lines"]) >= max_lines:
                stop_reason = "MAX_LINES"
                break

            now = time.monotonic()
            if now - last_heartbeat >= max(0.2, heartbeat_seconds):
                elapsed = max(0.001, now - started)
                processed = max(0, int(state["offset"]) - bytes_at_start)
                speed = processed / elapsed
                total_size = int(signature["size"])
                offset = int(state["offset"])
                percent = (offset / total_size * 100.0) if total_size else 100.0
                remaining = max(0, total_size - offset)
                eta = remaining / speed if speed > 0 else None
                eta_text = "?" if eta is None else f"{eta:.0f}s"
                print(
                    f"[RESEARCH-LAB] {relative} {percent:6.2f}% "
                    f"lignes={state['lines']} invalides={state['invalid_json']} "
                    f"vitesse={speed / (1024**2):.2f} MiB/s ETA={eta_text}",
                    flush=True,
                )
                last_heartbeat = now
            if resume and resumable and now - last_checkpoint >= max(1.0, checkpoint_seconds):
                state["key_counts"] = dict(key_counts)
                state["family_counts"] = dict(family_counts)
                state["event_counts"] = dict(event_counts)
                state["coin_counts"] = dict(coin_counts)
                state["metrics"] = {name: dict(value) for name, value in metrics.items()}
                state["samples"] = samples
                state["stop_reason"] = "CHECKPOINT"
                _save_checkpoint(checkpoint, state)
                last_checkpoint = now
    finally:
        handle.close()

    state["key_counts"] = dict(key_counts.most_common(500))
    state["family_counts"] = dict(family_counts.most_common(500))
    state["event_counts"] = dict(event_counts.most_common(500))
    state["coin_counts"] = dict(coin_counts.most_common(500))
    state["metrics"] = {name: _serialize_metric(value) for name, value in sorted(metrics.items())}
    state["samples"] = samples
    state["stop_reason"] = stop_reason
    state["compressed"] = compressed
    state["resume_supported"] = resumable
    state["resumed"] = saved is not None
    state["cached_complete"] = False
    state["checkpoint"] = str(checkpoint)
    state["scanned_bytes"] = int(state.get("offset") or 0)
    state["scanned_gib"] = _gib(int(state.get("offset") or 0))
    if resume and resumable:
        _save_checkpoint(checkpoint, state)
    return state


def discover_research_jsonl(root: str | Path) -> list[Path]:
    resolved = Path(root).resolve()
    candidates = load_family_source_paths(resolved, "research_lab")
    result = [
        path
        for path in candidates
        if path.name.casefold().endswith((".jsonl", ".jsonl.gz"))
    ]
    # Biggest first: the expensive evidence becomes visible immediately and progress is meaningful.
    def key(path: Path) -> tuple[int, str]:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return (-size, path.as_posix().casefold())

    return sorted(set(result), key=key)


def _merge_metric_aggregate(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    source_count = int(source.get("count") or 0)
    if source_count <= 0:
        return
    target_count = int(target.get("count") or 0)
    target["count"] = target_count + source_count
    target["sum"] = float(target.get("sum") or 0.0) + float(source.get("sum") or 0.0)
    source_min = source.get("min")
    source_max = source.get("max")
    if source_min is not None:
        target["min"] = source_min if target.get("min") is None else min(float(target["min"]), float(source_min))
    if source_max is not None:
        target["max"] = source_max if target.get("max") is None else max(float(target["max"]), float(source_max))
    for key in ("positive", "negative", "zero"):
        target[key] = int(target.get(key) or 0) + int(source.get(key) or 0)


def profile_research_workspace(
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
        profile = profile_research_jsonl(
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
    total_scanned_bytes = sum(int(profile.get("scanned_bytes") or 0) for profile in profiles)
    complete = sum(1 for profile in profiles if profile.get("complete") is True)
    result_metrics: dict[str, Any] = {}
    for name, raw in sorted(metrics.items()):
        result_metrics[name] = _serialize_metric(raw)
    return {
        "schema": "hypersmart.research_lab_stream_profile.v1",
        "root": str(resolved),
        "read_only": True,
        "raw_event_values_exported": False,
        "file_count": len(profiles),
        "complete_file_count": complete,
        "partial_file_count": len(profiles) - complete,
        "source_bytes": total_source_bytes,
        "source_gib": _gib(total_source_bytes),
        "scanned_bytes": total_scanned_bytes,
        "scanned_gib": _gib(total_scanned_bytes),
        "lines": sum(int(profile.get("lines") or 0) for profile in profiles),
        "valid_json": sum(int(profile.get("valid_json") or 0) for profile in profiles),
        "invalid_json": sum(int(profile.get("invalid_json") or 0) for profile in profiles),
        "family_counts": dict(family_counts.most_common(200)),
        "event_counts": dict(event_counts.most_common(200)),
        "coin_counts": dict(coin_counts.most_common(200)),
        "metrics": result_metrics,
        "files": profiles,
    }


def render_research_markdown(profile: Mapping[str, Any]) -> str:
    lines = [
        "# Profil streaming du Research Lab FULL/COLD",
        "",
        "- Lecture séquentielle locale, sans réseau et sans mutation des sources.",
        "- Les gros JSONL non compressés sont reprenables depuis leur dernier offset validé.",
        "- Le rapport garde des compteurs, métriques agrégées et échantillons de métadonnées; il n'exporte pas les lignes brutes.",
        f"- Fichiers profilés : **{profile.get('file_count', 0)}**.",
        f"- Volume source profilé : **{profile.get('source_gib', 0)} Gio**.",
        f"- Volume déjà parcouru : **{profile.get('scanned_gib', 0)} Gio**.",
        f"- Lignes : **{profile.get('lines', 0)}** dont **{profile.get('invalid_json', 0)}** JSON invalides.",
        f"- Fichiers terminés : **{profile.get('complete_file_count', 0)}** ; partiels/reprenables : **{profile.get('partial_file_count', 0)}**.",
        "",
        "## Fichiers les plus lourds profilés",
        "",
        "| Fichier | Gio | Parcouru Gio | Lignes | État |",
        "|---|---:|---:|---:|---|",
    ]
    raw_files = profile.get("files")
    files = raw_files if isinstance(raw_files, list) else []
    for item in files[:50]:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"| `{item.get('relative_path')}` | {_gib(int(item.get('source_size') or 0))} | "
            f"{item.get('scanned_gib', 0)} | {item.get('lines', 0)} | "
            f"{'TERMINE' if item.get('complete') else item.get('stop_reason')} |"
        )
    lines.extend(["", "## Familles les plus fréquentes", "", "| Famille | Occurrences |", "|---|---:|"])
    families = profile.get("family_counts")
    if isinstance(families, Mapping):
        for name, count in list(families.items())[:50]:
            lines.append(f"| {name} | {count} |")
    lines.extend(["", "## Métriques économiques repérées", "", "| Métrique | N | Somme | Moyenne | Min | Max |", "|---|---:|---:|---:|---:|---:|"])
    metrics = profile.get("metrics")
    if isinstance(metrics, Mapping):
        for name, raw in metrics.items():
            if not isinstance(raw, Mapping):
                continue
            lines.append(
                f"| {name} | {raw.get('count', 0)} | {raw.get('sum')} | {raw.get('mean')} | "
                f"{raw.get('min')} | {raw.get('max')} |"
            )
    lines.extend(
        [
            "",
            "> Ces agrégats servent à cartographier les preuves déjà collectées. Ils ne constituent ni une validation OOS ni une preuve de PnL futur.",
            "",
        ]
    )
    return "\n".join(lines)


def write_research_stream_profile(
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
    profile = profile_research_workspace(
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
    md_path.write_text(render_research_markdown(profile), encoding="utf-8")
    return json_path, md_path, profile


__all__ = [
    "CHECKPOINT_DIR",
    "REPORT_JSON",
    "REPORT_MD",
    "discover_research_jsonl",
    "profile_research_jsonl",
    "profile_research_workspace",
    "render_research_markdown",
    "write_research_stream_profile",
]
