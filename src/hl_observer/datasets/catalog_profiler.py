from __future__ import annotations

import gzip
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

FAMILY_KEYWORDS = {
    "copy_vault": (
        "copy_vault",
        "copy-vault",
        "vault",
        "leader",
        "userfill",
        "metaorder",
        "twap",
    ),
    "lead_lag": (
        "lead_lag",
        "lead-lag",
        "allmids",
        "bbo",
        "trade",
        "microprice",
        "orderflow",
        "ofi",
    ),
    "cross_venue": (
        "cross_venue",
        "cross-venue",
        "carnet_venues",
        "venue",
        "binance",
        "dydx",
        "dislocation",
        "spread",
    ),
    "microstructure": (
        "l2",
        "book",
        "orderbook",
        "depth",
        "carnet",
        "bid",
        "ask",
    ),
    "research_lab": (
        "research_lab",
        "research-lab",
        "scenario",
        "replay",
        "backtest",
        "histor",
    ),
}


def _gib(value: int) -> float:
    return round(value / (1024**3), 4)


def _iso_from_ns(value: int | None) -> str | None:
    if not value or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _extension(path: str) -> str:
    suffix = Path(path).suffix.casefold()
    return suffix if suffix else "(sans_extension)"


def _bucket(path: str) -> str:
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    return "/".join(parts[:3]) if parts else "(racine)"


def _families(path: str) -> tuple[str, ...]:
    lowered = path.casefold()
    found = [
        name
        for name, keywords in FAMILY_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]
    return tuple(found) if found else ("autres",)


def profile_manifest(manifest_path: Path) -> dict[str, object]:
    extensions_count: Counter[str] = Counter()
    extensions_bytes: Counter[str] = Counter()
    buckets_count: Counter[str] = Counter()
    buckets_bytes: Counter[str] = Counter()
    families_count: Counter[str] = Counter()
    families_bytes: Counter[str] = Counter()
    largest: list[tuple[int, str]] = []
    total_files = 0
    total_bytes = 0
    min_mtime_ns: int | None = None
    max_mtime_ns: int | None = None

    with gzip.open(manifest_path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            raw = json.loads(line)
            if not isinstance(raw, Mapping):
                continue
            path = str(raw.get("relative_path") or "")
            if not path:
                continue
            size = int(raw.get("size") or 0)
            try:
                mtime_ns = int(raw.get("mtime_ns") or 0)
            except (TypeError, ValueError, OverflowError):
                mtime_ns = 0

            total_files += 1
            total_bytes += size
            extension = _extension(path)
            bucket = _bucket(path)
            extensions_count[extension] += 1
            extensions_bytes[extension] += size
            buckets_count[bucket] += 1
            buckets_bytes[bucket] += size
            for family in _families(path):
                families_count[family] += 1
                families_bytes[family] += size

            if mtime_ns > 0:
                min_mtime_ns = mtime_ns if min_mtime_ns is None else min(min_mtime_ns, mtime_ns)
                max_mtime_ns = mtime_ns if max_mtime_ns is None else max(max_mtime_ns, mtime_ns)

            largest.append((size, path))
            if len(largest) > 500:
                largest.sort(reverse=True)
                del largest[250:]

    largest.sort(reverse=True)
    return {
        "schema": "hypersmart.dataset_catalog.v1",
        "manifest": str(manifest_path),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_gib": _gib(total_bytes),
        "mtime_min_utc": _iso_from_ns(min_mtime_ns),
        "mtime_max_utc": _iso_from_ns(max_mtime_ns),
        "families": {
            name: {
                "files": families_count[name],
                "bytes": families_bytes[name],
                "gib": _gib(families_bytes[name]),
            }
            for name in sorted(families_count)
        },
        "extensions": [
            {
                "extension": name,
                "files": count,
                "bytes": extensions_bytes[name],
                "gib": _gib(extensions_bytes[name]),
            }
            for name, count in extensions_count.most_common()
        ],
        "top_folders": [
            {
                "folder": name,
                "files": count,
                "bytes": buckets_bytes[name],
                "gib": _gib(buckets_bytes[name]),
            }
            for name, count in buckets_count.most_common(200)
        ],
        "largest_files": [
            {"relative_path": path, "bytes": size, "gib": _gib(size)}
            for size, path in largest[:200]
        ],
    }


def render_markdown(profile: Mapping[str, object]) -> str:
    lines = [
        "# Carte des données HyperSmart",
        "",
        f"- Fichiers : **{profile.get('total_files', 0)}**",
        f"- Volume brut : **{profile.get('total_gib', 0)} Gio**",
        f"- Plus ancien mtime : `{profile.get('mtime_min_utc')}`",
        f"- Plus récent mtime : `{profile.get('mtime_max_utc')}`",
        "",
        "## Familles repérées par les chemins",
        "",
        "| Famille | Fichiers | Gio |",
        "|---|---:|---:|",
    ]
    families = profile.get("families")
    if isinstance(families, Mapping):
        for name, raw in families.items():
            if isinstance(raw, Mapping):
                lines.append(
                    f"| {name} | {raw.get('files', 0)} | {raw.get('gib', 0)} |"
                )

    lines.extend([
        "",
        "## Extensions principales",
        "",
        "| Extension | Fichiers | Gio |",
        "|---|---:|---:|",
    ])
    extensions = profile.get("extensions")
    if isinstance(extensions, list):
        for raw in extensions[:30]:
            if isinstance(raw, Mapping):
                lines.append(
                    f"| {raw.get('extension')} | {raw.get('files', 0)} | {raw.get('gib', 0)} |"
                )

    lines.extend([
        "",
        "## Gros dossiers",
        "",
        "| Dossier | Fichiers | Gio |",
        "|---|---:|---:|",
    ])
    folders = profile.get("top_folders")
    if isinstance(folders, list):
        for raw in folders[:50]:
            if isinstance(raw, Mapping):
                lines.append(
                    f"| `{raw.get('folder')}` | {raw.get('files', 0)} | {raw.get('gib', 0)} |"
                )
    lines.append("")
    lines.append(
        "> Cette carte ne supprime et ne trie rien. Elle sert seulement à savoir ce que nous possédons."
    )
    return "\n".join(lines) + "\n"
