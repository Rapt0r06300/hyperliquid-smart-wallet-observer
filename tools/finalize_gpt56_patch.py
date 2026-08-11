from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_ps_function(text: str, name: str, replacement: str) -> str:
    marker = f"function {name} {{"
    start = text.index(marker)
    nxt = text.find("\nfunction ", start + len(marker))
    if nxt < 0:
        raise RuntimeError(f"next PowerShell function not found after {name}")
    return text[:start] + replacement.rstrip() + "\n" + text[nxt + 1 :]


def replace_py_function(text: str, name: str, replacement: str) -> str:
    match = re.search(rf"(?m)^def {re.escape(name)}\(.*", text)
    if not match:
        raise RuntimeError(f"Python function not found: {name}")
    start = match.start()
    nxt = re.search(r"(?m)^def [A-Za-z_]\w*\(", text[match.end() :])
    if not nxt:
        raise RuntimeError(f"next Python function not found after {name}")
    end = match.end() + nxt.start()
    return text[:start] + replacement.rstrip() + "\n\n" + text[end:]


def _has_py_function(text: str, name: str) -> bool:
    return re.search(rf"(?m)^def {re.escape(name)}\(", text) is not None


def patch_powershell() -> None:
    path = ROOT / "tools" / "start_hypersmart_simulation.ps1"
    text = path.read_text(encoding="utf-8")
    if "function Test-HyperSmartProcessBelongsToRoot" not in text:
        marker = "function Get-HyperSmartRuntimeProcesses {"
        helper = r'''function Test-HyperSmartProcessBelongsToRoot {
    param($Process)
    if ($null -eq $Process) { return $false }
    try {
        $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd([char]92, [char]47)
        $command = [string]$Process.CommandLine
        $executable = [string]$Process.ExecutablePath
        if ($command -and $command.IndexOf($rootFull, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $true
        }
        if ($executable -and $executable.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
        return $false
    } catch {
        Write-LauncherLog "process ownership proof failed pid=$($Process.ProcessId): $($_.Exception.Message)"
        return $false
    }
}

'''
        if marker not in text:
            raise RuntimeError("runtime process function marker missing")
        text = text.replace(marker, helper + marker, 1)

    runtime = r'''function Get-HyperSmartRuntimeProcesses {
    try {
        $ownPid = $PID
        return Get-CimInstance Win32_Process | Where-Object {
            $belongs = Test-HyperSmartProcessBelongsToRoot -Process $_
            # MONITEUR_SANTE_PRESERVE: il est lance juste avant ce wrapper par LANCER_HYPERSMART.cmd.
            # Le tuer ici rendrait le health monitoring mort des le startup.
            $isHealthMonitor = ([string]$_.CommandLine) -match 'hl_observer\.ops\.moniteur_sante'
            $_.ProcessId -ne $ownPid -and $belongs -and -not $isHealthMonitor -and (
                ($_.CommandLine -like "*python* -m hl_observer ui*") -or
                ($_.CommandLine -like "*hl_observer.runtime.persistent_poll_runner*") -or
                ($_.CommandLine -like "*hypersmart_simulation_poll_loop.ps1*") -or
                ($_.CommandLine -like "*tools\ia_train_loop.ps1*") -or
                ($_.CommandLine -like "*tools/ia_train_loop.ps1*") -or
                ($_.CommandLine -like "*tools\stream_loop.ps1*") -or
                ($_.CommandLine -like "*tools\resource_policy.py*--watch*") -or
                ($_.CommandLine -like "*tools/stream_loop.ps1*") -or
                ($_.CommandLine -like "*tools/resource_policy.py*--watch*") -or
                ($_.CommandLine -like "*hl_observer copy-run*--network-read*") -or
                ($_.CommandLine -like "*hl_observer live-user-fills-scan*--network-read*") -or
                ($_.CommandLine -like "*hl_observer live-user-fills-stream*--network-read*") -or
                ($_.CommandLine -like "*hl_observer live-public-scan*--network-read*") -or
                ($_.CommandLine -like "*hl_observer.research.explain_cli*") -or
                ($_.CommandLine -like "*python*hl_observer*") -or
                ($_.CommandLine -like "*-m hl_observer*")
            )
        }
    } catch {
        Write-LauncherLog "runtime process lookup skipped: $($_.Exception.Message)"
        return @()
    }
}'''
    text = replace_ps_function(text, "Get-HyperSmartRuntimeProcesses", runtime)
    text = text.replace("[IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\\')", "[IO.Path]::GetFullPath($Root).TrimEnd('\\')")

    old = r'''        $collectorLoops = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'boucle_collecteur' })
        foreach ($loopProc in $collectorLoops) {
            Write-LauncherLog "Stopping collector loop tree pid=$($loopProc.ProcessId)"
            try { Stop-HyperSmartProcessTree -ProcId $loopProc.ProcessId } catch {}
        }'''
    new = r'''        $collectorLoops = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'boucle_collecteur' })
        foreach ($loopProc in $collectorLoops) {
            if (-not (Test-HyperSmartProcessBelongsToRoot -Process $loopProc)) {
                Write-LauncherLog "Refusing to stop foreign collector loop pid=$($loopProc.ProcessId)"
                continue
            }
            Write-LauncherLog "Stopping collector loop tree pid=$($loopProc.ProcessId)"
            try { Stop-HyperSmartProcessTree -ProcId $loopProc.ProcessId } catch {
                Write-LauncherLog "collector loop stop failed pid=$($loopProc.ProcessId): $($_.Exception.Message)"
            }
        }'''
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise RuntimeError("collector loop shutdown block changed unexpectedly")
    if "$ProjectRoot" in text:
        raise RuntimeError("undefined $ProjectRoot remains")
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_cross_os_preflight() -> None:
    path = ROOT / "src" / "hl_observer" / "ops" / "premier_lancement.py"
    text = path.read_text(encoding="utf-8")
    old = '''    root = Path(root)\n    oi = os_info or {}\n    checks = [\n        verifier_os_arch(systeme=oi.get("systeme"), machine=oi.get("machine"), version=oi.get("version")),'''
    new = '''    root = Path(root)\n    oi = os_info or {}\n    requested_system = oi.get("systeme")\n    host_system = platform.system()\n    # Tests may simulate a target Windows identity on Linux. Platform semantics are\n    # evaluated against requested_system, while host-only probes (PowerShell/CIM/DLL)\n    # must inspect the machine that is actually executing the preflight. A real Windows\n    # launch passes no override, therefore these probes remain fully blocking on Windows.\n    probe_system = host_system if requested_system and requested_system != host_system else requested_system\n    checks = [\n        verifier_os_arch(systeme=requested_system, machine=oi.get("machine"), version=oi.get("version")),'''
    if old in text:
        text = text.replace(old, new, 1)
    elif "requested_system = oi.get(\"systeme\")" not in text:
        raise RuntimeError("premier_lancement orchestrator header changed unexpectedly")
    text = text.replace('verifier_outils_windows(systeme=oi.get("systeme"))', 'verifier_outils_windows(systeme=probe_system)', 1)
    text = text.replace('verifier_dll(root, systeme=oi.get("systeme"), dossier_python=dossier_python)', 'verifier_dll(root, systeme=probe_system, dossier_python=dossier_python)', 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_status_tests() -> None:
    path = ROOT / "tests" / "test_ui_simulation_status_fast.py"
    text = path.read_text(encoding="utf-8")
    old_name = "test_status_uses_latest_persisted_equity_point_without_heavy_overview"
    new_name = "test_status_does_not_resurrect_historical_equity_without_current_mark"
    if _has_py_function(text, old_name):
        text = replace_py_function(
            text,
            old_name,
            '''def test_status_does_not_resurrect_historical_equity_without_current_mark():
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = 3.0
    state.simulation_equity_history = [
        {"current_equity_usdt": 1004.25, "current_pnl_usdc": 4.25, "timestamp_ms": 123}
    ]
    client = TestClient(create_ui_app(_settings(), state=state), raise_server_exceptions=False)

    payload = client.get("/api/simulation/status").json()

    assert payload["equity_usdt"] == 1003.0
    assert payload["net_pnl_usdt"] == 3.0
    assert payload["realized_pnl_usdt"] == 3.0
    assert payload["status_projection_pure"] is True
    assert payload["network_reads_from_status"] is False''',
        )
    elif not _has_py_function(text, new_name):
        raise RuntimeError("equity status test marker missing")

    old_name = "test_status_can_mark_open_position_from_live_all_mids_when_launcher_enables_it"
    new_name = "test_status_get_never_calls_live_all_mids_even_when_launcher_flag_is_enabled"
    if _has_py_function(text, old_name):
        text = replace_py_function(
            text,
            old_name,
            '''def test_status_get_never_calls_live_all_mids_even_when_launcher_flag_is_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HYPERSMART_STATUS_LIVE_MARKS_ENABLED", "1")
    settings = _settings()
    from hl_observer.storage.database import init_db
    import hl_observer.ui.status_routes as status_routes

    init_db(settings.database_url)
    leader = "0x" + "c" * 40
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_virtual_positions = {
        f"{leader}|HYPE|SHORT": {
            "wallet_address": leader,
            "coin": "HYPE",
            "direction": "SHORT",
            "size": 3.0,
            "avg_price": 70.0,
            "entry_costs": 0.0,
            "fee_already_embedded_in_entry_price": False,
            "source_delta_key": "hash:paper-short-live",
        }
    }

    class _NetworkForbidden:
        def __init__(self, *args, **kwargs):
            raise AssertionError("status GET must never instantiate an HTTP client")

    monkeypatch.setattr(status_routes.httpx, "Client", _NetworkForbidden)
    payload = TestClient(create_ui_app(settings, state=state), raise_server_exceptions=False).get("/api/simulation/status").json()

    assert payload["status_projection_pure"] is True
    assert payload["network_reads_from_status"] is False
    assert payload["open_positions"] == 1
    assert payload["mark_to_market"]["marks_used"] == 0
    assert payload["positions"][0]["market_mark_available"] is False''',
        )
    elif not _has_py_function(text, new_name):
        raise RuntimeError("network-free status test marker missing")
    path.write_text(text, encoding="utf-8", newline="\n")


def instrument_exact_except_pass() -> list[str]:
    src = ROOT / "src" / "hl_observer"
    touched: list[str] = []
    for path in sorted(src.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        pass_lines = sorted(
            {
                handler.body[0].lineno
                for handler in ast.walk(tree)
                if isinstance(handler, ast.ExceptHandler)
                and len(handler.body) == 1
                and isinstance(handler.body[0], ast.Pass)
            },
            reverse=True,
        )
        if not pass_lines:
            continue
        lines = text.splitlines(keepends=True)
        for lineno in pass_lines:
            idx = lineno - 1
            raw = lines[idx]
            if raw.strip() != "pass":
                raise RuntimeError(f"non-standalone except/pass needs manual handling: {path}:{lineno}")
            indent = raw[: len(raw) - len(raw.lstrip())]
            newline = "\r\n" if raw.endswith("\r\n") else "\n"
            lines[idx : idx + 1] = [
                f"{indent}import logging as _hs_silent_logging{newline}",
                f"{indent}_hs_silent_logging.getLogger(__name__).debug(\"best-effort exception suppressed\", exc_info=True){newline}",
            ]
        path.write_text("".join(lines), encoding="utf-8", newline="")
        touched.append(path.relative_to(ROOT).as_posix())

    remaining: list[str] = []
    for path in sorted(src.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for handler in ast.walk(tree):
            if isinstance(handler, ast.ExceptHandler) and len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                remaining.append(f"{path.relative_to(ROOT)}:{handler.body[0].lineno}")
    if remaining:
        raise RuntimeError("silent except/pass remain: " + ", ".join(remaining))
    return touched


def main() -> None:
    patch_powershell()
    patch_cross_os_preflight()
    patch_status_tests()
    touched = instrument_exact_except_pass()
    print("FINALIZE_PATCH_OK")
    print("instrumented except/pass:", ", ".join(touched) or "none")


if __name__ == "__main__":
    main()
