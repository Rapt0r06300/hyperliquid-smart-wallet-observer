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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HyperSmart portable runtime diagnostics")
    parser.add_argument("--root", default=str(project_root_from_file()))
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="verify Python and runtime imports")
    check.add_argument("--json", action="store_true", dest="as_json")
    check.add_argument("--require-embedded", action="store_true")

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

    payload = load_manifest(root)
    if payload is None:
        print("portable runtime manifest: MISSING")
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
