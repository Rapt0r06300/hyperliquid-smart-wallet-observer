"""Audit guard inherited by Python processes during portable validation.

The guard is intentionally narrow: it denies network access and filesystem
mutations outside the extracted release.  It is enabled only when the
``HYPERSMART_PORTABLE_AUDIT_ROOT`` environment variable is present, so normal
runtime behaviour is unchanged.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

_INSTALLED = False
_LOCK = threading.Lock()
_WRITE_FLAGS = (
    getattr(os, "O_WRONLY", 0)
    | getattr(os, "O_RDWR", 0)
    | getattr(os, "O_APPEND", 0)
    | getattr(os, "O_CREAT", 0)
    | getattr(os, "O_TRUNC", 0)
)
_MUTATION_EVENTS = {
    "os.remove",
    "os.rename",
    "os.replace",
    "os.rmdir",
    "os.mkdir",
    "os.chmod",
    "os.chown",
    "os.truncate",
    "os.utime",
    "shutil.copyfile",
    "shutil.copymode",
    "shutil.copystat",
}
_NETWORK_EVENTS = {
    "socket.bind",
    "socket.connect",
    "socket.connect_ex",
    "socket.getaddrinfo",
    "socket.gethostbyaddr",
    "socket.gethostbyname",
    "socket.gethostbyname_ex",
}


def _inside(path: Any, root: Path) -> bool:
    if isinstance(path, int) or path is None:
        return True
    try:
        decoded = os.fsdecode(path)
    except (TypeError, ValueError):
        return True
    # Windows logging libraries legitimately open the null device as either
    # ``NUL`` or ``\\.\NUL``.  It is a kernel sink, not a persistent write
    # outside the extraction, so denying it makes the hermetic pytest run fail
    # without strengthening the filesystem boundary.
    if os.name == "nt":
        device = decoded.strip().replace("/", "\\").rstrip("\\").upper()
        if device in {"NUL", r"\\.\NUL", r"\\?\NUL", r"\??\NUL"}:
            return True
    candidate = Path(decoded)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        candidate.resolve(strict=False).relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def _record(log_path: Path, event: str, args: tuple[Any, ...]) -> None:
    payload = {
        "event": event,
        "pid": os.getpid(),
        "args": [repr(value)[:500] for value in args],
    }
    try:
        with _LOCK, log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
    except OSError:
        pass


def _open_is_write(args: tuple[Any, ...]) -> bool:
    mode = args[1] if len(args) > 1 else "r"
    flags = args[2] if len(args) > 2 else 0
    if isinstance(mode, str) and any(marker in mode for marker in ("w", "a", "x", "+")):
        return True
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def install(root: str | Path, log_path: str | Path) -> None:
    """Install the fail-closed audit hook once in the current interpreter."""
    global _INSTALLED
    if _INSTALLED:
        return
    audit_root = Path(root).resolve()
    audit_log = Path(log_path).resolve()
    try:
        audit_log.relative_to(audit_root)
    except ValueError as exc:
        raise ValueError("portable audit log must live inside extraction") from exc

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event in _NETWORK_EVENTS:
            _record(audit_log, event, args)
            raise PermissionError("portable hermetic validation denies network: %s" % event)
        paths: tuple[Any, ...] = ()
        if event == "open" and _open_is_write(args):
            paths = args[:1]
        elif event in _MUTATION_EVENTS:
            paths = args[:2] if event in {
                "os.rename", "os.replace", "shutil.copyfile", "shutil.copymode", "shutil.copystat",
            } else args[:1]
        for path in paths:
            if not _inside(path, audit_root):
                _record(audit_log, event, args)
                raise PermissionError(
                    "portable hermetic validation denies external write: %s" % path
                )

    sys.addaudithook(hook)
    _INSTALLED = True


def install_from_environment() -> bool:
    root = os.environ.get("HYPERSMART_PORTABLE_AUDIT_ROOT", "").strip()
    log = os.environ.get("HYPERSMART_PORTABLE_AUDIT_LOG", "").strip()
    if not root or not log:
        return False
    install(root, log)
    return True


__all__ = ["install", "install_from_environment"]
