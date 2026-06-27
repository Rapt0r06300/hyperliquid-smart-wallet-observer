from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from hyper_smart_observer.runtime.archive import archive_readiness


def audit_archive_readiness(root: Path) -> tuple[bool, str]:
    result = archive_readiness(root)
    root_archives = [path for path in root.glob("*") if path.is_file() and path.suffix.lower() in {".zip", ".7z", ".rar"}]
    if root_archives:
        return False, f"Archive(s) found at project root: {len(root_archives)}"
    return bool(result["archive_ready"]), f"Runtime files excluded by clean archive: {len(result['unsafe_runtime_files_excluded'])}"


def audit_zip_contents(zip_path: Path) -> tuple[bool, list[str]]:
    forbidden: list[str] = []
    with ZipFile(zip_path) as archive:
        for entry in archive.namelist():
            lower = entry.replace("\\", "/").lower()
            if (
                lower.startswith((".git/", "data/", "logs/", ".venv/", "venv/"))
                or "/__pycache__/" in lower
                or lower.startswith("__pycache__/")
                or ".pytest_cache/" in lower
                or ".refact/" in lower
                or lower.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".db", ".db-wal", ".db-shm", ".log", ".zip", ".7z", ".rar", ".pyc"))
                or lower == ".env"
            ):
                forbidden.append(entry)
    return not forbidden, forbidden


def write_archive_audit_report(root: Path, output: Path = Path("docs/release/HYPERSMART_ARCHIVE_AUDIT.md")) -> Path:
    ok, message = audit_archive_readiness(root)
    desktop = Path.home() / "Desktop"
    latest_archive = None
    if desktop.exists():
        archives = sorted(desktop.glob("Projet_invest_clean_*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
        latest_archive = archives[0] if archives else None
    zip_ok = None
    forbidden: list[str] = []
    if latest_archive is not None:
        zip_ok, forbidden = audit_zip_contents(latest_archive)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# HyperSmart Archive Audit",
        "",
        f"- status: {'OK' if ok else 'FAIL'}",
        f"- message: {message}",
        f"- latest_desktop_archive: {latest_archive if latest_archive else 'none'}",
        f"- latest_desktop_archive_clean: {zip_ok if zip_ok is not None else 'not_checked'}",
        f"- forbidden_entries_in_latest_archive: {len(forbidden)}",
        "- clean archives must be created outside the project, preferably Desktop.",
        "- root ZIP/7Z/RAR files are forbidden.",
        "- logs/, data/, .git/, SQLite, WAL/SHM, caches, .env and nested archives are excluded.",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
