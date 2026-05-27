from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


INCLUDE_PATHS = [
    ".env.example",
    ".gitignore",
    "AGENTS.md",
    "README.md",
    "requirements.txt",
    "pyproject.toml",
    "config",
    "docs",
    "src",
    "hyper_smart_observer",
    "tests",
    "tools",
    "CREER_ARCHIVE_PROPRE.cmd",
    "LANCER_HYPERSMART.cmd",
]
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "data",
    "logs",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".refact",
    "dist",
    "build",
}
EXCLUDED_SUFFIXES = {
    ".sqlite3",
    ".db",
    ".log",
    ".zip",
    ".7z",
    ".rar",
    ".tmp",
    ".pyc",
}
EXCLUDED_NAMES = {
    ".env",
}


@dataclass(frozen=True)
class ArchiveResult:
    archive_path: Path
    files_copied: int
    warnings: list[str]
    entries: int = 0


def default_desktop_output_dir() -> Path:
    return Path.home() / "Desktop"


def default_archive_name() -> str:
    return f"Projet_invest_clean_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"


def is_archive_safe_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    if parts & EXCLUDED_PARTS:
        return False
    if path.name.lower() in EXCLUDED_NAMES:
        return False
    lower = path.name.lower()
    if lower.endswith((".sqlite3-wal", ".sqlite3-shm", ".db-wal", ".db-shm")):
        return False
    return path.suffix.lower() not in EXCLUDED_SUFFIXES


def create_clean_archive(root: Path, output_dir: Path | None = None, *, name: str | None = None) -> ArchiveResult:
    root = root.resolve()
    output_dir = (output_dir or default_desktop_output_dir()).resolve()
    name = name or default_archive_name()
    if output_dir == root or root in output_dir.parents:
        raise RuntimeError("Clean archives must be created outside the project directory.")
    if Path(name).name != name:
        raise RuntimeError("Archive name must be a file name, not a path.")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / name
    if archive_path == root / archive_path.name or root in archive_path.resolve().parents:
        raise RuntimeError("Archive output path inside the project is refused.")
    warnings: list[str] = []
    files_copied = 0
    with tempfile.TemporaryDirectory(prefix="hypersmart-archive-") as temp_dir:
        staging = Path(temp_dir) / "staging"
        staging.mkdir()
        for include in INCLUDE_PATHS:
            source = root / include
            if not source.exists():
                continue
            if source.is_file():
                if is_archive_safe_path(source.relative_to(root)):
                    target = staging / include
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    files_copied += 1
                continue
            for path in source.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(root)
                if not is_archive_safe_path(relative):
                    warnings.append(f"excluded runtime file: {relative.as_posix()}")
                    continue
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                files_copied += 1
        _write_zip(staging, archive_path)
    entries = _audit_archive(archive_path)
    return ArchiveResult(archive_path, files_copied, warnings, entries)


def archive_readiness(root: Path) -> dict[str, object]:
    unsafe: list[str] = []
    root_archives: list[str] = []
    for path in root.rglob("*"):
        if path.is_file() and not is_archive_safe_path(path.relative_to(root)):
            unsafe.append(path.relative_to(root).as_posix())
    for path in root.glob("*"):
        if path.is_file() and path.suffix.lower() in {".zip", ".7z", ".rar"}:
            root_archives.append(path.name)
    return {
        "archive_ready": not root_archives,
        "unsafe_runtime_files_excluded": unsafe,
        "root_archives_forbidden": root_archives,
        "include_paths": INCLUDE_PATHS,
    }


def _write_zip(staging: Path, archive_path: Path) -> None:
    if archive_path.exists():
        archive_path.unlink()
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as zip_file:
        for path in staging.rglob("*"):
            if path.is_file():
                zip_file.write(path, path.relative_to(staging).as_posix())


def _audit_archive(archive_path: Path) -> int:
    with ZipFile(archive_path) as zip_file:
        names = zip_file.namelist()
    bad = [
        name
        for name in names
        if name.startswith(("logs/", "data/"))
        or name.startswith((".git/", ".venv/", "venv/"))
        or "/__pycache__/" in name
        or name.startswith("__pycache__/")
        or "/.pytest_cache/" in name
        or name.startswith(".pytest_cache/")
        or "/.refact/" in name
        or name.startswith(".refact/")
        or name.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".db", ".db-wal", ".db-shm", ".log"))
        or name.endswith((".zip", ".7z", ".rar", ".pyc"))
        or name == ".env"
    ]
    if bad:
        raise RuntimeError(f"Archive contains runtime files: {bad[:5]}")
    return len(names)
