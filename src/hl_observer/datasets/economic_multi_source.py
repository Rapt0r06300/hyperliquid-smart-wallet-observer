from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from hl_observer.datasets.source_discovery import (
    FAMILY_SOURCE_MANIFEST,
    is_dataset_workspace,
    load_family_source_paths,
)

_COPY_BASENAMES = (
    "vault_fills.jsonl",
    "vault_fills_live.jsonl",
    "vault_ledger.jsonl",
    "vault_episodes.jsonl",
    "vault_snapshots.jsonl",
    "copy_vault_l2_tape.jsonl",
    "carnet_venues.jsonl",
)


def _selection_token(root: Path) -> str:
    provenance = root / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json"
    try:
        payload = json.loads(provenance.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    token = str(payload.get("selection_digest") or "").strip().casefold()
    if len(token) >= 16 and all(ch in "0123456789abcdef" for ch in token):
        return token[:16]
    return "workspace"


def _source_signature(paths: Iterable[Path]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted({Path(p).resolve() for p in paths}, key=lambda item: item.as_posix().casefold()):
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append(
            {
                "path": str(path),
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }
        )
    return rows


def _safe_relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _merge_jsonl(
    root: Path,
    paths: Iterable[Path],
    *,
    output_name: str,
) -> tuple[Path, dict[str, object]]:
    sources = [path for path in sorted(set(paths), key=lambda p: p.as_posix().casefold()) if path.is_file()]
    output_dir = (
        root
        / "runtime"
        / "reports"
        / "datasets"
        / "economic_inputs"
        / _selection_token(root)
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / output_name
    manifest = output.with_suffix(output.suffix + ".sources.json")
    signature = _source_signature(sources)
    try:
        old = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else None
    except (OSError, json.JSONDecodeError):
        old = None
    if output.is_file() and isinstance(old, dict) and old.get("sources") == signature:
        return output, {
            **old,
            "reused": True,
            "output": _safe_relative(root, output),
        }

    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    seen: set[bytes] = set()
    lines_read = 0
    lines_written = 0
    duplicates = 0
    with temporary.open("wb") as target:
        for source in sources:
            try:
                handle = source.open("rb")
            except OSError:
                continue
            with handle:
                for raw in handle:
                    lines_read += 1
                    line = raw.strip()
                    if not line:
                        continue
                    digest = hashlib.sha256(line).digest()
                    if digest in seen:
                        duplicates += 1
                        continue
                    seen.add(digest)
                    target.write(line + b"\n")
                    lines_written += 1
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, output)
    payload: dict[str, object] = {
        "schema": "hypersmart.dataset_merged_jsonl.v1",
        "sources": signature,
        "source_count": len(signature),
        "lines_read": lines_read,
        "lines_written": lines_written,
        "duplicate_lines_rejected": duplicates,
        "output": _safe_relative(root, output),
        "output_bytes": output.stat().st_size,
        "reused": False,
    }
    manifest.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output, payload


def _paths_by_basename(paths: Iterable[Path]) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for path in paths:
        name = path.name.casefold()
        result.setdefault(name, []).append(path)
    return result


def build_copy_vault_input_view(root: str | Path) -> dict[str, object]:
    resolved = Path(root).resolve()
    if not is_dataset_workspace(resolved):
        return {"enabled": False, "reason": "NOT_A_DATASET_WORKSPACE"}

    copy_sources = load_family_source_paths(resolved, "copy_vault")
    # carnet_venues is shared economic evidence: Cross-Venue owns the source,
    # Copy-Vault consumes the Hyperliquid book side as historical audit material.
    cross_sources = [
        path
        for path in load_family_source_paths(resolved, "cross_venue")
        if path.name.casefold() == "carnet_venues.jsonl"
    ]
    grouped = _paths_by_basename([*copy_sources, *cross_sources])
    merged: dict[str, dict[str, object]] = {}
    outputs: dict[str, str] = {}
    for basename in _COPY_BASENAMES:
        sources = grouped.get(basename.casefold(), [])
        if not sources:
            continue
        output, meta = _merge_jsonl(resolved, sources, output_name=basename)
        merged[basename] = meta
        outputs[basename] = _safe_relative(resolved, output)
    return {
        "enabled": True,
        "source_manifest": _safe_relative(resolved, resolved / FAMILY_SOURCE_MANIFEST),
        "discovered_source_count": len(set([*copy_sources, *cross_sources])),
        "outputs": outputs,
        "merges": merged,
    }


def install_copy_vault_adapter(
    root: str | Path,
    *,
    copy_tool: Any,
    copy_executable: Any,
) -> dict[str, object]:
    resolved = Path(root).resolve()
    view = build_copy_vault_input_view(resolved)
    if view.get("enabled") is not True:
        return view
    outputs = view.get("outputs") if isinstance(view.get("outputs"), dict) else {}
    constant_map = {
        "FILLS": "vault_fills.jsonl",
        "FILLS_LIVE": "vault_fills_live.jsonl",
        "LEDGER": "vault_ledger.jsonl",
        "EPISODES": "vault_episodes.jsonl",
        "SNAP": "vault_snapshots.jsonl",
    }
    patched_constants: dict[str, str] = {}
    for constant, basename in constant_map.items():
        relative = outputs.get(basename)
        if isinstance(relative, str) and relative:
            setattr(copy_tool, constant, Path(relative))
            patched_constants[constant] = relative

    original_loader = copy_executable.load_observed_books
    historical = outputs.get("carnet_venues.jsonl")
    causal = outputs.get("copy_vault_l2_tape.jsonl")
    if isinstance(historical, str) or isinstance(causal, str):
        historical_relative = (
            historical if isinstance(historical, str) else "runtime/data/carnet_venues.jsonl"
        )
        causal_relative = (
            causal if isinstance(causal, str) else "runtime/data/copy_vault_l2_tape.jsonl"
        )

        def dataset_book_loader(root_value, *, coins=None):
            return original_loader(
                root_value,
                coins=coins,
                relative_path=historical_relative,
                causal_relative_path=causal_relative,
            )

        copy_executable.load_observed_books = dataset_book_loader
    return {
        **view,
        "patched_constants": patched_constants,
        "book_loader_patched": bool(isinstance(historical, str) or isinstance(causal, str)),
    }


def load_cross_venue_multi_source(
    root: str | Path,
    *,
    coins: tuple[str, ...] | None = None,
) -> tuple[dict[str, list[tuple]], dict[str, list[tuple[float, float]]], dict[str, object]]:
    resolved = Path(root).resolve()
    sources = [
        path
        for path in load_family_source_paths(resolved, "cross_venue")
        if path.name.casefold() == "carnet_venues.jsonl"
    ]
    allowed = {coin.upper() for coin in coins} if coins else None
    values: dict[tuple[str, float], tuple[float, float, float, float, float]] = {}
    conflicted: set[tuple[str, float]] = set()
    lines_read = invalid = duplicates = conflicts = 0
    for source in sources:
        try:
            handle = source.open("r", encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with handle:
            for line in handle:
                lines_read += 1
                try:
                    row = json.loads(line)
                    coin = str(row["coin"]).upper()
                    if allowed is not None and coin not in allowed:
                        continue
                    timestamp = float(row["collecte_ts"])
                    timestamp_ms = timestamp * 1000.0 if timestamp < 10_000_000_000 else timestamp
                    observed = (
                        float(row["hl_bid"]),
                        float(row["hl_ask"]),
                        float(row["bin_bid"]),
                        float(row["bin_ask"]),
                        float(row["taille_min_usd"]),
                    )
                    if not (
                        timestamp_ms > 0
                        and 0 < observed[0] <= observed[1]
                        and 0 < observed[2] <= observed[3]
                        and observed[4] > 0
                    ):
                        raise ValueError
                except (KeyError, TypeError, ValueError, OverflowError, json.JSONDecodeError):
                    invalid += 1
                    continue
                key = (coin, timestamp_ms)
                if key in conflicted:
                    continue
                previous = values.get(key)
                if previous is None:
                    values[key] = observed
                elif previous == observed:
                    duplicates += 1
                else:
                    conflicts += 1
                    conflicted.add(key)
                    values.pop(key, None)

    series: dict[str, list[tuple]] = {}
    depth: dict[str, list[tuple[float, float]]] = {}
    first_ms = last_ms = None
    for (coin, timestamp_ms), observed in sorted(values.items(), key=lambda item: item[0][1]):
        hl_bid, hl_ask, bin_bid, bin_ask, capacity = observed
        series.setdefault(coin, []).append(
            (timestamp_ms, "ATOMIC", hl_bid, hl_ask, bin_bid, bin_ask)
        )
        depth.setdefault(coin, []).append((timestamp_ms, capacity))
        first_ms = timestamp_ms if first_ms is None else min(first_ms, timestamp_ms)
        last_ms = timestamp_ms if last_ms is None else max(last_ms, timestamp_ms)
    return series, depth, {
        "sources": [_safe_relative(resolved, path) for path in sources],
        "source_count": len(sources),
        "source_mode": "FULL_COLD_MULTI_SOURCE_ATOMIC_FOUR_SIDE_BOOK",
        "lines_read": lines_read,
        "valid_snapshots": len(values),
        "invalid_rows": invalid,
        "duplicates_rejected": duplicates,
        "conflicting_same_timestamp_rejected": conflicts,
        "conflicting_keys": len(conflicted),
        "coins": len(series),
        "first_observed_ms": first_ms,
        "last_observed_ms": last_ms,
        "stopped_reason": "COMPLETED",
    }


def install_cross_venue_adapter(root: str | Path, *, cross_tool: Any) -> dict[str, object]:
    resolved = Path(root).resolve()
    if not is_dataset_workspace(resolved):
        return {"enabled": False, "reason": "NOT_A_DATASET_WORKSPACE"}
    sources = load_family_source_paths(resolved, "cross_venue")
    original = cross_tool.collecter_carnet_series

    def dataset_collecter(root_value, *, coins=None):
        selected_sources = load_family_source_paths(root_value, "cross_venue")
        if not selected_sources:
            return original(root_value, coins=coins)
        return load_cross_venue_multi_source(root_value, coins=coins)

    cross_tool.collecter_carnet_series = dataset_collecter
    return {
        "enabled": True,
        "discovered_source_count": len(sources),
        "sources": [_safe_relative(resolved, path) for path in sources],
        "collector_patched": True,
    }


def _family_coverage(discovered: list[Path], consumed: list[Path]) -> dict[str, object]:
    discovered_set = {path.resolve() for path in discovered if path.is_file()}
    consumed_set = {path.resolve() for path in consumed if path.is_file()}
    discovered_bytes = sum(path.stat().st_size for path in discovered_set)
    consumed_bytes = sum(path.stat().st_size for path in consumed_set if path in discovered_set)
    file_coverage = (
        len(consumed_set & discovered_set) / len(discovered_set) if discovered_set else 1.0
    )
    byte_coverage = consumed_bytes / discovered_bytes if discovered_bytes else 1.0
    status = "FULL" if file_coverage == 1.0 else ("NONE" if file_coverage == 0 else "PARTIAL")
    return {
        "discovered_files": len(discovered_set),
        "consumed_files": len(consumed_set & discovered_set),
        "discovered_bytes": discovered_bytes,
        "consumed_bytes": consumed_bytes,
        "file_coverage_pct": round(file_coverage * 100.0, 4),
        "byte_coverage_pct": round(byte_coverage * 100.0, 4),
        "status": status,
    }


def write_economic_source_coverage(
    root: str | Path,
    *,
    copy_consumed: Iterable[Path],
    lead_consumed: Iterable[Path],
    cross_consumed: Iterable[Path],
) -> tuple[Path, Path, dict[str, object]]:
    resolved = Path(root).resolve()
    copy_discovered = load_family_source_paths(resolved, "copy_vault")
    cross_discovered = load_family_source_paths(resolved, "cross_venue")
    # carnet_venues is a shared book source for Copy-Vault.
    copy_discovered_union = sorted(
        set([*copy_discovered, *[p for p in cross_discovered if p.name.casefold() == "carnet_venues.jsonl"]]),
        key=lambda path: path.as_posix().casefold(),
    )
    families = {
        "copy_vault": _family_coverage(copy_discovered_union, list(copy_consumed)),
        "lead_lag": _family_coverage(
            load_family_source_paths(resolved, "lead_lag"), list(lead_consumed)
        ),
        "cross_venue": _family_coverage(cross_discovered, list(cross_consumed)),
    }
    payload: dict[str, object] = {
        "schema": "hypersmart.dataset_source_consumption_coverage.v1",
        "dataset_workspace": is_dataset_workspace(resolved),
        "source_release_id": 371149058,
        "families": families,
        "all_families_full": all(row["status"] == "FULL" for row in families.values()),
    }
    report_dir = resolved / "runtime" / "reports" / "datasets"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "SOURCE_CONSUMPTION_COVERAGE.json"
    md_path = report_dir / "SOURCE_CONSUMPTION_COVERAGE.md"
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Couverture des sources FULL/COLD réellement consommées",
        "",
        "| Famille | Fichiers découverts | Fichiers consommés | Couverture fichiers | Couverture octets | Statut |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for family, row in families.items():
        lines.append(
            f"| {family} | {row['discovered_files']} | {row['consumed_files']} | "
            f"{row['file_coverage_pct']:.2f}% | {row['byte_coverage_pct']:.2f}% | {row['status']} |"
        )
    lines.extend(
        [
            "",
            "`FULL` signifie que chaque fichier compatible découvert pour cette famille est inclus dans la vue ou la liste réellement donnée au moteur.",
            "Une couverture complète ne prouve pas une stratégie rentable : elle prouve seulement que les sources compatibles ne sont pas oubliées.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path, payload
