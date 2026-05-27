from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from hyper_smart_observer.app.config import AppConfig


DB_SUFFIXES = (".sqlite3", ".db")
RUNTIME_SUFFIXES = (".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".db", ".db-wal", ".db-shm", ".log")


@dataclass(frozen=True)
class RuntimeFileReport:
    root: Path
    database_path: Path
    databases: list[Path] = field(default_factory=list)
    logs_databases: list[Path] = field(default_factory=list)
    wal_shm_files: list[Path] = field(default_factory=list)
    log_files: list[Path] = field(default_factory=list)
    archive_files_at_root: list[Path] = field(default_factory=list)
    cache_dirs: list[Path] = field(default_factory=list)
    data_dir_exists: bool = False
    logs_dir_exists: bool = False
    archive_button_exists: bool = False
    archive_script_exists: bool = False
    gitignore_has_runtime_excludes: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def archive_ready(self) -> bool:
        return not self.archive_files_at_root

    @property
    def runtime_has_legacy_files(self) -> bool:
        return bool(self.logs_databases or self.wal_shm_files)


def scan_runtime_files(config: AppConfig) -> RuntimeFileReport:
    root = Path(config.runtime_root).resolve()
    databases: list[Path] = []
    logs_databases: list[Path] = []
    wal_shm_files: list[Path] = []
    log_files: list[Path] = []
    archive_files_at_root: list[Path] = []
    cache_dirs: list[Path] = []
    warnings: list[str] = []
    if not root.exists():
        warnings.append(f"Runtime root does not exist: {root}")
        return RuntimeFileReport(root, Path(config.database_path), warnings=warnings)
    for archive in root.glob("*"):
        if archive.is_file() and archive.suffix.lower() in {".zip", ".7z", ".rar"}:
            archive_files_at_root.append(archive)
    for cache_name in ("__pycache__", ".pytest_cache", ".mypy_cache"):
        cache_dirs.extend(path for path in root.rglob(cache_name) if path.is_dir())
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        lower_name = path.name.lower()
        relative = _safe_relative(path, root).as_posix().lower()
        if lower_name.endswith(DB_SUFFIXES):
            databases.append(path)
            if relative.startswith("logs/"):
                logs_databases.append(path)
        if lower_name.endswith(("-wal", "-shm")):
            wal_shm_files.append(path)
        if lower_name.endswith(".log"):
            log_files.append(path)
    if logs_databases:
        warnings.append("SQLite database(s) found under logs/. Logs should contain text logs only.")
    if wal_shm_files:
        warnings.append("WAL/SHM files detected. Do not archive active SQLite runtime files.")
    if archive_files_at_root:
        warnings.append("Archive file(s) found at project root. Create clean archives on Desktop only.")
    db_path = Path(config.database_path)
    if "logs" in [part.lower() for part in db_path.parts]:
        warnings.append("HyperSmart database_path points inside logs/. Move it to data/.")
    gitignore_text = (root / ".gitignore").read_text(encoding="utf-8", errors="ignore") if (root / ".gitignore").exists() else ""
    return RuntimeFileReport(
        root,
        db_path,
        databases,
        logs_databases,
        wal_shm_files,
        log_files,
        archive_files_at_root,
        cache_dirs,
        (root / "data").exists(),
        (root / "logs").exists(),
        (root / "CREER_ARCHIVE_PROPRE.cmd").exists(),
        (root / "tools" / "create_clean_archive.ps1").exists(),
        all(token in gitignore_text for token in ("data/", "logs/", "*.sqlite3", "*.zip", ".env")),
        warnings,
    )


def format_runtime_report(report: RuntimeFileReport) -> str:
    lines = [
        "HyperSmart runtime check",
        f"root: {report.root}",
        f"database_path: {report.database_path}",
        f"databases: {len(report.databases)}",
        f"databases_in_logs: {len(report.logs_databases)}",
        f"wal_shm_files: {len(report.wal_shm_files)}",
        f"log_files: {len(report.log_files)}",
        f"root_archives_zip_7z_rar: {len(report.archive_files_at_root)}",
        f"cache_dirs: {len(report.cache_dirs)}",
        f"data_dir_exists: {report.data_dir_exists}",
        f"logs_dir_exists: {report.logs_dir_exists}",
        f"archive_button_exists: {report.archive_button_exists}",
        f"archive_script_exists: {report.archive_script_exists}",
        f"gitignore_runtime_excludes: {report.gitignore_has_runtime_excludes}",
        f"dashboard_output_path: data/dashboard/hypersmart_dashboard.html",
        f"archive_ready: {report.archive_ready}",
        f"runtime_has_legacy_files: {report.runtime_has_legacy_files}",
    ]
    for path in report.logs_databases:
        lines.append(f"WARNING db_in_logs: {path}")
    for path in report.wal_shm_files:
        lines.append(f"WARNING active_sqlite_sidecar: {path}")
    for warning in report.warnings:
        lines.append(f"WARNING: {warning}")
    for archive in report.archive_files_at_root:
        lines.append(f"WARNING root_archive: {archive}")
    if report.logs_databases:
        lines.append("Action: stop dashboards/processes using the DB, then move future DB defaults to data/.")
    if report.archive_files_at_root:
        lines.append("Action: remove root archives and use CREER_ARCHIVE_PROPRE.cmd to create a Desktop ZIP.")
    lines.append("Recommendation: use CREER_ARCHIVE_PROPRE.cmd for a Desktop archive.")
    lines.append("Archive rule: exclude logs/, data/, DB/WAL/SHM, caches, archives, .env and virtualenvs.")
    return "\n".join(lines)


def _safe_relative(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path
