from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

DEFAULT_REPOSITORY = "Rapt0r06300/hypersmart-datasets"
DEFAULT_RELEASE_ID = 371149058
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
    """Erreur contrôlée du pont vers hypersmart-datasets."""


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
    release_id: int = DEFAULT_RELEASE_ID,
) -> dict[str, object]:
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
    release_id: int = DEFAULT_RELEASE_ID,
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
