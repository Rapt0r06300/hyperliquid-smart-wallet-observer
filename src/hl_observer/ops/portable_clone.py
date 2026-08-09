"""Create a complete, directly runnable Windows disaster-recovery clone.

Unlike the small application-only ZIP, this clone preserves durable runtime
data, Git history, logs and reports. SQLite databases are copied with the
SQLite Backup API. Machine-specific state and transient caches are omitted so
the existing first-launch preflight can safely regenerate them on the target
computer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from hl_observer.ops import archive_portable as AP


MANIFEST_NAME = "PORTABLE_FULL_CLONE_MANIFEST.json"
SCHEMA_VERSION = 1
SQLITE_SUFFIXES = (".sqlite", ".sqlite3", ".db")
SQLITE_SIDECARS = (".sqlite-wal", ".sqlite-shm", ".sqlite3-wal", ".sqlite3-shm", ".db-wal", ".db-shm")

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        "__pycache__",
        ".hypothesis",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".refact",
        ".venv",
        ".venv-portable",
        "node_modules",
        "htmlcov",
        "tmp_pytest",
    }
)

MACHINE_SPECIFIC_PATHS = frozenset(
    {
        "runtime/data/launcher_pids.json",
        "runtime/data/lanceur_session_marqueur.txt",
        "runtime/data/courante.json",
        "runtime/data/sessions/courante.json",
        "runtime/data/machine_id.txt",
    }
)

SECRET_FILE_NAMES = frozenset({".env", "id_rsa", "id_ed25519"})
SECRET_SUFFIXES = (".key", ".p12", ".pfx", ".mnemonic", ".seed", ".keystore")
TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")
TRANSIENT_SUFFIXES = (".tmp", ".pid", ".pyc", ".pyo")
SECRET_SCAN_SUFFIXES = (
    "",
    ".cfg",
    ".cmd",
    ".conf",
    ".env",
    ".ini",
    ".json",
    ".md",
    ".pem",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
)
MAX_SECRET_SCAN_SIZE = 2 * 1024 * 1024
MAX_WINDOWS_PATH = 259
# No link is currently required by the portable runtime. Any future exception
# must be reviewed and named explicitly here; links are never followed.
REPARSE_WHITELIST = frozenset()


class PortableCloneError(RuntimeError):
    """A full clone was refused before publication."""


def machine_fingerprint() -> str:
    """Return a privacy-preserving identifier used only to prove PC A != PC B."""
    parts = [platform.node(), os.environ.get("COMPUTERNAME", ""), str(uuid.getnode())]
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                parts.append(str(winreg.QueryValueEx(key, "MachineGuid")[0]))
        except (OSError, ImportError):
            pass
    material = "|".join(part.strip().casefold() for part in parts if part.strip())
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PlannedFile:
    relative_path: str
    size: int
    kind: str


@dataclass(frozen=True)
class CloneInventory:
    files: tuple[PlannedFile, ...]
    excluded: tuple[dict[str, str], ...]
    total_bytes: int
    sqlite_count: int
    longest_relative_path: int
    longest_relative_member: str


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(os.stat_result, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _assert_reparse_allowed(relative_path: str) -> None:
    normalized = relative_path.replace("\\", "/").rstrip("/")
    if normalized not in REPARSE_WHITELIST:
        raise PortableCloneError(
            "symlink/junction/reparse point refused (not whitelisted): " + normalized
        )


def _is_public_template(name: str) -> bool:
    return name == ".env.example" or any(name.endswith(suffix) for suffix in TEMPLATE_SUFFIXES)


def _classification(relative_path: str) -> tuple[str, str | None]:
    normalized = relative_path.replace("\\", "/")
    lower = normalized.casefold()
    parts = tuple(part.casefold() for part in normalized.split("/") if part)
    name = parts[-1]

    if any(part in EXCLUDED_DIRECTORY_NAMES for part in parts[:-1]):
        return "exclude", "cache_or_generated_directory"
    if lower in MACHINE_SPECIFIC_PATHS:
        return "exclude", "machine_specific_state"
    if name.endswith(".lock") and ("runtime" in parts or ".git" in parts):
        return "exclude", "stale_runtime_lock"
    if lower.endswith(SQLITE_SIDECARS):
        return "exclude", "sqlite_sidecar_replaced_by_backup"
    if name.endswith(TRANSIENT_SUFFIXES):
        return "exclude", "transient_file"
    if (name in SECRET_FILE_NAMES or name.startswith(".env.")) and not _is_public_template(name):
        return "secret", "secret_filename"
    if name.endswith(SECRET_SUFFIXES):
        return "secret", "secret_suffix"
    if name.startswith("debug_status") or name.startswith("debug_fusion_status"):
        if parts and parts[0] == "runtime":
            return "exclude", "machine_specific_debug_status"
    if name == MANIFEST_NAME.casefold():
        return "exclude", "generated_clone_manifest"
    if name.endswith(SQLITE_SUFFIXES):
        return "sqlite", None
    return "file", None


def _should_scan_private_key_content(relative_path: str, size: int) -> bool:
    if size > MAX_SECRET_SCAN_SIZE:
        return False
    lower = relative_path.casefold()
    if lower.startswith((".git/objects/", "tools/python/", "portable_runtime/")):
        return False
    return Path(lower).suffix in SECRET_SCAN_SUFFIXES


def inventory(root: str | Path, *, scan_private_key_content: bool = True) -> CloneInventory:
    """Inventory every durable file without following links or touching source data."""
    source_root = _resolved(root)
    if not source_root.is_dir():
        raise PortableCloneError(f"source root does not exist: {source_root}")

    files: list[PlannedFile] = []
    excluded: list[dict[str, str]] = []
    secrets: list[str] = []
    longest_member = ""
    longest_length = 0
    total_bytes = 0
    sqlite_count = 0

    for directory, subdirectories, names in os.walk(source_root, topdown=True, followlinks=False):
        current = Path(directory)
        kept_directories: list[str] = []
        for name in sorted(subdirectories):
            candidate = current / name
            rel = candidate.relative_to(source_root).as_posix()
            if name.casefold() in EXCLUDED_DIRECTORY_NAMES:
                excluded.append({"path": rel + "/", "reason": "cache_or_generated_directory"})
                continue
            if _is_reparse(candidate):
                _assert_reparse_allowed(rel)
                excluded.append({"path": rel + "/", "reason": "whitelisted_reparse_not_copied"})
                continue
            kept_directories.append(name)
        subdirectories[:] = kept_directories

        for name in sorted(names):
            path = current / name
            rel = path.relative_to(source_root).as_posix()
            if _is_reparse(path):
                _assert_reparse_allowed(rel)
                excluded.append({"path": rel, "reason": "whitelisted_reparse_not_copied"})
                continue
            try:
                AP.valider_chemin_relatif(rel, max_rel=245)
            except AP.ArchiveRefuseeError as exc:
                raise PortableCloneError(str(exc)) from exc
            kind, reason = _classification(rel)
            if kind == "exclude":
                excluded.append({"path": rel, "reason": str(reason)})
                continue
            try:
                size = path.stat().st_size
            except OSError as exc:
                if reason == "transient_file":
                    excluded.append({"path": rel, "reason": "disappeared_transient_file"})
                    continue
                raise PortableCloneError(f"cannot stat {rel}: {exc}") from exc
            content_secret = (
                scan_private_key_content
                and _should_scan_private_key_content(rel, int(size))
                and AP.contient_cle_privee(path)
            )
            if kind == "secret" or content_secret:
                secrets.append(rel)
                continue
            files.append(PlannedFile(rel, int(size), kind))
            total_bytes += int(size)
            sqlite_count += int(kind == "sqlite")
            if len(rel) > longest_length:
                longest_length = len(rel)
                longest_member = rel

    if secrets:
        preview = ", ".join(sorted(secrets)[:20])
        raise PortableCloneError(f"secret/private-key material must not be cloned: {preview}")
    files.sort(key=lambda item: item.relative_path.casefold())
    excluded.sort(key=lambda item: item["path"].casefold())
    return CloneInventory(
        files=tuple(files),
        excluded=tuple(excluded),
        total_bytes=total_bytes,
        sqlite_count=sqlite_count,
        longest_relative_path=longest_length,
        longest_relative_member=longest_member,
    )


def _available_drive_roots() -> Iterable[Path]:
    if os.name != "nt":
        yield Path.cwd().anchor and Path(Path.cwd().anchor) or Path("/")
        return
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZC":
        drive = Path(f"{letter}:\\")
        if drive.exists():
            yield drive


def automatic_destination(required_bytes: int, *, now: float | None = None) -> Path:
    """Pick a short writable drive path with enough free space."""
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now or time.time()))
    margin = max(512 * 1024 * 1024, int(required_bytes * 0.05))
    candidates: list[tuple[int, Path]] = []
    for drive in _available_drive_roots():
        try:
            free = shutil.disk_usage(drive).free
        except OSError:
            continue
        if free >= required_bytes + margin:
            candidates.append((free, drive / f"HS_PORTABLE_{stamp}"))
    if not candidates:
        raise PortableCloneError(
            "no drive has enough free space for the full portable clone "
            f"({required_bytes + margin} bytes required)"
        )
    # Prefer a non-system drive when possible, then the one with most free space.
    system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\/").casefold()
    non_system = [item for item in candidates if item[1].drive.casefold() != system_drive]
    pool = non_system or candidates
    return max(pool, key=lambda item: item[0])[1]


def _validate_destination(source_root: Path, destination: Path, inv: CloneInventory) -> None:
    if _is_within(destination, source_root) or _is_within(source_root, destination):
        raise PortableCloneError("destination must be outside and separate from the source project")
    if destination.exists():
        raise PortableCloneError(f"destination already exists: {destination}")
    longest = len(str(destination)) + 1 + inv.longest_relative_path
    if longest > MAX_WINDOWS_PATH:
        raise PortableCloneError(
            "destination path is too long for standard Windows copy/paste "
            f"({longest} characters; choose a short path such as D:\\HS_PORTABLE)"
        )
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    margin = max(512 * 1024 * 1024, int(inv.total_bytes * 0.05))
    free = shutil.disk_usage(parent).free
    if free < inv.total_bytes + margin:
        raise PortableCloneError(
            f"not enough free space: {free} available, {inv.total_bytes + margin} required"
        )


def _copy_and_hash(source: Path, destination: Path, *, buffer_size: int = 8 * 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("xb") as dst:
        while True:
            block = src.read(buffer_size)
            if not block:
                break
            dst.write(block)
            digest.update(block)
            size += len(block)
        dst.flush()
        os.fsync(dst.fileno())
    try:
        shutil.copystat(source, destination, follow_symlinks=False)
    except OSError:
        pass
    return digest.hexdigest(), size


def _hash_file(path: Path, *, buffer_size: int = 8 * 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(buffer_size)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _embedded_git(root: Path) -> Path:
    return root / "tools" / "git" / "cmd" / "git.exe"


def _git_command(root: Path, *arguments: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    git = _embedded_git(root)
    if not git.is_file():
        raise PortableCloneError(f"embedded Git missing: {git}")
    return subprocess.run(
        [str(git), "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def verify_git_repository(root: str | Path) -> dict[str, object]:
    """Prove the transported repository with the Git binary it carries."""
    project = _resolved(root)
    commands = {
        "fsck": ("fsck", "--full"),
        "head": ("rev-parse", "HEAD"),
        "branch": ("branch", "--show-current"),
        "remotes": ("remote", "-v"),
    }
    outputs: dict[str, str] = {}
    failures: dict[str, dict[str, object]] = {}
    for name, args in commands.items():
        try:
            completed = _git_command(project, *args, timeout=300 if name == "fsck" else 60)
        except (OSError, subprocess.SubprocessError, PortableCloneError) as exc:
            failures[name] = {"returncode": -1, "stderr": str(exc)}
            continue
        output = (completed.stdout or "").strip()
        outputs[name] = output
        if completed.returncode != 0:
            failures[name] = {
                "returncode": completed.returncode,
                "stderr": (completed.stderr or "").strip(),
            }
    head = outputs.get("head", "")
    branch = outputs.get("branch", "")
    remotes = outputs.get("remotes", "")
    if len(head) != 40:
        failures.setdefault("head", {"returncode": -2, "stderr": "invalid HEAD"})
    if branch != "main":
        failures.setdefault("branch", {"returncode": -2, "stderr": f"expected main, got {branch!r}"})
    if not remotes:
        failures.setdefault("remotes", {"returncode": -2, "stderr": "no configured remote"})
    return {
        "ok": not failures,
        "git": str(_embedded_git(project)),
        "head": head,
        "branch": branch,
        "remotes": remotes.splitlines(),
        "fsck": outputs.get("fsck", ""),
        "failures": failures,
    }


def _active_project_mutators(root: Path) -> list[str]:
    findings: list[str] = []
    git_dir = root / ".git"
    if git_dir.is_dir():
        for lock in git_dir.rglob("*.lock"):
            if lock.is_file():
                findings.append("git-lock:" + lock.relative_to(root).as_posix())
    if os.name != "nt":
        return findings
    script = (
        "$p='" + str(root).replace("'", "''") + "'; "
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -and $_.CommandLine.IndexOf($p,[StringComparison]::OrdinalIgnoreCase) -ge 0 "
        "-and ($_.Name -match '^(git|codex)(\\.exe)?$') } | "
        "Select-Object Name,ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            parsed = json.loads(completed.stdout)
            rows = parsed if isinstance(parsed, list) else [parsed]
            for row in rows:
                findings.append(f"process:{row.get('Name')}:{row.get('ProcessId')}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        # Git lock + clean worktree checks remain authoritative if CIM is unavailable.
        pass
    return sorted(set(findings))


def source_worktree_guard(root: str | Path) -> dict[str, object]:
    project = _resolved(root)
    active = _active_project_mutators(project)
    if active:
        raise PortableCloneError("active Git/Codex operation refused: " + ", ".join(active))
    status = _git_command(project, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        raise PortableCloneError("cannot prove clean worktree: " + (status.stderr or "").strip())
    dirty = [line for line in status.stdout.splitlines() if line.strip()]
    if dirty:
        raise PortableCloneError("full clone requires a clean worktree: " + " | ".join(dirty[:20]))
    head = _git_command(project, "rev-parse", "HEAD")
    branch = _git_command(project, "branch", "--show-current")
    if head.returncode or branch.returncode:
        raise PortableCloneError("cannot capture source Git identity")
    return {
        "head": head.stdout.strip(),
        "branch": branch.stdout.strip(),
        "status": dirty,
        "active_mutators": active,
    }


def _source_file_state(root: Path, inv: CloneInventory) -> dict[str, tuple[int, int]]:
    state: dict[str, tuple[int, int]] = {}
    for planned in inv.files:
        path = root / Path(planned.relative_path)
        if _is_reparse(path):
            _assert_reparse_allowed(planned.relative_path)
        try:
            info = path.stat()
        except OSError as exc:
            raise PortableCloneError(f"source changed or disappeared: {planned.relative_path}: {exc}") from exc
        state[planned.relative_path] = (int(info.st_size), int(info.st_mtime_ns))
    return state


def _inventory_signature(inv: CloneInventory) -> tuple[tuple[str, int, str], ...]:
    return tuple((item.relative_path, item.size, item.kind) for item in inv.files)


def verify_clone(
    destination: str | Path,
    *,
    full_hash: bool = True,
    git_verifier: Callable[[str | Path], dict[str, object]] = verify_git_repository,
) -> dict[str, object]:
    root = _resolved(destination)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        return {"ok": False, "reason": "manifest_missing", "root": str(root)}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "reason": f"manifest_invalid:{exc}", "root": str(root)}
    missing: list[str] = []
    divergent: list[str] = []
    reparse_points: list[str] = []
    verified = 0
    for rel, metadata in sorted(dict(manifest.get("files", {})).items()):
        path = root / Path(rel)
        if not path.is_file():
            missing.append(rel)
            continue
        if path.stat().st_size != int(metadata.get("size", -1)):
            divergent.append(rel)
            continue
        if full_hash:
            digest, _size = _hash_file(path)
            if digest != metadata.get("sha256"):
                divergent.append(rel)
                continue
        verified += 1
    required = (
        "LANCER_HYPERSMART.cmd",
        "ANALYSER_BACKTESTS_REPLAYS.cmd",
        "POUSSER-GITHUB-FORCE.cmd",
        "CREER_ARCHIVE_PORTABLE.cmd",
        "tools/python/python.exe",
        "tools/portable_env.cmd",
        "tools/git/cmd/git.exe",
        "tools/push_github_safe.ps1",
        "src/hl_observer/__init__.py",
        "src/hl_observer/ops/portable_smoke.py",
    )
    required_missing = [rel for rel in required if not (root / rel).is_file()]
    leaks = [
        rel for rel in manifest.get("files", {})
        if any(token in rel.casefold() for token in ("c:/users/", "c:\\users\\"))
    ]
    manifest_files = set(dict(manifest.get("files", {})))
    source_machine = str(manifest.get("source_machine_fingerprint") or "")
    current_machine = machine_fingerprint()
    actual_files: set[str] = set()
    longest_path = len(str(root))
    longest_member = ""
    for directory, subdirectories, names in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        for name in list(subdirectories):
            candidate = current / name
            rel = candidate.relative_to(root).as_posix()
            if _is_reparse(candidate):
                reparse_points.append(rel + "/")
                subdirectories.remove(name)
        for name in names:
            candidate = current / name
            rel = candidate.relative_to(root).as_posix()
            if _is_reparse(candidate):
                reparse_points.append(rel)
            if rel != MANIFEST_NAME:
                actual_files.add(rel)
            length = len(str(candidate))
            if length > longest_path:
                longest_path = length
                longest_member = rel
    unexpected = sorted(actual_files - manifest_files)
    longest_path_ok = longest_path <= MAX_WINDOWS_PATH
    try:
        git = git_verifier(root)
    except Exception as exc:  # noqa: BLE001
        git = {"ok": False, "error": str(exc)}
    ok = (
        not missing
        and not divergent
        and not required_missing
        and not leaks
        and not unexpected
        and not reparse_points
        and longest_path_ok
        and bool(git.get("ok"))
    )
    return {
        "ok": ok,
        "root": str(root),
        "verified": verified,
        "full_hash": full_hash,
        "missing": missing,
        "divergent": divergent,
        "required_missing": required_missing,
        "absolute_path_leaks_in_manifest": leaks,
        "unexpected": unexpected,
        "reparse_points": sorted(reparse_points),
        "longest_path": longest_path,
        "longest_path_member": longest_member,
        "longest_path_ok": longest_path_ok,
        "long_path_recommendation": "C:\\HyperSmart" if not longest_path_ok else "",
        "git": git,
        "source_machine_fingerprint": source_machine,
        "current_machine_fingerprint": current_machine,
        "physical_machine_distinct": bool(source_machine and source_machine != current_machine),
    }


def create_full_clone(
    root: str | Path,
    destination: str | Path | None = None,
    *,
    writer_probe: Callable[[str | Path], list[str]] = AP.writers_vivants,
    session_probe: Callable[[str | Path], list[str]] = AP.sessions_actives,
    verify_hashes: bool = True,
    progress: Callable[[dict[str, object]], None] | None = None,
    worktree_guard: Callable[[str | Path], dict[str, object]] = source_worktree_guard,
    git_verifier: Callable[[str | Path], dict[str, object]] = verify_git_repository,
) -> dict[str, object]:
    source_root = _resolved(root)
    writers = list(writer_probe(source_root))
    if writers:
        raise PortableCloneError("HyperSmart writers are still active: " + ", ".join(writers))
    active_sessions = list(session_probe(source_root))
    if active_sessions:
        raise PortableCloneError("active sessions must be stopped first: " + ", ".join(active_sessions))

    source_guard_start = worktree_guard(source_root)

    inv = inventory(source_root)
    source_state_start = _source_file_state(source_root, inv)
    target = _resolved(destination) if destination else automatic_destination(inv.total_bytes)
    _validate_destination(source_root, target, inv)
    staging = target.with_name(f".{target.name}.partial-{os.getpid()}")
    if staging.exists():
        raise PortableCloneError(f"staging already exists: {staging}")
    staging.mkdir(parents=False)

    manifest_files: dict[str, dict[str, object]] = {}
    sqlite_results: list[dict[str, object]] = []
    copied_bytes = 0
    started = time.time()
    try:
        for index, planned in enumerate(inv.files, start=1):
            src = source_root / Path(planned.relative_path)
            dst = staging / Path(planned.relative_path)
            if planned.kind == "sqlite":
                result = AP.copier_sqlite_vers_staging(src, dst)
                sqlite_results.append({"path": planned.relative_path, **result})
                if not result.get("ok"):
                    raise PortableCloneError(f"SQLite backup failed for {planned.relative_path}: {result}")
                digest, size = _hash_file(dst)
            else:
                digest, size = _copy_and_hash(src, dst)
            copied_bytes += size
            manifest_files[planned.relative_path] = {
                "sha256": digest,
                "size": size,
                "kind": planned.kind,
            }
            if progress is not None:
                progress(
                    {
                        "index": index,
                        "total": len(inv.files),
                        "relative_path": planned.relative_path,
                        "copied_bytes": copied_bytes,
                        "planned_bytes": inv.total_bytes,
                    }
                )

        source_guard_end = worktree_guard(source_root)
        final_inventory = inventory(source_root, scan_private_key_content=False)
        source_state_end = _source_file_state(source_root, inv)
        if source_guard_end != source_guard_start:
            raise PortableCloneError("source Git/worktree identity changed during clone")
        if _inventory_signature(final_inventory) != _inventory_signature(inv):
            raise PortableCloneError("source inventory changed during clone")
        if source_state_end != source_state_start:
            changed = sorted(
                rel for rel, before in source_state_start.items() if source_state_end.get(rel) != before
            )
            raise PortableCloneError("source files changed during clone: " + ", ".join(changed[:20]))

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "target": "Windows 10/11 x64",
            "entrypoint": "LANCER_HYPERSMART.cmd",
            "copy_mode": "complete_disaster_recovery_clone",
            "durable_runtime_included": True,
            "git_history_included": ".git/config" in manifest_files,
            "sqlite_copy_method": "sqlite_backup_api",
            "source_guard": source_guard_end,
            "source_machine_fingerprint": machine_fingerprint(),
            "source_unchanged": True,
            "files": manifest_files,
            "excluded": list(inv.excluded),
            "excluded_policy": [
                "machine-specific PID/identity/locks",
                "SQLite WAL/SHM sidecars replaced by coherent backup",
                "generated caches and temporary files",
                "secret/private-key material",
                "links and Windows reparse points",
            ],
            "safety": "read-only market data; local paper simulation; no real execution",
        }
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        # The staging directory is the transaction boundary. Nothing appears at
        # the final target name until every file, hash, path and Git proof passes.
        staging_verification = verify_clone(
            staging,
            full_hash=verify_hashes,
            git_verifier=git_verifier,
        )
        if not staging_verification.get("ok"):
            raise PortableCloneError(
                "staging verification failed; target not published: "
                + json.dumps(staging_verification, ensure_ascii=False)
            )
        os.replace(staging, target)
        verification = verify_clone(target, full_hash=verify_hashes, git_verifier=git_verifier)
        if not verification.get("ok"):
            failed_target = target.with_name(f".{target.name}.failed-{int(time.time())}")
            os.replace(target, failed_target)
            try:
                (failed_target / "PORTABLE_CLONE_FAILED.txt").write_text(
                    "Post-publication verification failed. Do not launch this directory.\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
            raise PortableCloneError(
                "published clone verification failed and target was withdrawn: "
                + json.dumps(verification, ensure_ascii=False)
            )
    except BaseException:
        if staging.exists():
            failure = staging / "PORTABLE_CLONE_FAILED.txt"
            try:
                failure.write_text("Clone incomplete. Do not launch this directory.\n", encoding="utf-8")
            except OSError:
                pass
        raise

    return {
        "ok": True,
        "destination": str(target),
        "files": len(inv.files),
        "bytes": copied_bytes,
        "sqlite": sqlite_results,
        "excluded": len(inv.excluded),
        "elapsed_seconds": round(time.time() - started, 3),
        "verification": verification,
        "staging_verification": staging_verification,
        "manifest": str(target / MANIFEST_NAME),
    }


def _print_progress(payload: dict[str, object]) -> None:
    total = max(1, int(payload["total"]))
    index = int(payload["index"])
    if index == 1 or index == total or index % 250 == 0:
        percent = 100.0 * index / total
        rel = str(payload["relative_path"])
        print(f"[{percent:6.2f}%] {index}/{total} {rel}", flush=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Complete HyperSmart Windows disaster-recovery clone")
    parser.add_argument("--root", "--racine", dest="root", default=".")
    parser.add_argument("--destination", "--sortie", dest="destination", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", default="", help="verify an existing clone")
    parser.add_argument("--fast-verify", action="store_true", help="verify sizes without rehashing all data")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.verify:
        result = verify_clone(args.verify, full_hash=not args.fast_verify)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 4
    try:
        inv = inventory(args.root)
        destination = _resolved(args.destination) if args.destination else automatic_destination(inv.total_bytes)
        preview = {
            "source": str(_resolved(args.root)),
            "destination": str(destination),
            "files": len(inv.files),
            "bytes": inv.total_bytes,
            "gigabytes": round(inv.total_bytes / (1024 ** 3), 3),
            "sqlite": inv.sqlite_count,
            "excluded": len(inv.excluded),
            "longest_relative_path": inv.longest_relative_path,
            "longest_relative_member": inv.longest_relative_member,
        }
        if args.dry_run:
            print(json.dumps({"ok": True, "dry_run": True, **preview}, ensure_ascii=False, indent=2))
            return 0
        print(json.dumps({"phase": "inventory", **preview}, ensure_ascii=False, indent=2), flush=True)
        result = create_full_clone(
            args.root,
            destination,
            verify_hashes=not args.fast_verify,
            progress=_print_progress,
        )
        print("PORTABLE_FULL_CLONE_OK " + str(result["destination"]))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except PortableCloneError as exc:
        print("PORTABLE_FULL_CLONE_REFUSED: " + str(exc), file=sys.stderr)
        return 5
    except Exception as exc:  # noqa: BLE001
        print("PORTABLE_FULL_CLONE_ERROR: " + str(exc), file=sys.stderr)
        return 1


__all__ = [
    "CloneInventory",
    "MANIFEST_NAME",
    "PlannedFile",
    "PortableCloneError",
    "automatic_destination",
    "create_full_clone",
    "inventory",
    "main",
    "verify_clone",
    "verify_git_repository",
    "source_worktree_guard",
    "machine_fingerprint",
]


if __name__ == "__main__":
    raise SystemExit(main())
