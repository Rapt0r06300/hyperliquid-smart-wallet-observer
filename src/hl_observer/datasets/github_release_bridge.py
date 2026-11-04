from __future__ import annotations

import gzip
import hashlib
import json
import math
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

DEFAULT_REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
DEFAULT_RELEASE_ID: int | None = None
LEGACY_REPOSITORY = "Rapt0r06300/hypersmart-datasets"
LEGACY_RELEASE_ID = 371149058
CORE_METADATA_ASSETS = (
    "FULL_UPLOADED_FILE_MANIFEST.jsonl.gz",
    "FULL_RELEASE_ASSET_MANIFEST.json",
    "FULL_SNAPSHOT_SUMMARY.json",
)
OPTIONAL_METADATA_ASSETS = (
    "DIRECTORY_MANIFEST.jsonl.gz",
    "RECONSTRUCT_FULL_SNAPSHOT.py",
    "RELEASE_NOTES.md",
)


class DatasetBridgeError(RuntimeError):
    """Controlled dataset bridge error."""


def _validated_source(repository: str, release_id: int | None) -> tuple[str, int]:
    repo = str(repository or "").strip()
    if repo.casefold() == LEGACY_REPOSITORY.casefold() or release_id == LEGACY_RELEASE_ID:
        raise DatasetBridgeError(
            "LEGACY_DATASET_BLOCKED: hypersmart-datasets/FULL-COLD cannot be used by Alina V2."
        )
    if repo != DEFAULT_REPOSITORY:
        raise DatasetBridgeError(
            f"UNAPPROVED_DATASET_REPOSITORY: {repo or '<empty>'}; expected {DEFAULT_REPOSITORY}"
        )
    if release_id is None or int(release_id) <= 0:
        raise DatasetBridgeError(
            "EXPLICIT_V2_RELEASE_REQUIRED: select a verified release from the Alina Smart Flow repository."
        )
    return repo, int(release_id)


@dataclass(frozen=True)
class ReleaseAsset:
    asset_id: int
    name: str
    size: int
    digest: str

    @property
    def sha256(self) -> str:
        prefix = "sha256:"
        return self.digest[len(prefix) :] if self.digest.startswith(prefix) else ""


@dataclass(frozen=True)
class DatasetRecord:
    relative_path: str
    size: int
    sha256: str
    storage: str
    asset: str | None = None
    chunks: tuple[Mapping[str, object], ...] = ()
    release_tag: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "DatasetRecord":
        raw_chunks = raw.get("chunks")
        chunks: tuple[Mapping[str, object], ...] = ()
        if isinstance(raw_chunks, list):
            chunks = tuple(item for item in raw_chunks if isinstance(item, Mapping))
        return cls(
            relative_path=str(raw.get("relative_path") or ""),
            size=int(raw.get("size") or 0),
            sha256=str(raw.get("sha256") or ""),
            storage=str(raw.get("storage") or ""),
            asset=str(raw.get("asset")) if raw.get("asset") else None,
            chunks=chunks,
            release_tag=str(raw.get("release_tag")) if raw.get("release_tag") else None,
        )

    def needed_assets(self) -> tuple[str, ...]:
        if self.storage == "zip_entry":
            return (self.asset,) if self.asset else ()
        if self.storage == "raw_chunks":
            names: list[str] = []
            for chunk in self.chunks:
                name = str(chunk.get("asset") or "")
                if name:
                    names.append(name)
            return tuple(names)
        return ()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _gh_path() -> str:
    gh = shutil.which("gh")
    if not gh:
        raise DatasetBridgeError(
            "GitHub CLI (gh) est introuvable. Le pont ne télécharge rien sans outil GitHub authentifié."
        )
    return gh


def _run_gh_text(arguments: Sequence[str]) -> str:
    process = subprocess.run(
        [_gh_path(), *arguments],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()
        raise DatasetBridgeError(
            f"GitHub a refusé la commande ({process.returncode}): {detail}"
        )
    return process.stdout


def load_release(
    repository: str = DEFAULT_REPOSITORY,
    release_id: int | None = DEFAULT_RELEASE_ID,
) -> dict[str, object]:
    repository, release_id = _validated_source(repository, release_id)
    raw = _run_gh_text(["api", f"repos/{repository}/releases/{release_id}"])
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise DatasetBridgeError("Réponse GitHub invalide pour la Release HyperSmart.")
    return payload


def release_assets(release: Mapping[str, object]) -> dict[str, ReleaseAsset]:
    result: dict[str, ReleaseAsset] = {}
    raw_assets = release.get("assets")
    if not isinstance(raw_assets, list):
        return result
    for raw in raw_assets:
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("name") or "")
        if not name:
            continue
        result[name] = ReleaseAsset(
            asset_id=int(raw.get("id") or 0),
            name=name,
            size=int(raw.get("size") or 0),
            digest=str(raw.get("digest") or ""),
        )
    return result


def verify_asset(path: Path, asset: ReleaseAsset) -> None:
    if not path.is_file():
        raise DatasetBridgeError(f"Fichier absent après téléchargement: {path}")
    if path.stat().st_size != asset.size:
        raise DatasetBridgeError(
            f"Taille incorrecte pour {asset.name}: {path.stat().st_size} au lieu de {asset.size}"
        )
    if not asset.sha256:
        raise DatasetBridgeError(
            f"GitHub ne fournit pas de SHA-256 pour {asset.name}; le fichier est refusé."
        )
    local = _sha256(path)
    if local.lower() != asset.sha256.lower():
        raise DatasetBridgeError(
            f"SHA-256 incorrect pour {asset.name}: {local} != {asset.sha256}"
        )


def download_asset(
    asset: ReleaseAsset,
    destination_dir: Path,
    *,
    repository: str = DEFAULT_REPOSITORY,
    force: bool = False,
) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / asset.name
    if destination.is_file() and not force:
        try:
            verify_asset(destination, asset)
            return destination
        except DatasetBridgeError:
            destination.unlink(missing_ok=True)

    if asset.asset_id <= 0:
        raise DatasetBridgeError(f"Identifiant GitHub invalide pour {asset.name}")

    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("wb") as target:
        process = subprocess.run(
            [
                _gh_path(),
                "api",
                "-H",
                "Accept: application/octet-stream",
                f"repos/{repository}/releases/assets/{asset.asset_id}",
            ],
            stdout=target,
            stderr=subprocess.PIPE,
        )
    if process.returncode != 0:
        temporary.unlink(missing_ok=True)
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise DatasetBridgeError(
            f"Téléchargement GitHub échoué pour {asset.name}: {detail}"
        )
    temporary.replace(destination)
    verify_asset(destination, asset)
    return destination


def ensure_metadata(
    root: Path,
    *,
    repository: str = DEFAULT_REPOSITORY,
    release_id: int | None = DEFAULT_RELEASE_ID,
    force: bool = False,
) -> tuple[dict[str, object], dict[str, ReleaseAsset], Path]:
    release = load_release(repository, release_id)
    assets = release_assets(release)
    metadata_dir = root / "data" / "hypersmart_datasets" / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    missing = [name for name in CORE_METADATA_ASSETS if name not in assets]
    if missing:
        raise DatasetBridgeError(
            "La Release n'a pas tous ses fichiers de contrôle: " + ", ".join(missing)
        )

    for name in CORE_METADATA_ASSETS:
        download_asset(assets[name], metadata_dir, repository=repository, force=force)
    for name in OPTIONAL_METADATA_ASSETS:
        if name in assets:
            download_asset(assets[name], metadata_dir, repository=repository, force=force)
    return release, assets, metadata_dir


def iter_manifest_records(manifest_path: Path) -> Iterator[DatasetRecord]:
    with gzip.open(manifest_path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetBridgeError(
                    f"Le manifeste est abîmé à la ligne {line_number}."
                ) from exc
            if not isinstance(raw, Mapping):
                continue
            record = DatasetRecord.from_mapping(raw)
            if record.relative_path:
                yield record


def select_records(
    records: Iterable[DatasetRecord],
    *,
    contains: Sequence[str] = (),
    suffixes: Sequence[str] = (),
    limit: int | None = None,
) -> list[DatasetRecord]:
    needles = tuple(item.casefold() for item in contains if item)
    endings = tuple(item.casefold() for item in suffixes if item)
    selected: list[DatasetRecord] = []
    for record in records:
        path = record.relative_path.casefold()
        if needles and not any(needle in path for needle in needles):
            continue
        if endings and not any(path.endswith(suffix) for suffix in endings):
            continue
        selected.append(record)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def assets_for_records(records: Iterable[DatasetRecord]) -> tuple[str, ...]:
    names: set[str] = set()
    for record in records:
        names.update(record.needed_assets())
    return tuple(sorted(names))


def download_needed_assets(
    root: Path,
    assets: Mapping[str, ReleaseAsset],
    names: Iterable[str],
    *,
    repository: str = DEFAULT_REPOSITORY,
    force: bool = False,
) -> dict[str, Path]:
    cache_dir = root / "data" / "hypersmart_datasets" / "assets"
    result: dict[str, Path] = {}
    for name in names:
        asset = assets.get(name)
        if asset is None:
            raise DatasetBridgeError(f"Fichier référencé mais absent de la Release: {name}")
        result[name] = download_asset(
            asset,
            cache_dir,
            repository=repository,
            force=force,
        )
    return result


def _safe_destination(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    destination = (resolved_root / relative_path).resolve()
    try:
        destination.relative_to(resolved_root)
    except ValueError as exc:
        raise DatasetBridgeError(
            f"Chemin dangereux refusé dans le dataset: {relative_path}"
        ) from exc
    return destination


def materialize_records(
    records: Iterable[DatasetRecord],
    downloaded_assets: Mapping[str, Path],
    output_root: Path,
) -> list[Path]:
    records = list(records)
    output_root.mkdir(parents=True, exist_ok=True)
    by_zip: dict[str, list[DatasetRecord]] = {}
    raw_records: list[DatasetRecord] = []

    for record in records:
        if record.storage == "zip_entry" and record.asset:
            by_zip.setdefault(record.asset, []).append(record)
        elif record.storage == "raw_chunks":
            raw_records.append(record)
        else:
            raise DatasetBridgeError(
                f"Stockage inconnu pour {record.relative_path}: {record.storage}"
            )

    created: list[Path] = []
    for asset_name, group in by_zip.items():
        archive_path = downloaded_assets.get(asset_name)
        if archive_path is None:
            raise DatasetBridgeError(f"Archive non téléchargée: {asset_name}")
        with zipfile.ZipFile(archive_path, "r") as archive:
            names = set(archive.namelist())
            for record in group:
                if record.relative_path not in names:
                    raise DatasetBridgeError(
                        f"{record.relative_path} est absent de {asset_name}"
                    )
                destination = _safe_destination(output_root, record.relative_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(record.relative_path, "r") as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target, length=8 * 1024 * 1024)
                _verify_reconstructed(destination, record)
                created.append(destination)

    for record in raw_records:
        destination = _safe_destination(output_root, record.relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        chunks = sorted(record.chunks, key=lambda item: int(item.get("part") or 0))
        if not chunks:
            raise DatasetBridgeError(f"Aucun morceau pour {record.relative_path}")
        with destination.open("wb") as target:
            for chunk in chunks:
                asset_name = str(chunk.get("asset") or "")
                chunk_path = downloaded_assets.get(asset_name)
                if chunk_path is None:
                    raise DatasetBridgeError(f"Morceau non téléchargé: {asset_name}")
                with chunk_path.open("rb") as source:
                    shutil.copyfileobj(source, target, length=8 * 1024 * 1024)
        _verify_reconstructed(destination, record)
        created.append(destination)
    return created


def _verify_reconstructed(path: Path, record: DatasetRecord) -> None:
    if path.stat().st_size != record.size:
        raise DatasetBridgeError(
            f"Taille reconstruite incorrecte pour {record.relative_path}"
        )
    if record.sha256 and _sha256(path).lower() != record.sha256.lower():
        raise DatasetBridgeError(
            f"SHA-256 reconstruit incorrect pour {record.relative_path}"
        )


def build_status(
    root: Path,
    *,
    repository: str = DEFAULT_REPOSITORY,
    release_id: int = DEFAULT_RELEASE_ID,
) -> dict[str, object]:
    release = load_release(repository, release_id)
    assets = release_assets(release)
    return {
        "repository": repository,
        "release_id": release_id,
        "release_name": release.get("name"),
        "tag_name": release.get("tag_name"),
        "draft": bool(release.get("draft")),
        "published_at": release.get("published_at"),
        "asset_count": len(assets),
        "asset_bytes": sum(asset.size for asset in assets.values()),
        "local_metadata_dir": str(root / "data" / "hypersmart_datasets" / "metadata"),
        "local_asset_cache_dir": str(root / "data" / "hypersmart_datasets" / "assets"),
        "local_materialized_dir": str(root / "data" / "hypersmart_datasets" / "materialized"),
    }


def release_publication_receipt(
    release: Mapping[str, object],
    required_assets: Sequence[str],
) -> dict[str, object]:
    """Validate publication metadata without treating an incomplete release as SAFE."""
    assets = release_assets(release)
    required = tuple(dict.fromkeys(str(name) for name in required_assets if str(name).strip()))
    missing = [name for name in required if name not in assets]
    invalid = [asset.name for asset in assets.values() if asset.asset_id <= 0 or asset.size < 0 or not asset.sha256]
    if missing or invalid or not str(release.get("tag_name") or "").strip() or release.get("draft") is True:
        return {"status": "REJECTED", "missing_assets": missing, "invalid_assets": invalid, "safe_published": False}
    return {"status": "PROVEN", "asset_count": len(assets), "required_assets": list(required), "safe_published": True, "repository": DEFAULT_REPOSITORY, "tag_name": str(release.get("tag_name"))}


def _release_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _release_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _release_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def release_bridge_safety_receipt(release: Mapping[str, object], required_assets: Sequence[str]) -> dict[str, Any]:
    result = release_publication_receipt(release, required_assets) if isinstance(release, Mapping) else {"status": "REJECTED"}
    valid = result.get("status") == "PROVEN"
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_SAFE" if valid else "RELEASE_BRIDGE_UNSAFE", release_status=result, fail_closed=not valid)


def release_bridge_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_FIELD_PRESENT" if valid else "RELEASE_BRIDGE_FIELD_MISSING", field=field, fail_closed=not valid)


def release_bridge_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_FIELD_NON_NULL" if valid else "RELEASE_BRIDGE_FIELD_NULL", field=field, fail_closed=not valid)


def release_bridge_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_FIELD_TYPE_VALID" if valid else "REJECTED", field=field, fail_closed=not valid)


def release_bridge_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _release_finite(value)
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_VALUE_FINITE" if valid else "RELEASE_BRIDGE_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def release_bridge_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _release_integer(event_ts_ms) and _release_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_EVENT_WITHIN_CUTOFF" if valid else "RELEASE_BRIDGE_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def release_bridge_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _release_integer(event_ts_ms) and _release_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_EVENT_AGE_VALID" if valid else "RELEASE_BRIDGE_EVENT_TOO_OLD", fail_closed=not valid)


def release_bridge_duplicate_receipt(*, event_ids: list[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_EVENTS_UNIQUE" if valid else "RELEASE_BRIDGE_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def release_bridge_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _release_integer(attempts) and _release_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_RETRY_BOUNDED" if valid else "RELEASE_BRIDGE_RETRY_UNSAFE", fail_closed=not valid)


def release_bridge_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_REPLAY_DETERMINISTIC" if valid else "RELEASE_BRIDGE_REPLAY_DIVERGED", fail_closed=not valid)


def release_bridge_http_error_receipt(*, status_code: Any, retry_after_seconds: Any = None) -> dict[str, Any]:
    valid_status = _release_integer(status_code) and status_code in {404, 408, 429, 500, 502, 503, 504}
    retryable = status_code in {408, 429, 500, 502, 503, 504} and _release_finite(retry_after_seconds) and float(retry_after_seconds) > 0
    valid = status_code == 404 or retryable
    return _release_base("PROVEN" if valid and valid_status else "REJECTED", verdict="RELEASE_BRIDGE_REMOTE_ERROR_QUARANTINED" if valid and valid_status else "RELEASE_BRIDGE_REMOTE_ERROR_UNSAFE", status_code=status_code, retryable=retryable, fail_closed=not (valid and valid_status))


def release_bridge_range_receipt(*, requested_start: Any, observed_start: Any, range_honored: bool) -> dict[str, Any]:
    valid = _release_integer(requested_start) and _release_integer(observed_start) and requested_start == observed_start and range_honored is True
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_RANGE_HONORED" if valid else "RELEASE_BRIDGE_RANGE_IGNORED", fail_closed=not valid)


def release_bridge_content_range_receipt(*, expected_start: Any, observed_start: Any, expected_end: Any, observed_end: Any) -> dict[str, Any]:
    valid = all(_release_integer(value) for value in (expected_start, observed_start, expected_end, observed_end)) and expected_start == observed_start and expected_end == observed_end and observed_end >= observed_start
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_CONTENT_RANGE_MATCH" if valid else "RELEASE_BRIDGE_CONTENT_RANGE_MISMATCH", fail_closed=not valid)


def release_bridge_etag_receipt(*, previous_etag: Any, current_etag: Any) -> dict[str, Any]:
    previous = str(previous_etag or "").strip(); current = str(current_etag or "").strip()
    changed = bool(previous and current and previous != current)
    return _release_base("PROVEN" if changed else "REJECTED", verdict="RELEASE_BRIDGE_ETAG_CHANGE_INVALIDATES_CACHE" if changed else "RELEASE_BRIDGE_ETAG_CHANGE_UNPROVEN", cache_invalidated=changed, fail_closed=not changed)


def release_bridge_disk_space_receipt(*, required_bytes: Any, available_bytes: Any) -> dict[str, Any]:
    valid = _release_integer(required_bytes) and _release_integer(available_bytes) and required_bytes >= 0 and available_bytes >= 0 and available_bytes >= required_bytes
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_DISK_SPACE_SUFFICIENT" if valid else "RELEASE_BRIDGE_DISK_SPACE_INSUFFICIENT", fail_closed=not valid)


def release_bridge_zip_slip_receipt(member: Any) -> dict[str, Any]:
    text = str(member or "").replace("\\", "/")
    unsafe = text.startswith("/") or ":" in text.split("/")[0] or ".." in text.split("/")
    return _release_base("PROVEN" if unsafe else "REJECTED", verdict="RELEASE_BRIDGE_ZIP_SLIP_REFUSED" if unsafe else "RELEASE_BRIDGE_ZIP_SLIP_NOT_REFUSED", fail_closed=not unsafe)


def release_bridge_expansion_receipt(*, observed_bytes: Any, max_bytes: Any, complete: bool) -> dict[str, Any]:
    valid = _release_integer(observed_bytes) and _release_integer(max_bytes) and observed_bytes >= 0 and max_bytes >= 0 and observed_bytes <= max_bytes and complete is True
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_EXPANSION_BOUNDED" if valid else "RELEASE_BRIDGE_EXPANSION_UNSAFE", fail_closed=not valid)


def release_bridge_lease_receipt(*, active_leases: Any, lease_token_present: bool) -> dict[str, Any]:
    valid = _release_integer(active_leases) and active_leases == 1 and lease_token_present is True
    return _release_base("PROVEN" if valid else "REJECTED", verdict="RELEASE_BRIDGE_SINGLE_LEASE" if valid else "RELEASE_BRIDGE_SPLIT_BRAIN_RISK", fail_closed=not valid)


def release_bridge_done_receipt(*, checks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Close release-bridge review only when every local gate is proven."""

    valid = bool(checks) and all(
        isinstance(check, Mapping)
        and check.get("status") == "PROVEN"
        and check.get("paper_read_only") is True
        and check.get("real_execution") is False
        and check.get("fail_closed") is False
        and bool(str(check.get("verdict") or "").strip())
        for check in checks
    )
    return _release_base(
        "PROVEN" if valid else "REJECTED",
        verdict="RELEASE_BRIDGE_DONE_COVERED" if valid else "RELEASE_BRIDGE_DONE_INCOMPLETE",
        check_count=len(checks) if isinstance(checks, Sequence) else 0,
        fail_closed=not valid,
    )


def release_bridge_preflight_receipt(release: Mapping[str, object], required_assets: Sequence[str]) -> dict[str, Any]:
    return release_bridge_safety_receipt(release, required_assets)
