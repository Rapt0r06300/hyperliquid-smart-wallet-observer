from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from hl_observer.datasets.github_release_bridge import (
    CORE_METADATA_ASSETS,
    OPTIONAL_METADATA_ASSETS,
    DEFAULT_RELEASE_ID,
    DEFAULT_REPOSITORY,
    DatasetBridgeError,
    ReleaseAsset,
    download_asset,
    load_release,
)


def _gh_path() -> str:
    gh = shutil.which("gh")
    if not gh:
        raise DatasetBridgeError(
            "GitHub CLI (gh) est introuvable. Impossible de lire la Release privée."
        )
    return gh


def _gh_json(arguments: Sequence[str]) -> object:
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
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise DatasetBridgeError("GitHub a renvoyé un JSON illisible.") from exc


def parse_asset_page(raw: object) -> list[ReleaseAsset]:
    if not isinstance(raw, list):
        raise DatasetBridgeError("La liste des fichiers de Release est invalide.")
    result: list[ReleaseAsset] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        result.append(
            ReleaseAsset(
                asset_id=int(item.get("id") or 0),
                name=name,
                size=int(item.get("size") or 0),
                digest=str(item.get("digest") or ""),
            )
        )
    return result


def list_all_release_assets(
    repository: str = DEFAULT_REPOSITORY,
    release_id: int = DEFAULT_RELEASE_ID,
    *,
    per_page: int = 100,
) -> dict[str, ReleaseAsset]:
    page = 1
    result: dict[str, ReleaseAsset] = {}
    while True:
        raw = _gh_json(
            [
                "api",
                f"repos/{repository}/releases/{release_id}/assets?per_page={per_page}&page={page}",
            ]
        )
        rows = parse_asset_page(raw)
        for asset in rows:
            previous = result.get(asset.name)
            if previous is not None and previous.asset_id != asset.asset_id:
                raise DatasetBridgeError(
                    f"Deux assets GitHub portent le même nom: {asset.name}"
                )
            result[asset.name] = asset
        if len(rows) < per_page:
            break
        page += 1
        if page > 100:
            raise DatasetBridgeError("Pagination GitHub anormalement longue; arrêt de sécurité.")
    return result


def ensure_release_metadata(
    root: Path,
    *,
    repository: str = DEFAULT_REPOSITORY,
    release_id: int = DEFAULT_RELEASE_ID,
    force: bool = False,
) -> tuple[dict[str, object], dict[str, ReleaseAsset], Path]:
    release = load_release(repository, release_id)
    assets = list_all_release_assets(repository, release_id)
    metadata_dir = root / "data" / "hypersmart_datasets" / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    missing = [name for name in CORE_METADATA_ASSETS if name not in assets]
    if missing:
        raise DatasetBridgeError(
            "La Release n'a pas tous ses fichiers de contrôle: " + ", ".join(missing)
        )

    for name in CORE_METADATA_ASSETS:
        download_asset(
            assets[name], metadata_dir, repository=repository, force=force
        )
    for name in OPTIONAL_METADATA_ASSETS:
        if name in assets:
            download_asset(
                assets[name], metadata_dir, repository=repository, force=force
            )
    return release, assets, metadata_dir


def build_release_status(
    root: Path,
    *,
    repository: str = DEFAULT_REPOSITORY,
    release_id: int = DEFAULT_RELEASE_ID,
) -> dict[str, object]:
    release = load_release(repository, release_id)
    assets = list_all_release_assets(repository, release_id)
    return {
        "repository": repository,
        "release_id": release_id,
        "release_name": release.get("name"),
        "tag_name": release.get("tag_name"),
        "draft": bool(release.get("draft")),
        "published_at": release.get("published_at"),
        "asset_count": len(assets),
        "asset_bytes": sum(asset.size for asset in assets.values()),
        "assets_with_sha256": sum(1 for asset in assets.values() if asset.sha256),
        "local_metadata_dir": str(root / "data" / "hypersmart_datasets" / "metadata"),
        "local_asset_cache_dir": str(root / "data" / "hypersmart_datasets" / "assets"),
        "local_materialized_dir": str(root / "data" / "hypersmart_datasets" / "materialized"),
    }
