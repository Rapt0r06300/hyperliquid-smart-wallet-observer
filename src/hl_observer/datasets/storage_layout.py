from __future__ import annotations

import os
from pathlib import Path


def dataset_storage_root(project_root: str | Path) -> Path:
    """Retourne la racine persistante utilisée par les datasets FULL/COLD.

    Priorité :
    1. ALINA_DATASET_HOME : chemin explicite vers la racine datasets ;
    2. ALINA_RESEARCH_HOME : le sous-dossier ``datasets`` du laboratoire ;
    3. emplacement historique dans le projet pour rester rétro-compatible.
    """

    explicit = str(os.getenv("ALINA_DATASET_HOME") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    research_home = str(os.getenv("ALINA_RESEARCH_HOME") or "").strip()
    if research_home:
        return (Path(research_home).expanduser().resolve() / "datasets")

    return Path(project_root).resolve() / "data" / "hypersmart_datasets"


def dataset_metadata_dir(project_root: str | Path) -> Path:
    return dataset_storage_root(project_root) / "metadata"


def dataset_asset_cache_dir(project_root: str | Path) -> Path:
    return dataset_storage_root(project_root) / "assets"


def dataset_workspace_root(project_root: str | Path) -> Path:
    return dataset_storage_root(project_root) / "workspaces"


def dataset_materialized_dir(project_root: str | Path) -> Path:
    return dataset_storage_root(project_root) / "materialized"


__all__ = [
    "dataset_asset_cache_dir",
    "dataset_materialized_dir",
    "dataset_metadata_dir",
    "dataset_storage_root",
    "dataset_workspace_root",
]
