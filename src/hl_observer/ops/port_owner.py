"""Fail-closed ownership check for the local HyperSmart UI port.

An occupied port is not proof that HyperSmart is already running.  This module
accepts a listener only when its process has the UI command signature and is
anchored to the current project (command line, executable, or registered UI
PID).  Unknown listeners remain foreign and must never be stopped by the
launcher.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from hl_observer.ops.registre_pids import lire_registre

FREE = "FREE"
HYPERSMART = "HYPERSMART"
FOREIGN = "FOREIGN"
ERROR = "ERROR"
_UI_SIGNATURES = ("-m hl_observer ui", "hl_observer ui")


@dataclass(frozen=True)
class PortOwnerStatus:
    state: str
    port: int
    pid: int | None = None
    reason: str = ""
    command: str = ""


def _norm(value: str | Path) -> str:
    try:
        return str(Path(value).resolve()).replace("/", "\\").rstrip("\\").casefold()
    except (OSError, ValueError):
        return str(value).replace("/", "\\").rstrip("\\").casefold()


def _registered_ui_pid(root: Path) -> int | None:
    meta = dict(lire_registre(root).get("composants") or {}).get("ui")
    pid = meta.get("pid") if isinstance(meta, Mapping) else None
    return int(pid) if isinstance(pid, int) else None


def _default_listener_pids(port: int) -> list[int]:
    import psutil

    found: set[int] = set()
    for conn in psutil.net_connections(kind="tcp"):
        if not conn.laddr or int(conn.laddr.port) != int(port):
            continue
        if str(conn.status).upper() != "LISTEN" or conn.pid is None:
            continue
        found.add(int(conn.pid))
    return sorted(found)


def _default_process(pid: int) -> dict[str, Any]:
    import psutil

    proc = psutil.Process(int(pid))
    with proc.oneshot():
        return {
            "pid": int(pid),
            "command": " ".join(proc.cmdline() or []),
            "executable": proc.exe() or "",
            "name": proc.name() or "",
        }


def inspect_port_owner(
    root: str | Path,
    *,
    port: int = 8794,
    listener_pids: Callable[[int], Sequence[int]] = _default_listener_pids,
    process_info: Callable[[int], Mapping[str, Any]] = _default_process,
    registered_ui_pid: int | None = None,
) -> PortOwnerStatus:
    project = Path(root).resolve()
    try:
        pids = [int(pid) for pid in listener_pids(int(port))]
    except Exception as exc:  # fail closed: inability to inspect is not FREE
        return PortOwnerStatus(ERROR, int(port), reason=f"listener inspection failed: {exc}")
    if not pids:
        return PortOwnerStatus(FREE, int(port), reason="no TCP listener")

    registered = registered_ui_pid if registered_ui_pid is not None else _registered_ui_pid(project)
    root_text = _norm(project)
    foreign: list[str] = []
    for pid in pids:
        try:
            info = dict(process_info(pid))
        except Exception as exc:
            foreign.append(f"pid={pid}: process inspection failed: {exc}")
            continue
        command = str(info.get("command") or info.get("cmd") or "")
        executable = str(info.get("executable") or info.get("exe") or "")
        cmd_fold = command.casefold()
        has_ui_signature = any(signature in cmd_fold for signature in _UI_SIGNATURES)
        anchored = root_text in _norm(command) or root_text in _norm(executable)
        registered_match = registered is not None and int(registered) == pid
        if has_ui_signature and (anchored or registered_match):
            why = "registered UI PID" if registered_match else "UI signature anchored to project"
            return PortOwnerStatus(HYPERSMART, int(port), pid, why, command[:500])
        foreign.append(
            f"pid={pid}: missing verified HyperSmart UI ownership "
            f"(signature={has_ui_signature}, anchored={anchored}, registered={registered_match})"
        )
    return PortOwnerStatus(FOREIGN, int(port), pids[0], "; ".join(foreign))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify ownership of the HyperSmart UI port")
    parser.add_argument("--root", default=".")
    parser.add_argument("--port", type=int, default=8794)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    status = inspect_port_owner(args.root, port=args.port)
    if args.json:
        print(json.dumps(asdict(status), ensure_ascii=False))
    else:
        print(f"PORT_OWNER={status.state} port={status.port} pid={status.pid or '-'} reason={status.reason}")
    return {FREE: 0, HYPERSMART: 2, FOREIGN: 3, ERROR: 4}[status.state]


if __name__ == "__main__":
    raise SystemExit(main())

