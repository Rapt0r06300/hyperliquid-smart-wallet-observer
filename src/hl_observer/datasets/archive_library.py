from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from hl_observer.datasets.github_release_bridge import (
    DatasetBridgeError,
    DatasetRecord,
    ReleaseAsset,
)
from hl_observer.datasets.storage_layout import (
    dataset_asset_cache_dir,
    dataset_workspace_root,
)

ECONOMIC_CORE_PATTERNS = (
    "runtime/data/vault_fills.jsonl",
    "runtime/data/vault_fills_live.jsonl",
    "runtime/data/vault_ledger.jsonl",
    "runtime/data/vault_episodes.jsonl",
    "runtime/data/vault_snapshots.jsonl",
    "runtime/data/copy_vault_l2_tape.jsonl",
    "runtime/data/carnet_venues.jsonl",
    "runtime/data/bbo_tape.jsonl",
    "runtime/data/bbo_tape.jsonl.prev",
    "runtime/data/bbo_shards/",
    "runtime/data/bbo_shards_archive/",
    "runtime/data/lead_lag_config_gele.json",
)

COPY_VAULT_PATTERNS = (
    "copy_vault",
    "copy-vault",
    "vault",
    "leader",
    "userfill",
    "metaorder",
    "twap",
)

LEAD_LAG_PATTERNS = (
    "lead_lag",
    "lead-lag",
    "bbo",
    "allmids",
    "microprice",
    "orderflow",
    "ofi",
)

CROSS_VENUE_PATTERNS = (
    "cross_venue",
    "cross-venue",
    "carnet_venues",
    "venue",
    "binance",
    "dydx",
    "dislocation",
)

MICROSTRUCTURE_PATTERNS = (
    "l2",
    "book",
    "orderbook",
    "depth",
    "carnet",
    "bid",
    "ask",
)

RESEARCH_LAB_PATTERNS = (
    "research_lab",
    "research-lab",
    "scenario",
    "replay",
    "backtest",
    "histor",
)

SQLITE_PRIMARY_PATHS = (
    "runtime/data/hypersmart_simulation_session.sqlite3",
    "data/hl_observer.sqlite3",
)

SQLITE_SAFE_SUFFIXES = (".sqlite3",)
SQLITE_UNSAFE_PATH_PATTERNS = (
    "corrupt",
    "broken",
    "damaged",
    "quarantine",
    "invalid",
    ".git/",
)


def _merge_patterns(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for group in groups for item in group))


@dataclass(frozen=True)
class DatasetSuite:
    name: str
    label: str
    description: str
    patterns: tuple[str, ...] = ()
    exact_paths: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()
    include_all: bool = False
    runner: str = "inventory_only"


SUITES: dict[str, DatasetSuite] = {
    "economic-core": DatasetSuite(
        name="economic-core",
        label="Noyau économique canonique",
        description=(
            "Sources minimales canoniques pour Copy-Vault, Lead-Lag et Cross-Venue. "
            "Sert au smoke replay rapide des trois moteurs."
        ),
        patterns=ECONOMIC_CORE_PATTERNS,
        runner="economic_campaigns",
    ),
    "economic-full": DatasetSuite(
        name="economic-full",
        label="Toutes les données des trois moteurs",
        description=(
            "Union large de toutes les données repérées pour Copy-Vault, Lead-Lag "
            "et Cross-Venue. C'est la suite principale pour les replays économiques profonds."
        ),
        patterns=_merge_patterns(
            COPY_VAULT_PATTERNS,
            LEAD_LAG_PATTERNS,
            CROSS_VENUE_PATTERNS,
        ),
        runner="economic_campaigns",
    ),
    "copy-vault-full": DatasetSuite(
        name="copy-vault-full",
        label="Copy-Vault complet",
        description="Toutes les sources repérées autour des vaults, leaders, user fills, metaorders et TWAP.",
        patterns=COPY_VAULT_PATTERNS,
        runner="family_research",
    ),
    "lead-lag-full": DatasetSuite(
        name="lead-lag-full",
        label="Lead-Lag complet",
        description="Toutes les sources BBO, allMids, microprice, order-flow et OFI repérées.",
        patterns=LEAD_LAG_PATTERNS,
        runner="family_research",
    ),
    "cross-venue-full": DatasetSuite(
        name="cross-venue-full",
        label="Cross-Venue complet",
        description="Toutes les sources de dislocation et de comparaison de venues repérées.",
        patterns=CROSS_VENUE_PATTERNS,
        runner="family_research",
    ),
    "microstructure-full": DatasetSuite(
        name="microstructure-full",
        label="Microstructure complète",
        description="Carnets L2, profondeur, bid/ask et autres données de microstructure repérées.",
        patterns=MICROSTRUCTURE_PATTERNS,
        runner="research_inventory",
    ),
    "research-lab-full": DatasetSuite(
        name="research-lab-full",
        label="Research Lab complet",
        description="Archives de recherche, scénarios, replays, backtests et historiques repérés.",
        patterns=RESEARCH_LAB_PATTERNS,
        runner="research_inventory",
    ),
    "sqlite-core": DatasetSuite(
        name="sqlite-core",
        label="Bases SQLite principales",
        description=(
            "Les deux grosses bases SQLite canoniques du projet. Les anciennes copies marquées "
            "corrompues et les sidecars WAL/SHM ne font pas partie de cette suite."
        ),
        exact_paths=SQLITE_PRIMARY_PATHS,
        runner="sqlite_inventory",
    ),
    "sqlite-all-safe": DatasetSuite(
        name="sqlite-all-safe",
        label="Toutes les bases SQLite saines par leur nom",
        description=(
            "Toutes les bases terminant par .sqlite3, hors chemins explicitement marqués "
            "corrompus/endommages/quarantaine et hors objets internes .git."
        ),
        suffixes=SQLITE_SAFE_SUFFIXES,
        exclude_patterns=SQLITE_UNSAFE_PATH_PATTERNS,
        runner="sqlite_inventory",
    ),
    "full-archive": DatasetSuite(
        name="full-archive",
        label="Archive FULL/COLD complète",
        description=(
            "La totalité du snapshot FULL/COLD. Cette suite ne signifie pas que tout doit être "
            "téléchargé d'un coup : elle fournit surtout une vue et un workspace reproductibles."
        ),
        include_all=True,
        runner="archive_inventory",
    ),
}


def suite_names() -> tuple[str, ...]:
    return tuple(SUITES)


def get_suite(name: str) -> DatasetSuite:
    try:
        return SUITES[name]
    except KeyError as exc:
        raise DatasetBridgeError(f"Suite de données inconnue: {name}") from exc


def record_matches_suite(record: DatasetRecord, suite: DatasetSuite) -> bool:
    lowered = record.relative_path.replace("\\", "/").casefold()
    if suite.include_all:
        return True
    if any(pattern.casefold() in lowered for pattern in suite.exclude_patterns):
        return False
    if suite.exact_paths:
        exact = {path.casefold() for path in suite.exact_paths}
        if lowered in exact:
            return True
    if suite.suffixes and any(lowered.endswith(suffix.casefold()) for suffix in suite.suffixes):
        return True
    if suite.patterns and any(pattern.casefold() in lowered for pattern in suite.patterns):
        return True
    return False


def select_suite_records(
    records: Iterable[DatasetRecord],
    suite_name: str,
    *,
    limit: int | None = None,
) -> list[DatasetRecord]:
    suite = get_suite(suite_name)
    selected: list[DatasetRecord] = []
    for record in records:
        if not record_matches_suite(record, suite):
            continue
        selected.append(record)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def selection_digest(records: Iterable[DatasetRecord]) -> str:
    digest = hashlib.sha256()
    for record in records:
        line = (
            f"{record.relative_path}\0{record.size}\0{record.sha256}\0{record.storage}\n"
        )
        digest.update(line.encode("utf-8", errors="strict"))
    return digest.hexdigest()


def asset_cache_dir(project_root: Path) -> Path:
    return dataset_asset_cache_dir(project_root)


def suite_workspace_base(project_root: Path, suite_name: str) -> Path:
    get_suite(suite_name)
    return dataset_workspace_root(project_root) / suite_name


def suite_workspace_for_digest(
    project_root: Path,
    suite_name: str,
    digest: str,
) -> Path:
    if len(digest) < 16 or any(ch not in "0123456789abcdef" for ch in digest.casefold()):
        raise DatasetBridgeError("Digest de sélection invalide pour le workspace.")
    return suite_workspace_base(project_root, suite_name) / digest[:16].casefold()


def current_pointer_path(project_root: Path, suite_name: str) -> Path:
    return suite_workspace_base(project_root, suite_name) / "CURRENT.json"


def write_current_workspace(
    project_root: Path,
    suite_name: str,
    *,
    digest: str,
    workspace: Path,
    release_id: int,
) -> Path:
    base = suite_workspace_base(project_root, suite_name).resolve()
    resolved = workspace.resolve()
    try:
        relative = resolved.relative_to(base)
    except ValueError as exc:
        raise DatasetBridgeError("Le workspace courant sort de la suite autorisée.") from exc
    pointer = current_pointer_path(project_root, suite_name)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "hypersmart.dataset_suite_pointer.v1",
        "suite": suite_name,
        "selection_digest": digest,
        "workspace_relative_to_suite": relative.as_posix(),
        "source_release_id": int(release_id),
    }
    temporary = pointer.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(pointer)
    return pointer


def resolve_current_workspace(project_root: Path, suite_name: str) -> Path:
    pointer = current_pointer_path(project_root, suite_name)
    if not pointer.is_file():
        raise DatasetBridgeError(
            f"Aucun workspace courant pour {suite_name}. Prépare d'abord cette suite."
        )
    try:
        raw = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetBridgeError(f"Pointeur de workspace illisible: {pointer}") from exc
    relative = str(raw.get("workspace_relative_to_suite") or "")
    if not relative:
        raise DatasetBridgeError(f"Pointeur de workspace incomplet: {pointer}")
    base = suite_workspace_base(project_root, suite_name).resolve()
    resolved = (base / relative).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise DatasetBridgeError("Pointeur de workspace dangereux refusé.") from exc
    if not resolved.is_dir():
        raise DatasetBridgeError(f"Workspace pointé absent: {resolved}")
    return resolved


def _plan_state() -> dict[str, object]:
    return {
        "matched_files": 0,
        "matched_raw_bytes": 0,
        "asset_names": set(),
        "examples": [],
        "digest": hashlib.sha256(),
    }


def _update_state(state: dict[str, object], record: DatasetRecord) -> None:
    state["matched_files"] = int(state["matched_files"]) + 1
    state["matched_raw_bytes"] = int(state["matched_raw_bytes"]) + int(record.size)
    names = state["asset_names"]
    assert isinstance(names, set)
    names.update(record.needed_assets())
    examples = state["examples"]
    assert isinstance(examples, list)
    if len(examples) < 40:
        examples.append(record.relative_path)
    digest = state["digest"]
    assert hasattr(digest, "update")
    digest.update(
        (
            f"{record.relative_path}\0{record.size}\0{record.sha256}\0{record.storage}\n"
        ).encode("utf-8")
    )


def _finish_plan(
    suite: DatasetSuite,
    state: Mapping[str, object],
    assets: Mapping[str, ReleaseAsset],
    *,
    project_root: Path | None,
) -> dict[str, object]:
    asset_names = sorted(str(name) for name in state["asset_names"])
    missing = [name for name in asset_names if name not in assets]
    download_bytes = sum(assets[name].size for name in asset_names if name in assets)
    cached_names: list[str] = []
    cached_bytes = 0
    cache = asset_cache_dir(project_root) if project_root is not None else None
    if cache is not None:
        for name in asset_names:
            asset = assets.get(name)
            path = cache / name
            if asset is None or not path.is_file():
                continue
            try:
                same_size = path.stat().st_size == asset.size
            except OSError:
                same_size = False
            if same_size:
                cached_names.append(name)
                cached_bytes += asset.size
    remaining = max(0, download_bytes - cached_bytes)
    digest_obj = state["digest"]
    digest_hex = digest_obj.hexdigest()
    workspace = (
        suite_workspace_for_digest(project_root, suite.name, digest_hex)
        if project_root is not None
        else None
    )
    return {
        "suite": suite.name,
        "label": suite.label,
        "description": suite.description,
        "runner": suite.runner,
        "matched_files": int(state["matched_files"]),
        "matched_raw_bytes": int(state["matched_raw_bytes"]),
        "matched_raw_gib": round(int(state["matched_raw_bytes"]) / (1024**3), 4),
        "selection_digest": digest_hex,
        "needed_asset_count": len(asset_names),
        "needed_assets": asset_names,
        "download_bytes": download_bytes,
        "download_gib": round(download_bytes / (1024**3), 4),
        "cache_hits_size_only": len(cached_names),
        "cached_bytes_size_only": cached_bytes,
        "cached_gib_size_only": round(cached_bytes / (1024**3), 4),
        "remaining_download_bytes": remaining,
        "remaining_download_gib": round(remaining / (1024**3), 4),
        "missing_asset_count": len(missing),
        "missing_assets": missing,
        "workspace": str(workspace) if workspace is not None else None,
        "examples": list(state["examples"]),
    }


def build_all_suite_plans(
    records: Iterable[DatasetRecord],
    assets: Mapping[str, ReleaseAsset],
    *,
    project_root: Path | None = None,
) -> dict[str, dict[str, object]]:
    states = {name: _plan_state() for name in SUITES}
    for record in records:
        for name, suite in SUITES.items():
            if record_matches_suite(record, suite):
                _update_state(states[name], record)
    return {
        name: _finish_plan(
            SUITES[name],
            states[name],
            assets,
            project_root=project_root,
        )
        for name in SUITES
    }


def build_selection_plan(
    records: Iterable[DatasetRecord],
    assets: Mapping[str, ReleaseAsset],
    suite_name: str,
    *,
    project_root: Path | None = None,
) -> dict[str, object]:
    suite = get_suite(suite_name)
    state = _plan_state()
    for record in records:
        _update_state(state, record)
    return _finish_plan(suite, state, assets, project_root=project_root)


def render_library_markdown(
    plans: Mapping[str, Mapping[str, object]],
    *,
    release_id: int,
) -> str:
    lines = [
        "# Bibliothèque FULL/COLD reliée à Alina SmartFlow",
        "",
        f"- Release source : **{release_id}**",
        "- Les assets sont partagés dans un cache commun et vérifiés au téléchargement.",
        "- Chaque suite est reconstruite dans un workspace isolé identifié par son digest.",
        "- Les chiffres de cache ci-dessous sont basés sur la taille locale; le SHA-256 est revérifié avant usage réel.",
        "",
        "| Suite | Fichiers | Gio bruts | Assets | Gio total assets | Gio restant | Manquants | Usage |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name in SUITES:
        plan = plans.get(name, {})
        lines.append(
            f"| {name} | {plan.get('matched_files', 0)} | "
            f"{plan.get('matched_raw_gib', 0)} | {plan.get('needed_asset_count', 0)} | "
            f"{plan.get('download_gib', 0)} | {plan.get('remaining_download_gib', 0)} | "
            f"{plan.get('missing_asset_count', 0)} | {plan.get('runner', '')} |"
        )
    lines.extend(
        [
            "",
            "## Doctrine",
            "",
            "- `economic-core` sert de contrôle rapide du pipeline.",
            "- `economic-full` est la suite large prioritaire pour les trois moteurs actifs.",
            "- Les suites par famille servent aux recherches ciblées et aux futurs replays dédiés.",
            "- `microstructure-full` et `research-lab-full` alimentent la recherche de nouvelles hypothèses.",
            "- `sqlite-core` récupère uniquement les deux grosses bases canoniques connues.",
            "- `sqlite-all-safe` récupère toutes les bases `.sqlite3` dont le nom ne porte pas un marqueur de corruption/quarantaine.",
            "- `full-archive` représente toute la sauvegarde; elle ne doit pas être téléchargée inutilement en bloc.",
            "- Aucun résultat n'est promu sans coûts, séparation temporelle et validation hors échantillon.",
            "",
        ]
    )
    return "\n".join(lines)
