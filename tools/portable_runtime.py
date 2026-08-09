"""Portable Windows runtime diagnostics for HyperSmart.

The only release runtime is ``tools/python/python.exe``.  A legacy
``portable_runtime/python`` tree may be copied once by :func:`migrate_legacy_runtime`,
but it is never selected as a runtime and is never part of an official archive.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

PORTABLE_DIR = "tools"
PORTABLE_PYTHON_RELATIVE = Path("tools") / "python" / "python.exe"
PORTABLE_MANIFEST_RELATIVE = Path("tools") / "python" / "portable_runtime_manifest.json"
LEGACY_PYTHON_RELATIVE = Path("portable_runtime") / "python"
LEGACY_MANIFEST_RELATIVE = Path("portable_runtime") / "portable_runtime_manifest.json"

REQUIRED_IMPORTS: tuple[str, ...] = (
    "fastapi",
    "httpx",
    "pydantic",
    "sqlalchemy",
    "typer",
    "uvicorn",
    "websocket",
    "websockets",
    "yaml",
    "psutil",
    "rich",
    "numpy",
)

REQUIRED_RELOCATION_FILES: tuple[str, ...] = (
    "LANCER_HYPERSMART.cmd",
    "ANALYSER_BACKTESTS_REPLAYS.cmd",
    "POUSSER-GITHUB-FORCE.cmd",
    "CREER_ARCHIVE_PORTABLE.cmd",
    "tools/portable_env.cmd",
    "tools/python/python.exe",
    "tools/python/python314._pth",
    "tools/git/cmd/git.exe",
    "tools/push_github_safe.ps1",
    "src/hl_observer/__init__.py",
    "src/hl_observer/ops/premier_lancement.py",
    "src/hl_observer/ops/portable_smoke.py",
    "tools/start_hypersmart_simulation.ps1",
)

_ACTIVE_TEXT_SUFFIXES = frozenset(
    {".cmd", ".conf", ".ini", ".json", ".ps1", ".py", ".toml", ".yaml", ".yml"}
)
_USER_ABSOLUTE_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/](?:Users|Documents and Settings)[\\/][^\"'\r\n]+"
)

EXCLUDED_TOP_LEVEL: frozenset[str] = frozenset(
    {
        ".git",
        ".hypothesis",
        ".mypy_cache",
        ".pytest_cache",
        ".refact",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "data",
        "dist",
        "env",
        "logs",
        "node_modules",
        "portable_runtime",
        "reports",
        "runtime",
        "venv",
    }
)

EXCLUDED_SUFFIXES: tuple[str, ...] = (
    ".7z",
    ".db",
    ".db-shm",
    ".db-wal",
    ".log",
    ".p12",
    ".pfx",
    ".pyc",
    ".rar",
    ".sqlite",
    ".sqlite3",
    ".sqlite3-shm",
    ".sqlite3-wal",
    ".tmp",
    ".zip",
)


@dataclass(frozen=True)
class PythonSelection:
    executable: str
    source: str
    portable: bool


@dataclass(frozen=True)
class RuntimeStatus:
    project_root: str
    platform: str
    machine: str
    selected_python: str | None
    selected_source: str | None
    portable_python_exists: bool
    portable_manifest_exists: bool
    probe_ok: bool
    python_version: str | None
    missing_imports: tuple[str, ...]
    external_path_leaks: tuple[str, ...]
    error: str | None


@dataclass(frozen=True)
class RelocationStatus:
    project_root: str
    target: str
    platform_ok: bool
    architecture_ok: bool
    writable: bool
    embedded_runtime_ok: bool
    relative_launcher_ok: bool
    relative_python_paths_ok: bool
    first_launch_regeneration_ok: bool
    required_files_missing: tuple[str, ...]
    hardcoded_user_paths: tuple[str, ...]
    absolute_python_path_entries: tuple[str, ...]
    recommendations: tuple[str, ...]
    ok: bool


def project_root_from_file() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def is_within(path: Path, parent: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(parent))
    except ValueError:
        return False
    return True


def validate_output_outside_project(project_root: Path, output: Path) -> Path:
    resolved = _resolved(output)
    if is_within(resolved, project_root):
        raise ValueError("portable bundle output must be outside the project")
    return resolved


def is_safe_bundle_member(relative_path: str | Path) -> bool:
    normalized = str(relative_path).replace("\\", "/").lstrip("/")
    if not normalized:
        return False
    parts = tuple(part.lower() for part in normalized.split("/") if part)
    if not parts:
        return False
    if parts[0] in EXCLUDED_TOP_LEVEL:
        return False
    lower = normalized.lower()
    if lower == ".env" or lower.endswith("/.env"):
        return False
    if any(part == "__pycache__" for part in parts):
        return False
    if (
        len(parts) == 3
        and parts[0] == "tools"
        and parts[1] == "python"
        and parts[2].startswith("python")
        and parts[2].endswith(".zip")
        and parts[2][6:-4].isdigit()
    ):
        return True
    if lower.endswith(EXCLUDED_SUFFIXES):
        return False
    return True


def select_python(
    project_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    path_candidates: Sequence[str] | None = None,
) -> PythonSelection | None:
    """Select only the embedded release interpreter.

    ``environ`` and ``path_candidates`` remain accepted for API compatibility;
    they deliberately cannot influence the official selection.
    """
    del environ, path_candidates
    root = _resolved(project_root)
    portable = root / PORTABLE_PYTHON_RELATIVE
    if portable.is_file():
        return PythonSelection(str(portable), "embedded-tools-python", True)
    return None


def migrate_legacy_runtime(project_root: Path) -> dict[str, object]:
    """Copy a valid legacy runtime to ``tools/python`` without deleting it.

    Copying through a sibling temporary directory prevents a half-migrated
    runtime from being selected after an interrupted operation.
    """
    root = _resolved(project_root)
    destination = root / PORTABLE_PYTHON_RELATIVE.parent
    legacy = root / LEGACY_PYTHON_RELATIVE
    if (destination / "python.exe").is_file():
        return {"migrated": False, "reason": "already_present", "destination": str(destination)}
    if not (legacy / "python.exe").is_file():
        return {"migrated": False, "reason": "legacy_missing", "destination": str(destination)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="python-migration-", dir=str(destination.parent)))
    try:
        shutil.copytree(legacy, temporary / "python", dirs_exist_ok=True)
        legacy_manifest = root / LEGACY_MANIFEST_RELATIVE
        if legacy_manifest.is_file():
            shutil.copy2(legacy_manifest, temporary / "python" / "portable_runtime_manifest.json")
        if not (temporary / "python" / "python.exe").is_file():
            raise RuntimeError("legacy runtime copy is missing python.exe")
        (temporary / "python").replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    return {"migrated": True, "reason": "legacy_copied", "destination": str(destination)}


def load_manifest(project_root: Path) -> dict[str, object] | None:
    path = _resolved(project_root) / PORTABLE_MANIFEST_RELATIVE
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def probe_python(executable: Path, *, timeout_seconds: float = 30.0) -> dict[str, object]:
    imports_json = json.dumps(REQUIRED_IMPORTS)
    code = (
        "import importlib,json,os,platform,sys\n"
        f"names={imports_json}\n"
        "missing=[]\n"
        "for name in names:\n"
        "    try: importlib.import_module(name)\n"
        "    except Exception as exc: missing.append(name + ':' + type(exc).__name__)\n"
        "root=os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(sys.executable),'..','..')))\n"
        "stdlib=os.path.normcase(os.path.abspath(os.path.dirname(sys.executable)))\n"
        "allowed=(root,stdlib)\n"
        "leaks=[]\n"
        "for item in sys.path:\n"
        "    if not item or item.startswith('__editable__'): continue\n"
        "    resolved=os.path.normcase(os.path.abspath(item))\n"
        "    if not any(resolved == base or resolved.startswith(base + os.sep) for base in allowed):\n"
        "        leaks.append(item)\n"
        "print(json.dumps({'version':platform.python_version(),"
        "'machine':platform.machine(),'missing':missing,'external_path_leaks':leaks,"
        "'executable':sys.executable}))\n"
    )
    completed = subprocess.run(
        [str(executable), "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail or f"python probe failed with code {completed.returncode}")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("python probe produced no output")
    payload = json.loads(lines[-1])
    if not isinstance(payload, dict):
        raise RuntimeError("python probe returned an invalid payload")
    return payload


def runtime_status(project_root: Path, *, require_embedded: bool = False) -> RuntimeStatus:
    root = _resolved(project_root)
    portable_python = root / PORTABLE_PYTHON_RELATIVE
    selection = select_python(root)
    manifest_exists = (root / PORTABLE_MANIFEST_RELATIVE).is_file()
    if selection is None:
        return RuntimeStatus(
            project_root=str(root),
            platform=platform.system(),
            machine=platform.machine(),
            selected_python=None,
            selected_source=None,
            portable_python_exists=portable_python.is_file(),
            portable_manifest_exists=manifest_exists,
            probe_ok=False,
            python_version=None,
            missing_imports=(),
            external_path_leaks=(),
            error="no Python interpreter found",
        )
    if require_embedded and not selection.portable:
        return RuntimeStatus(
            project_root=str(root),
            platform=platform.system(),
            machine=platform.machine(),
            selected_python=selection.executable,
            selected_source=selection.source,
            portable_python_exists=False,
            portable_manifest_exists=manifest_exists,
            probe_ok=False,
            python_version=None,
            missing_imports=(),
            external_path_leaks=(),
            error="embedded portable runtime is required",
        )
    try:
        result = probe_python(Path(selection.executable))
        missing = tuple(str(item) for item in result.get("missing", ()))
        leaks = tuple(str(item) for item in result.get("external_path_leaks", ()))
        probe_ok = not missing and (not selection.portable or not leaks)
        return RuntimeStatus(
            project_root=str(root),
            platform=platform.system(),
            machine=platform.machine(),
            selected_python=selection.executable,
            selected_source=selection.source,
            portable_python_exists=portable_python.is_file(),
            portable_manifest_exists=manifest_exists,
            probe_ok=probe_ok,
            python_version=str(result.get("version") or ""),
            missing_imports=missing,
            external_path_leaks=leaks,
            error=(
                "required imports are missing"
                if missing
                else "portable Python imports packages outside the project"
                if leaks
                else None
            ),
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return RuntimeStatus(
            project_root=str(root),
            platform=platform.system(),
            machine=platform.machine(),
            selected_python=selection.executable,
            selected_source=selection.source,
            portable_python_exists=portable_python.is_file(),
            portable_manifest_exists=manifest_exists,
            probe_ok=False,
            python_version=None,
            missing_imports=(),
            external_path_leaks=(),
            error=str(exc),
        )


def _iter_active_text_files(root: Path):
    """Yield runtime-relevant text files, never history, datasets or vendored Python."""
    for path in sorted(root.glob("*.cmd")):
        if path.is_file():
            yield path
    for path in sorted(root.glob("*.ps1")):
        if path.is_file():
            yield path
    for top in (root / "src", root / "config", root / "tools"):
        if not top.is_dir():
            continue
        for directory, subdirectories, names in os.walk(top, topdown=True):
            current = Path(directory)
            subdirectories[:] = [
                name
                for name in subdirectories
                if name.casefold()
                not in {"__pycache__", ".git", "python", "wheelhouse", "github_repos_v24"}
            ]
            for name in names:
                path = current / name
                if path.suffix.casefold() not in _ACTIVE_TEXT_SUFFIXES:
                    continue
                try:
                    if path.stat().st_size <= 2 * 1024 * 1024:
                        yield path
                except OSError:
                    continue


def scan_hardcoded_user_paths(project_root: Path) -> tuple[str, ...]:
    """Find user-specific absolute paths in files used by the active runtime."""
    root = _resolved(project_root)
    leaks: list[str] = []
    for path in _iter_active_text_files(root):
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        suffix = path.suffix.casefold()
        for number, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if suffix == ".cmd" and (stripped.casefold().startswith("rem ") or stripped.startswith("::")):
                continue
            if suffix in {".py", ".ps1"} and stripped.startswith("#"):
                continue
            if _USER_ABSOLUTE_PATH.search(line):
                leaks.append(f"{path.relative_to(root).as_posix()}:{number}")
    return tuple(sorted(set(leaks)))


def _absolute_python_path_entries(project_root: Path) -> tuple[str, ...]:
    pth = _resolved(project_root) / "tools" / "python" / "python314._pth"
    if not pth.is_file():
        return ("tools/python/python314._pth:MISSING",)
    absolute: list[str] = []
    for line in pth.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        value = line.strip()
        if not value or value.startswith("#") or value.startswith("import "):
            continue
        if Path(value).is_absolute() or re.match(r"^[A-Za-z]:[\\/]", value):
            absolute.append(value)
    return tuple(absolute)


def _launcher_is_relative(project_root: Path) -> bool:
    root = _resolved(project_root)
    launcher = root / "LANCER_HYPERSMART.cmd"
    env = root / "tools" / "portable_env.cmd"
    if not launcher.is_file() or not env.is_file():
        return False
    launcher_text = launcher.read_text(encoding="utf-8-sig", errors="replace").casefold()
    env_text = env.read_text(encoding="utf-8-sig", errors="replace").casefold()
    return (
        'cd /d "%~dp0"' in launcher_text
        and 'call "%~dp0tools\\portable_env.cmd"' in launcher_text
        and "%~dp0" in env_text
        and "tools\\python\\python.exe" in env_text
    )


def _root_is_writable(project_root: Path) -> bool:
    root = _resolved(project_root)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".hypersmart-portable-", suffix=".tmp", dir=root, delete=True
        ) as stream:
            stream.write("portable-write-check\n")
            stream.flush()
        return True
    except OSError:
        return False


def relocation_status(project_root: Path, *, check_writable: bool = True) -> RelocationStatus:
    """Validate that a raw folder copy can boot from a different Windows path."""
    root = _resolved(project_root)
    runtime = runtime_status(root, require_embedded=True)
    missing = tuple(rel for rel in REQUIRED_RELOCATION_FILES if not (root / Path(rel)).is_file())
    hardcoded = scan_hardcoded_user_paths(root)
    absolute_pth = _absolute_python_path_entries(root)
    launcher_ok = _launcher_is_relative(root)
    first_launch_ok = (
        (root / "src" / "hl_observer" / "ops" / "premier_lancement.py").is_file()
        and "premier_lancement --racine \"%~dp0.\""
        in (root / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8-sig", errors="replace")
    ) if (root / "LANCER_HYPERSMART.cmd").is_file() else False
    system = platform.system()
    machine = platform.machine().casefold()
    platform_ok = system == "Windows"
    architecture_ok = machine in {"amd64", "x86_64"}
    writable = _root_is_writable(root) if check_writable else True
    recommendations = (
        "Stop HyperSmart cleanly before copying or archiving the whole folder.",
        "Include hidden files, .git, tools/python, tools/git, runtime, data and logs.",
        "Extract to a short writable path such as C:\\HyperSmart or D:\\HyperSmart.",
        "Do not use a GitHub source ZIP as a disaster-recovery copy.",
    )
    ok = all(
        (
            platform_ok,
            architecture_ok,
            writable,
            runtime.probe_ok,
            launcher_ok,
            not absolute_pth,
            first_launch_ok,
            not missing,
            not hardcoded,
        )
    )
    return RelocationStatus(
        project_root=str(root),
        target="Windows 10/11 x64",
        platform_ok=platform_ok,
        architecture_ok=architecture_ok,
        writable=writable,
        embedded_runtime_ok=runtime.probe_ok,
        relative_launcher_ok=launcher_ok,
        relative_python_paths_ok=not absolute_pth,
        first_launch_regeneration_ok=first_launch_ok,
        required_files_missing=missing,
        hardcoded_user_paths=hardcoded,
        absolute_python_path_entries=absolute_pth,
        recommendations=recommendations,
        ok=ok,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HyperSmart portable runtime diagnostics")
    parser.add_argument("--root", default=str(project_root_from_file()))
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="verify Python and runtime imports")
    check.add_argument("--json", action="store_true", dest="as_json")
    check.add_argument("--require-embedded", action="store_true")

    relocate = subparsers.add_parser(
        "relocate-check", help="verify that a raw folder copy can start from another Windows path"
    )
    relocate.add_argument("--json", action="store_true", dest="as_json")
    relocate.add_argument("--skip-write-check", action="store_true")

    manifest = subparsers.add_parser("manifest", help="print the portable runtime manifest")
    manifest.add_argument("--json", action="store_true", dest="as_json")
    subparsers.add_parser("migrate", help="copy a legacy runtime to tools/python")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = Path(args.root)
    if args.command == "migrate":
        result = migrate_legacy_runtime(root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["reason"] != "legacy_missing" else 1
    if args.command == "check":
        status = runtime_status(root, require_embedded=bool(args.require_embedded))
        payload = asdict(status)
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"project_root: {status.project_root}")
            print(f"python: {status.selected_python or 'MISSING'}")
            print(f"source: {status.selected_source or 'MISSING'}")
            print(f"version: {status.python_version or 'UNKNOWN'}")
            print(f"portable: {'YES' if status.portable_python_exists else 'NO'}")
            print(f"imports: {'OK' if status.probe_ok else 'FAILED'}")
            if status.missing_imports:
                print("missing: " + ", ".join(status.missing_imports))
            if status.external_path_leaks:
                print("external_paths: " + ", ".join(status.external_path_leaks))
            if status.error:
                print("error: " + status.error)
        return 0 if status.probe_ok else 1
    if args.command == "relocate-check":
        status = relocation_status(root, check_writable=not bool(args.skip_write_check))
        payload = asdict(status)
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"project_root: {status.project_root}")
            print(f"target: {status.target}")
            print(f"embedded_runtime: {'OK' if status.embedded_runtime_ok else 'FAILED'}")
            print(f"relative_launcher: {'OK' if status.relative_launcher_ok else 'FAILED'}")
            print(f"relative_python_paths: {'OK' if status.relative_python_paths_ok else 'FAILED'}")
            print(f"first_launch_regeneration: {'OK' if status.first_launch_regeneration_ok else 'FAILED'}")
            print(f"writable: {'YES' if status.writable else 'NO'}")
            if status.required_files_missing:
                print("missing: " + ", ".join(status.required_files_missing))
            if status.hardcoded_user_paths:
                print("hardcoded_user_paths: " + ", ".join(status.hardcoded_user_paths))
            if status.absolute_python_path_entries:
                print("absolute_python_paths: " + ", ".join(status.absolute_python_path_entries))
            print("verdict: " + ("PORTABLE" if status.ok else "NOT_PORTABLE"))
        return 0 if status.ok else 1

    payload = load_manifest(root)
    if payload is None:
        print("portable runtime manifest: MISSING")
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
