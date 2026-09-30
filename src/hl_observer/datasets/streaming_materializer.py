from __future__ import annotations

import shutil
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable, Mapping

from hl_observer.datasets.github_release_bridge import (
    DatasetBridgeError,
    DatasetRecord,
    ReleaseAsset,
    verify_asset,
)
from hl_observer.datasets.release_gateway import _download_asset


DownloadAsset = Callable[
    [ReleaseAsset, Path],
    Path,
]


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


def _verify_reconstructed(path: Path, record: DatasetRecord) -> None:
    from hl_observer.datasets.github_release_bridge import _sha256

    if not path.is_file():
        raise DatasetBridgeError(f"Fichier reconstruit absent: {path}")
    if path.stat().st_size != record.size:
        raise DatasetBridgeError(
            f"Taille reconstruite incorrecte pour {record.relative_path}: "
            f"{path.stat().st_size} != {record.size}"
        )
    if record.sha256 and _sha256(path).lower() != record.sha256.lower():
        raise DatasetBridgeError(
            f"SHA-256 reconstruit incorrect pour {record.relative_path}"
        )


def _default_downloader(
    asset: ReleaseAsset,
    cache_dir: Path,
    *,
    repository: str,
    force: bool,
) -> Path:
    return _download_asset(
        asset,
        cache_dir,
        repository=repository,
        force=force,
    )


def materialize_records_streaming(
    records: Iterable[DatasetRecord],
    assets: Mapping[str, ReleaseAsset],
    output_root: Path,
    cache_dir: Path,
    *,
    repository: str,
    force: bool = False,
    purge_assets_after_use: bool = True,
    downloader: Callable[..., Path] | None = None,
) -> dict[str, object]:
    """Materialize a selection while keeping at most one large asset resident.

    ZIP assets are downloaded one-by-one, all selected members are extracted,
    then the asset can be removed. Raw chunk records are reconstructed in
    chunk order, downloading/deleting each chunk sequentially.

    The source Release remains immutable; only the local cache/workspace is
    written. Final file size and SHA-256 are checked before success.
    """

    rows = list(records)
    output_root.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    fetch = downloader or _default_downloader
    by_zip: dict[str, list[DatasetRecord]] = defaultdict(list)
    raw_records: list[DatasetRecord] = []

    for record in rows:
        if record.storage == "zip_entry":
            if not record.asset:
                raise DatasetBridgeError(
                    f"Archive absente du manifeste pour {record.relative_path}"
                )
            by_zip[record.asset].append(record)
        elif record.storage == "raw_chunks":
            raw_records.append(record)
        else:
            raise DatasetBridgeError(
                f"Stockage inconnu pour {record.relative_path}: {record.storage}"
            )

    created: list[Path] = []
    downloaded_names: list[str] = []
    purged_names: list[str] = []
    max_asset_size = 0

    def obtain(name: str) -> tuple[ReleaseAsset, Path]:
        asset = assets.get(name)
        if asset is None:
            raise DatasetBridgeError(
                f"Fichier référencé mais absent de la Release: {name}"
            )
        nonlocal max_asset_size
        max_asset_size = max(max_asset_size, int(asset.size))
        try:
            path = fetch(
                asset,
                cache_dir,
                repository=repository,
                force=force,
            )
        except TypeError:
            # Small injectable fakes used by unit tests may only accept two args.
            path = fetch(asset, cache_dir)
        verify_asset(path, asset)
        downloaded_names.append(name)
        return asset, path

    def purge(path: Path, name: str) -> None:
        if not purge_assets_after_use:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise DatasetBridgeError(
                f"Impossible de purger l'asset temporaire {name}: {exc}"
            ) from exc
        purged_names.append(name)

    for asset_name in sorted(by_zip):
        _, archive_path = obtain(asset_name)
        group = by_zip[asset_name]
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                available = set(archive.namelist())
                for record in group:
                    member = record.relative_path
                    if member not in available:
                        raise DatasetBridgeError(
                            f"{member} est absent de {asset_name}"
                        )
                    destination = _safe_destination(
                        output_root,
                        record.relative_path,
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temporary = destination.with_suffix(
                        destination.suffix + ".part"
                    )
                    temporary.unlink(missing_ok=True)
                    try:
                        with archive.open(member, "r") as source, temporary.open(
                            "wb"
                        ) as target:
                            shutil.copyfileobj(
                                source,
                                target,
                                length=8 * 1024 * 1024,
                            )
                        temporary.replace(destination)
                        _verify_reconstructed(destination, record)
                    except Exception:
                        temporary.unlink(missing_ok=True)
                        raise
                    created.append(destination)
        finally:
            purge(archive_path, asset_name)

    for record in raw_records:
        chunks = sorted(
            record.chunks,
            key=lambda item: int(item.get("part") or 0),
        )
        if not chunks:
            raise DatasetBridgeError(
                f"Aucun morceau pour {record.relative_path}"
            )

        destination = _safe_destination(
            output_root,
            record.relative_path,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.unlink(missing_ok=True)

        try:
            with temporary.open("wb") as target:
                for chunk in chunks:
                    asset_name = str(chunk.get("asset") or "")
                    if not asset_name:
                        raise DatasetBridgeError(
                            f"Nom de morceau absent pour {record.relative_path}"
                        )
                    _, chunk_path = obtain(asset_name)
                    try:
                        with chunk_path.open("rb") as source:
                            shutil.copyfileobj(
                                source,
                                target,
                                length=8 * 1024 * 1024,
                            )
                    finally:
                        purge(chunk_path, asset_name)
            temporary.replace(destination)
            _verify_reconstructed(destination, record)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        created.append(destination)

    return {
        "created_files": len(created),
        "created_paths": [str(path) for path in created],
        "downloaded_asset_count": len(downloaded_names),
        "downloaded_assets": downloaded_names,
        "purged_asset_count": len(purged_names),
        "purged_assets": purged_names,
        "max_asset_size_bytes": max_asset_size,
        "purge_assets_after_use": bool(purge_assets_after_use),
    }


__all__ = ["materialize_records_streaming"]
