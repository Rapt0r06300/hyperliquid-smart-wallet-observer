from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from hl_observer.config.settings import Settings


DB_SUFFIXES = (".sqlite3", ".db")
SQLITE_RUNTIME_SUFFIXES = (".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".db", ".db-wal", ".db-shm")
_HYGIENE_PRUNED_DIRS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv-portable",
    "__pycache__",
    "datasets",
    "node_modules",
    "src",
    "tests",
}


def _hygiene_scan_roots(root: Path) -> list[Path]:
    """Return bounded runtime roots for a repository checkout.

    The project contains immutable datasets, source trees and historical
    archives that cannot contain an active SQLite/log runtime state. Scanning
    those trees made the read-only CLI contract unbounded. Temporary fixture
    roots are still scanned generically so the unit-level safety contract does
    not lose coverage.
    """
    if not (root / ".git").is_dir():
        return [root]
    candidates = [
        root / "data",
        root / "logs",
        root / "runtime" / "data",
        root / "runtime" / "logs",
    ]
    existing = [path for path in candidates if path.is_dir()]
    return existing or [root]


@dataclass(frozen=True)
class RuntimeHygieneReport:
    root: Path
    configured_database_url: str
    configured_db_path: Path | None
    databases: list[Path] = field(default_factory=list)
    databases_in_logs: list[Path] = field(default_factory=list)
    sqlite_sidecars: list[Path] = field(default_factory=list)
    log_files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def clean_archive_safe(self) -> bool:
        return True

    @property
    def active_runtime_warning(self) -> bool:
        return bool(self.databases_in_logs or self.sqlite_sidecars)

    @property
    def databases_in_logs_count(self) -> int:
        return len(self.databases_in_logs)


def scan_runtime_hygiene(settings: Settings, *, root: Path = Path(".")) -> RuntimeHygieneReport:
    resolved_root = root.resolve()
    db_path = _database_path(settings.database_url)
    databases: list[Path] = []
    databases_in_logs: list[Path] = []
    sqlite_sidecars: list[Path] = []
    log_files: list[Path] = []
    warnings: list[str] = []
    for scan_root in _hygiene_scan_roots(resolved_root):
        for dirpath, dirnames, filenames in os.walk(scan_root, topdown=True):
            dirnames[:] = [name for name in dirnames if name not in _HYGIENE_PRUNED_DIRS]
            current = Path(dirpath)
            for filename in filenames:
                path = current / filename
                rel = _safe_relative(path, resolved_root).as_posix().lower()
                name = path.name.lower()
                if name.endswith(DB_SUFFIXES):
                    databases.append(path)
                    if rel.startswith("logs/"):
                        databases_in_logs.append(path)
                if name.endswith((".sqlite3-wal", ".sqlite3-shm", ".db-wal", ".db-shm")):
                    sqlite_sidecars.append(path)
                if name.endswith(".log"):
                    log_files.append(path)
    if db_path is not None and "logs" in [part.lower() for part in db_path.parts]:
        warnings.append("configured database_url points inside logs/; move runtime DB to data/.")
    if databases_in_logs:
        warnings.append("legacy SQLite database detected under logs/; do not archive it.")
    if sqlite_sidecars:
        warnings.append("SQLite WAL/SHM sidecars detected; a database may be active.")
    return RuntimeHygieneReport(
        root=resolved_root,
        configured_database_url=settings.database_url,
        configured_db_path=db_path,
        databases=databases,
        databases_in_logs=databases_in_logs,
        sqlite_sidecars=sqlite_sidecars,
        log_files=log_files,
        warnings=warnings,
    )


def format_runtime_hygiene_report(report: RuntimeHygieneReport) -> str:
    lines = [
        "runtime-check report",
        f"root: {report.root}",
        f"database_url: {report.configured_database_url}",
        f"configured_db_path: {report.configured_db_path}",
        f"sqlite_databases_found: {len(report.databases)}",
        f"sqlite_databases_in_logs: {len(report.databases_in_logs)}",
        f"sqlite_wal_shm_files: {len(report.sqlite_sidecars)}",
        f"log_files: {len(report.log_files)}",
        "clean_archive_safe: true",
        "archive_policy: exclude logs/, data/, *.sqlite3, *.db, WAL/SHM, logs, caches, venvs, archives, .env",
        "do not archive runtime files; clean archives use staging and exclusion rules",
    ]
    for path in report.databases_in_logs:
        lines.append(f"WARNING legacy DB in logs: {path}")
    for path in report.sqlite_sidecars:
        lines.append(f"WARNING sqlite_sidecar: {path}")
    for warning in report.warnings:
        lines.append(f"WARNING: {warning}")
    if report.databases_in_logs:
        lines.append("next_action: close the process using the legacy DB, then move future DBs to data/.")
    return "\n".join(lines)


def _database_path(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite:///"):
        return None
    value = database_url.removeprefix("sqlite:///")
    if value == ":memory:":
        return None
    return Path(value)


def _safe_relative(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path
