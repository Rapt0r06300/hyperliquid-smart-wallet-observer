"""Fail-closed reader/materializer for Alina SmartFlow Dataset V2.

Only shards explicitly indexed as SAFE are eligible. Every downloaded release asset
is verified against the control-plane byte count and SHA-256 before it is exposed to
replay/backtest code.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import requests

DEFAULT_REPOSITORY = "Rapt0r06300/alina-smartflow-datasets-v2"
DEFAULT_REF = "main"
RAW_ROOT = "https://raw.githubusercontent.com"
API_ROOT = "https://api.github.com"
TIMEOUT = (20.0, 300.0)


class DatasetV2Error(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SafeShard:
    dataset_id: str
    family: str
    venue: str
    symbol: str
    start_ts_ms: int
    end_ts_ms: int
    sha256: str
    bytes: int
    event_count: int
    release_repository: str
    release_tag: str
    release_asset: str
    manifest_path: str

    @classmethod
    def from_index_row(cls, row: Mapping[str, Any]) -> "SafeShard":
        status = str(row.get("quality_status") or "").upper()
        if status != "SAFE":
            raise DatasetV2Error(f"non-SAFE shard refused: {status or 'MISSING'}")
        if row.get("replay_compatible") is not True:
            raise DatasetV2Error("SAFE shard is not explicitly replay compatible")
        required = (
            "dataset_id",
            "family",
            "venue",
            "symbol",
            "start_ts_ms",
            "end_ts_ms",
            "sha256",
            "bytes",
            "event_count",
            "release_repository",
            "release_tag",
            "release_asset",
            "manifest_path",
        )
        missing = [key for key in required if row.get(key) in {None, ""}]
        if missing:
            raise DatasetV2Error("SAFE index row missing: " + ",".join(missing))
        digest = str(row["sha256"]).lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise DatasetV2Error("invalid SAFE shard sha256")
        start = int(row["start_ts_ms"])
        end = int(row["end_ts_ms"])
        size = int(row["bytes"])
        events = int(row["event_count"])
        if start < 0 or end < start or size <= 0 or events <= 0:
            raise DatasetV2Error("invalid SAFE shard bounds")
        release_repo = str(row["release_repository"])
        if release_repo != DEFAULT_REPOSITORY:
            raise DatasetV2Error(f"foreign dataset repository refused: {release_repo}")
        return cls(
            dataset_id=str(row["dataset_id"]),
            family=str(row["family"]),
            venue=str(row["venue"]),
            symbol=str(row["symbol"]),
            start_ts_ms=start,
            end_ts_ms=end,
            sha256=digest,
            bytes=size,
            event_count=events,
            release_repository=release_repo,
            release_tag=str(row["release_tag"]),
            release_asset=str(row["release_asset"]),
            manifest_path=str(row["manifest_path"]),
        )


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Alina-SmartFlow-Dataset-V2",
    }
    token = str(os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_index(
    *,
    repository: str = DEFAULT_REPOSITORY,
    ref: str = DEFAULT_REF,
) -> tuple[dict[str, Any], str]:
    url = f"{RAW_ROOT}/{repository}/{ref}/catalog/DATA_INDEX.json"
    response = requests.get(url, timeout=TIMEOUT)
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DatasetV2Error(f"unable to load V2 index: {type(exc).__name__}") from exc
    raw = response.content
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetV2Error("V2 index is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "alina.data_index.v2":
        raise DatasetV2Error("unexpected V2 index schema")
    return payload, hashlib.sha256(raw).hexdigest()


def select_safe_shards(
    index: Mapping[str, Any],
    *,
    families: Iterable[str] = (),
    venues: Iterable[str] = (),
    symbols: Iterable[str] = (),
    start_ts_ms: int | None = None,
    end_ts_ms: int | None = None,
) -> list[SafeShard]:
    family_set = {str(v).lower() for v in families if str(v)}
    venue_set = {str(v).lower() for v in venues if str(v)}
    symbol_set = {str(v).upper() for v in symbols if str(v)}
    rows = index.get("shards")
    if not isinstance(rows, list):
        raise DatasetV2Error("V2 index shards must be a list")
    selected: list[SafeShard] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("quality_status") or "").upper() != "SAFE":
            continue
        if raw.get("replay_compatible") is not True:
            continue
        shard = SafeShard.from_index_row(raw)
        if family_set and shard.family.lower() not in family_set:
            continue
        if venue_set and shard.venue.lower() not in venue_set:
            continue
        if symbol_set and shard.symbol.upper() not in symbol_set:
            continue
        if start_ts_ms is not None and shard.end_ts_ms < int(start_ts_ms):
            continue
        if end_ts_ms is not None and shard.start_ts_ms > int(end_ts_ms):
            continue
        selected.append(shard)
    return sorted(
        selected,
        key=lambda item: (
            item.start_ts_ms,
            item.venue,
            item.family,
            item.symbol,
            item.dataset_id,
        ),
    )


def _release_asset_url(shard: SafeShard) -> str:
    url = (
        f"{API_ROOT}/repos/{shard.release_repository}/releases/tags/"
        f"{shard.release_tag}"
    )
    response = requests.get(url, headers=_headers(), timeout=TIMEOUT)
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DatasetV2Error(
            f"release lookup failed for {shard.release_tag}: {type(exc).__name__}"
        ) from exc
    payload = response.json()
    assets = payload.get("assets") if isinstance(payload, dict) else None
    if not isinstance(assets, list):
        raise DatasetV2Error("release assets missing")
    matches = [
        row for row in assets
        if isinstance(row, Mapping) and str(row.get("name") or "") == shard.release_asset
    ]
    if len(matches) != 1:
        raise DatasetV2Error(
            f"release asset resolution is not unique for {shard.release_asset}"
        )
    url = str(matches[0].get("browser_download_url") or "")
    if not url.startswith("https://"):
        raise DatasetV2Error("release asset download URL missing")
    return url


def download_safe_shard(
    shard: SafeShard,
    destination: str | Path,
    *,
    force: bool = False,
) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and not force:
        if path.stat().st_size == shard.bytes and _sha256(path) == shard.sha256:
            return path
        path.unlink(missing_ok=True)

    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    url = _release_asset_url(shard)
    try:
        with requests.get(
            url,
            headers=_headers(),
            timeout=TIMEOUT,
            stream=True,
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
                    if chunk:
                        handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
    except (requests.RequestException, OSError) as exc:
        temporary.unlink(missing_ok=True)
        raise DatasetV2Error(
            f"SAFE shard download failed: {type(exc).__name__}"
        ) from exc

    if temporary.stat().st_size != shard.bytes:
        temporary.unlink(missing_ok=True)
        raise DatasetV2Error("SAFE shard size mismatch")
    if _sha256(temporary) != shard.sha256:
        temporary.unlink(missing_ok=True)
        raise DatasetV2Error("SAFE shard SHA-256 mismatch")
    temporary.replace(path)
    return path


def materialize_safe_shards(
    shards: Iterable[SafeShard],
    output_root: str | Path,
    *,
    index_sha256: str,
) -> dict[str, Any]:
    root = Path(output_root).resolve()
    data_root = root / "runtime" / "data" / "market_ticks"
    created: list[str] = []
    rows = list(shards)
    for shard in rows:
        destination = (
            data_root
            / shard.venue
            / shard.family
            / shard.symbol
            / shard.release_asset
        )
        download_safe_shard(shard, destination)
        created.append(str(destination.relative_to(root)).replace("\\", "/"))

    report_dir = root / "runtime" / "reports" / "datasets"
    report_dir.mkdir(parents=True, exist_ok=True)
    provenance = {
        "schema": "alina.dataset_v2_selection_provenance.v1",
        "source_repository": DEFAULT_REPOSITORY,
        "source_ref": DEFAULT_REF,
        "source_index_sha256": index_sha256,
        "quality_status_required": "SAFE",
        "selected_shards": len(rows),
        "selected_events": sum(item.event_count for item in rows),
        "selected_bytes": sum(item.bytes for item in rows),
        "created_paths": created,
        "paper_only": True,
        "real_execution": False,
        "legacy_import": False,
    }
    path = report_dir / "SELECTION_PROVENANCE.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return provenance


__all__ = [
    "DEFAULT_REF",
    "DEFAULT_REPOSITORY",
    "DatasetV2Error",
    "SafeShard",
    "download_safe_shard",
    "load_index",
    "materialize_safe_shards",
    "select_safe_shards",
]