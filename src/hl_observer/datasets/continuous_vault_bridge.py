from __future__ import annotations

import base64
import gzip
import hashlib
import json
import urllib.parse
from pathlib import Path
from typing import Iterable, Mapping

from hl_observer.datasets.archive_library import (
    build_selection_plan,
    select_suite_records,
    selection_digest,
    suite_names,
)
from hl_observer.datasets.github_api_transport import (
    GitHubTransportError,
    download_release_asset,
    get_json,
)
from hl_observer.datasets.github_release_bridge import (
    DEFAULT_REPOSITORY,
    DatasetBridgeError,
    DatasetRecord,
    ReleaseAsset,
    assets_for_records,
    verify_asset,
)
from hl_observer.datasets.release_gateway import list_all_release_assets
from hl_observer.datasets.storage_layout import (
    dataset_asset_cache_dir,
    dataset_storage_root,
)
from hl_observer.datasets.streaming_materializer import materialize_records_streaming

POINTER_PATH = "catalog/CONTINUOUS_VAULT_POINTER.json"
POINTER_SCHEMA = "alina.data_vault.pointer.v1"
INDEX_SCHEMA = "alina.data_vault.file_index.v1"


def _decode_contents_payload(raw: object) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise DatasetBridgeError("Pointeur Continuous Vault GitHub invalide.")
    encoding = str(raw.get("encoding") or "")
    content = str(raw.get("content") or "")
    if encoding != "base64" or not content:
        raise DatasetBridgeError(
            "Le pointeur Continuous Vault n'est pas fourni en base64 par GitHub."
        )
    try:
        decoded = base64.b64decode(content).decode("utf-8")
        payload = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetBridgeError(
            "Le pointeur Continuous Vault est illisible."
        ) from exc
    if not isinstance(payload, dict):
        raise DatasetBridgeError("Le pointeur Continuous Vault doit être un objet JSON.")
    return payload


def load_continuous_pointer(
    *,
    repository: str = DEFAULT_REPOSITORY,
    ref: str = "main",
) -> dict[str, object]:
    encoded_path = urllib.parse.quote(POINTER_PATH, safe="/")
    encoded_ref = urllib.parse.quote(ref, safe="")
    try:
        raw = get_json(
            f"repos/{repository}/contents/{encoded_path}?ref={encoded_ref}"
        )
    except GitHubTransportError as exc:
        raise DatasetBridgeError(
            "Aucun snapshot Continuous Vault utilisable n'est encore publié "
            f"dans {repository}:{ref}."
        ) from exc

    payload = _decode_contents_payload(raw)
    if str(payload.get("schema") or "") != POINTER_SCHEMA:
        raise DatasetBridgeError(
            f"Schema Continuous Vault inattendu: {payload.get('schema')!r}"
        )
    if str(payload.get("repository") or "") != repository:
        raise DatasetBridgeError(
            "Le pointeur Continuous Vault référence un autre dépôt."
        )
    index_asset = payload.get("index_asset")
    if not isinstance(index_asset, Mapping):
        raise DatasetBridgeError("Le pointeur Continuous Vault n'a pas d'index_asset.")
    if int(index_asset.get("asset_id") or 0) <= 0:
        raise DatasetBridgeError("Identifiant d'index Continuous Vault invalide.")
    if not str(index_asset.get("sha256") or ""):
        raise DatasetBridgeError("SHA-256 de l'index Continuous Vault absent.")
    return payload


def _pointer_index_asset(pointer: Mapping[str, object]) -> ReleaseAsset:
    raw = pointer.get("index_asset")
    if not isinstance(raw, Mapping):
        raise DatasetBridgeError("index_asset Continuous Vault invalide.")
    digest = str(raw.get("sha256") or "")
    if digest and not digest.startswith("sha256:"):
        digest = f"sha256:{digest}"
    return ReleaseAsset(
        asset_id=int(raw.get("asset_id") or 0),
        name=str(raw.get("name") or "VAULT_FILE_INDEX.json.gz"),
        size=int(raw.get("size") or 0),
        digest=digest,
    )


def ensure_continuous_index(
    root: Path,
    *,
    pointer: Mapping[str, object],
    repository: str = DEFAULT_REPOSITORY,
    force: bool = False,
) -> Path:
    metadata_dir = dataset_storage_root(root) / "continuous" / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    asset = _pointer_index_asset(pointer)
    destination = metadata_dir / asset.name

    if destination.is_file() and not force:
        try:
            verify_asset(destination, asset)
            return destination
        except DatasetBridgeError:
            destination.unlink(missing_ok=True)

    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        download_release_asset(
            repository=repository,
            asset_id=asset.asset_id,
            destination=temporary,
        )
    except (GitHubTransportError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        raise DatasetBridgeError(
            f"Téléchargement de l'index Continuous Vault impossible: {exc}"
        ) from exc

    temporary.replace(destination)
    verify_asset(destination, asset)
    return destination


def load_continuous_index(path: Path) -> dict[str, object]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetBridgeError(
            f"Index Continuous Vault illisible: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise DatasetBridgeError("Index Continuous Vault invalide.")
    if str(payload.get("schema") or "") != INDEX_SCHEMA:
        raise DatasetBridgeError(
            f"Schema d'index Continuous Vault inattendu: {payload.get('schema')!r}"
        )
    files = payload.get("files")
    if not isinstance(files, dict):
        raise DatasetBridgeError("Index Continuous Vault sans table de fichiers.")
    return payload


def iter_continuous_records(
    index_payload: Mapping[str, object],
    *,
    present_only: bool = False,
) -> Iterable[DatasetRecord]:
    raw_files = index_payload.get("files")
    if not isinstance(raw_files, Mapping):
        return ()

    def generate():
        for relative_path in sorted(str(key) for key in raw_files):
            raw = raw_files.get(relative_path)
            if not isinstance(raw, Mapping):
                continue
            if present_only and raw.get("present_local", True) is not True:
                continue
            mapping = dict(raw)
            mapping["relative_path"] = relative_path
            record = DatasetRecord.from_mapping(mapping)
            if not record.release_tag:
                raise DatasetBridgeError(
                    f"Release tag absent du Continuous Vault: {relative_path}"
                )
            yield record

    return generate()


def _release_for_tag(
    repository: str,
    tag: str,
) -> dict[str, object]:
    encoded = urllib.parse.quote(tag, safe="")
    try:
        raw = get_json(f"repos/{repository}/releases/tags/{encoded}")
    except GitHubTransportError as exc:
        raise DatasetBridgeError(
            f"Release Continuous Vault introuvable: {tag}"
        ) from exc
    if not isinstance(raw, dict):
        raise DatasetBridgeError(f"Release Continuous Vault invalide: {tag}")
    return raw


def assets_for_continuous_records(
    records: Iterable[DatasetRecord],
    *,
    repository: str = DEFAULT_REPOSITORY,
) -> dict[str, ReleaseAsset]:
    rows = list(records)
    tags = sorted({str(row.release_tag) for row in rows if row.release_tag})
    needed_names = set(assets_for_records(rows))
    result: dict[str, ReleaseAsset] = {}

    for tag in tags:
        release = _release_for_tag(repository, tag)
        release_id = int(release.get("id") or 0)
        if release_id <= 0:
            raise DatasetBridgeError(
                f"Release id invalide pour le tag Continuous Vault {tag}"
            )
        assets = list_all_release_assets(repository, release_id)
        for name in sorted(needed_names.intersection(assets)):
            asset = assets[name]
            previous = result.get(name)
            if previous is not None and previous.asset_id != asset.asset_id:
                raise DatasetBridgeError(
                    f"Deux assets Continuous Vault partagent le nom {name}"
                )
            result[name] = asset

    missing = sorted(needed_names - set(result))
    if missing:
        raise DatasetBridgeError(
            "Assets Continuous Vault manquants: " + ", ".join(missing[:20])
        )
    return result


def continuous_workspace_base(root: Path, suite: str) -> Path:
    if suite not in suite_names():
        raise DatasetBridgeError(f"Suite de données inconnue: {suite}")
    return dataset_storage_root(root) / "continuous" / "workspaces" / suite


def continuous_workspace_for_digest(
    root: Path,
    suite: str,
    digest: str,
) -> Path:
    if len(digest) < 16 or any(
        char not in "0123456789abcdef" for char in digest.casefold()
    ):
        raise DatasetBridgeError("Digest Continuous Vault invalide.")
    return continuous_workspace_base(root, suite) / digest[:16].casefold()


def continuous_pointer_path(root: Path, suite: str) -> Path:
    return continuous_workspace_base(root, suite) / "CURRENT.json"


def write_continuous_workspace_pointer(
    root: Path,
    suite: str,
    *,
    digest: str,
    workspace: Path,
    vault_snapshot_id: str,
    vault_release_id: int,
) -> Path:
    base = continuous_workspace_base(root, suite).resolve()
    resolved = workspace.resolve()
    try:
        relative = resolved.relative_to(base)
    except ValueError as exc:
        raise DatasetBridgeError(
            "Workspace Continuous Vault sort de la suite autorisée."
        ) from exc
    path = continuous_pointer_path(root, suite)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "hypersmart.continuous_vault_workspace.v1",
        "suite": suite,
        "selection_digest": digest,
        "workspace_relative_to_suite": relative.as_posix(),
        "vault_snapshot_id": vault_snapshot_id,
        "vault_release_id": int(vault_release_id),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def resolve_continuous_workspace(root: Path, suite: str) -> Path:
    path = continuous_pointer_path(root, suite)
    if not path.is_file():
        raise DatasetBridgeError(
            f"Aucun workspace Continuous Vault courant pour {suite}."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetBridgeError(
            f"Pointeur Continuous Vault illisible: {path}"
        ) from exc
    relative = str(payload.get("workspace_relative_to_suite") or "")
    if not relative:
        raise DatasetBridgeError("Pointeur Continuous Vault incomplet.")
    base = continuous_workspace_base(root, suite).resolve()
    workspace = (base / relative).resolve()
    try:
        workspace.relative_to(base)
    except ValueError as exc:
        raise DatasetBridgeError(
            "Pointeur Continuous Vault dangereux refusé."
        ) from exc
    if not workspace.is_dir():
        raise DatasetBridgeError(
            f"Workspace Continuous Vault absent: {workspace}"
        )
    return workspace


def continuous_snapshot_fingerprint(
    pointer: Mapping[str, object],
    index_path: Path,
) -> str:
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {
                "snapshot_id": pointer.get("latest_snapshot_id"),
                "release_id": pointer.get("latest_release_id"),
                "release_tag": pointer.get("latest_release_tag"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    with index_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_continuous_suite(
    root: Path,
    *,
    suite: str,
    repository: str = DEFAULT_REPOSITORY,
    ref: str = "main",
    present_only: bool = False,
    download: bool = False,
    force: bool = False,
    max_download_gib: float = 20.0,
    disk_reserve_gib: float = 1.0,
) -> dict[str, object]:
    if max_download_gib < 0 or disk_reserve_gib < 0:
        raise DatasetBridgeError("Les limites Continuous Vault ne peuvent pas être négatives.")

    pointer = load_continuous_pointer(repository=repository, ref=ref)
    index_path = ensure_continuous_index(
        root,
        pointer=pointer,
        repository=repository,
        force=force,
    )
    index_payload = load_continuous_index(index_path)
    all_records = list(
        iter_continuous_records(
            index_payload,
            present_only=present_only,
        )
    )
    selected = select_suite_records(all_records, suite)
    if not selected:
        raise DatasetBridgeError(
            f"Aucun fichier Continuous Vault ne correspond à {suite}."
        )

    assets = assets_for_continuous_records(
        selected,
        repository=repository,
    )
    plan = build_selection_plan(
        selected,
        assets,
        suite,
        project_root=None,
    )
    asset_names = tuple(plan["needed_assets"])
    total_download = sum(assets[name].size for name in asset_names)
    raw_bytes = sum(int(record.size) for record in selected)
    max_asset = max((assets[name].size for name in asset_names), default=0)
    free = __import__("shutil").disk_usage(root).free
    reserve = int(disk_reserve_gib * 1024**3)
    disk_required = raw_bytes + max_asset + reserve
    fingerprint = continuous_snapshot_fingerprint(pointer, index_path)
    digest = selection_digest(selected)
    workspace = continuous_workspace_for_digest(root, suite, digest)

    preview = {
        **plan,
        "source_kind": "continuous-vault",
        "repository": repository,
        "vault_snapshot_id": pointer.get("latest_snapshot_id"),
        "vault_release_id": int(pointer.get("latest_release_id") or 0),
        "vault_release_tag": pointer.get("latest_release_tag"),
        "snapshot_fingerprint_sha256": fingerprint,
        "selected_raw_bytes": raw_bytes,
        "selected_raw_gib": round(raw_bytes / (1024**3), 4),
        "download_bytes": total_download,
        "download_gib": round(total_download / (1024**3), 4),
        "largest_asset_bytes": max_asset,
        "streaming_disk_required_bytes": disk_required,
        "streaming_disk_free_bytes": int(free),
        "streaming_disk_ok": int(free) >= disk_required,
        "present_only": bool(present_only),
        "workspace": str(workspace),
        "paper_read_only": True,
        "real_execution": False,
    }
    if not download:
        return preview

    max_bytes = int(max_download_gib * 1024**3)
    if max_bytes > 0 and total_download > max_bytes:
        raise DatasetBridgeError(
            f"Continuous Vault demande {total_download / (1024**3):.2f} Gio, "
            f"au-dessus du plafond {max_download_gib:.2f} Gio."
        )
    if int(free) < disk_required:
        raise DatasetBridgeError(
            "Espace disque insuffisant pour la matérialisation streaming "
            f"Continuous Vault: libre={int(free)/(1024**3):.2f} Gio, "
            f"requis={disk_required/(1024**3):.2f} Gio."
        )

    streaming = materialize_records_streaming(
        selected,
        assets,
        workspace,
        dataset_asset_cache_dir(root) / "continuous",
        repository=repository,
        force=force,
        purge_assets_after_use=True,
    )
    provenance_dir = workspace / "runtime" / "reports" / "datasets"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    provenance = {
        "schema": "hypersmart.continuous_vault_provenance.v1",
        **preview,
        "streaming_result": streaming,
    }
    provenance_path = provenance_dir / "CONTINUOUS_VAULT_PROVENANCE.json"
    provenance_path.write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    canonical_provenance = provenance_dir / "SELECTION_PROVENANCE.json"
    canonical_provenance.write_text(
        json.dumps(
            {
                "schema": "hypersmart.dataset_selection_provenance.v3",
                "source_kind": "continuous-vault",
                "source_repository": repository,
                "source_release_id": int(pointer.get("latest_release_id") or 0),
                "source_release_name": pointer.get("latest_release_tag"),
                "source_snapshot_id": pointer.get("latest_snapshot_id"),
                "snapshot_fingerprint_sha256": fingerprint,
                "suite": suite,
                "selection_digest": digest,
                "selected_files": len(selected),
                "selected_raw_bytes": raw_bytes,
                "paper_read_only": True,
                "real_execution": False,
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    current = write_continuous_workspace_pointer(
        root,
        suite,
        digest=digest,
        workspace=workspace,
        vault_snapshot_id=str(pointer.get("latest_snapshot_id") or ""),
        vault_release_id=int(pointer.get("latest_release_id") or 0),
    )
    return {
        **preview,
        "downloaded": True,
        "fichiers_reconstruits": int(streaming["created_files"]),
        "provenance": str(provenance_path),
        "canonical_provenance": str(canonical_provenance),
        "pointeur_courant": str(current),
        "streaming_result": streaming,
    }


__all__ = [
    "INDEX_SCHEMA",
    "POINTER_PATH",
    "POINTER_SCHEMA",
    "assets_for_continuous_records",
    "continuous_pointer_path",
    "continuous_snapshot_fingerprint",
    "ensure_continuous_index",
    "iter_continuous_records",
    "load_continuous_index",
    "load_continuous_pointer",
    "prepare_continuous_suite",
    "resolve_continuous_workspace",
]
