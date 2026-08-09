from __future__ import annotations

from pathlib import Path

from hl_observer.ops.port_owner import ERROR, FOREIGN, FREE, HYPERSMART, inspect_port_owner


def test_port_is_free_without_listener(tmp_path: Path) -> None:
    status = inspect_port_owner(tmp_path, listener_pids=lambda _port: [])
    assert status.state == FREE


def test_registered_hypersmart_ui_listener_is_accepted(tmp_path: Path) -> None:
    command = f'python -m hl_observer ui --root "{tmp_path}"'
    status = inspect_port_owner(
        tmp_path,
        listener_pids=lambda _port: [321],
        process_info=lambda _pid: {"command": command, "executable": "python.exe"},
        registered_ui_pid=321,
    )
    assert status.state == HYPERSMART
    assert status.pid == 321


def test_foreign_listener_is_never_accepted(tmp_path: Path) -> None:
    status = inspect_port_owner(
        tmp_path,
        listener_pids=lambda _port: [654],
        process_info=lambda _pid: {"command": "python foreign_server.py", "executable": "C:/Python/python.exe"},
    )
    assert status.state == FOREIGN


def test_ui_signature_from_another_checkout_is_foreign(tmp_path: Path) -> None:
    status = inspect_port_owner(
        tmp_path,
        listener_pids=lambda _port: [777],
        process_info=lambda _pid: {
            "command": 'C:\\Other\\python.exe -m hl_observer ui --root C:\\Other\\Project',
            "executable": "C:\\Other\\python.exe",
        },
    )
    assert status.state == FOREIGN


def test_listener_inspection_error_fails_closed(tmp_path: Path) -> None:
    def fail(_port: int):
        raise RuntimeError("inspection unavailable")

    status = inspect_port_owner(tmp_path, listener_pids=fail)
    assert status.state == ERROR


def test_launcher_and_powershell_use_verified_port_ownership() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="replace")
    powershell = (root / "tools" / "start_hypersmart_simulation.ps1").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "hl_observer.ops.port_owner" in launcher
    assert "Test-HyperSmartUiProcess" in powershell
    port_block = powershell[powershell.index("$portPids =") : powershell.index("# FILET DE SECURITE")]
    assert "Test-HyperSmartUiProcess" in port_block
    assert "Refusing to stop foreign port owner" in port_block

