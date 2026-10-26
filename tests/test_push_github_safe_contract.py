"""Contracts for the Python-backed local-main to GitHub-main launcher."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "push_github_safe.ps1"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell shim is Windows-only")
@pytest.mark.parametrize(
    ("mode", "expected_flag"),
    (("DryRun", "--dry-run"), ("WipOnly", "--wip-only")),
)
def test_powershell_shim_forwards_arguments_and_python_exit_code(
    tmp_path: Path, mode: str, expected_flag: str,
) -> None:
    powershell = shutil.which("powershell.exe")
    assert powershell is not None

    project = tmp_path / "project with spaces"
    tools = project / "tools"
    tools.mkdir(parents=True)
    driver = tools / "alina_git_code_sync.py"
    driver.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['ALINA_SYNC_CAPTURE']).write_text("
        "json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        "raise SystemExit(int(os.environ['ALINA_SYNC_STUB_EXIT']))\n",
        encoding="utf-8",
    )
    capture = tmp_path / "captured argv.json"
    harness = tmp_path / "invoke-wrapper.ps1"
    harness.write_text(
        "param([string]$Helper, [string]$Root, [string]$Git, [string]$Mode)\n"
        "$ErrorActionPreference = 'Stop'\n"
        "if ($Mode -eq 'DryRun') { & $Helper -ProjectRoot $Root -GitExecutable $Git -DryRun }\n"
        "else { & $Helper -ProjectRoot $Root -GitExecutable $Git -WipOnly }\n"
        "exit $LASTEXITCODE\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["ALINA_SYNC_CAPTURE"] = str(capture)
    env["ALINA_SYNC_STUB_EXIT"] = "23"
    git_path = str(tmp_path / "git executable with spaces.exe")
    result = subprocess.run(
        (
            powershell, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(harness), str(HELPER), str(project), git_path, mode,
        ),
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 23, result.stdout + result.stderr
    assert json.loads(capture.read_text(encoding="utf-8")) == [
        "--root", str(project.resolve()), "--git", git_path, expected_flag,
    ]


def test_powershell_compatibility_layer_delegates_to_single_python_engine() -> None:
    source = HELPER.read_text(encoding="utf-8")

    assert '$driver = Join-Path $ProjectRoot "tools\\alina_git_code_sync.py"' in source
    assert '$command = @($driver, "--root", $ProjectRoot, "--git", $GitExecutable)' in source
    assert 'if ($DryRun) { $command += "--dry-run" }' in source
    assert 'if ($WipOnly) { $command += "--wip-only" }' in source
    assert "& $python @pyArgs @command" in source
    assert "Invoke-Git" not in source


def test_double_click_launcher_runs_canonical_engine_and_never_forces_git() -> None:
    launcher = (ROOT / "POUSSER-GITHUB-FORCE.cmd").read_text(encoding="utf-8-sig")

    assert "ALINA_ENGINE_REQUIRED_BUILD=2026-10-26-status-inventory-v2" in launcher
    assert 'call :download_source "tools/alina_git_code_sync.py"' in launcher
    assert '"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% "%ALINA_ENGINE%" --root "%ALINA_ROOT%." --git "%HYPERSMART_GIT%" %SYNC_OPTION%' in launcher
    assert 'SYNC_OPTION=--dry-run' in launcher
    assert 'SYNC_OPTION=--wip-only' in launcher
    assert "git push --force" not in launcher.casefold()
    assert "git reset --hard" not in launcher.casefold()


def test_alias_launchers_call_the_single_canonical_cmd_and_propagate_status() -> None:
    for name in ("POUSSER_TOUT_LE_TRAVAIL.cmd", "REPARER_ET_POUSSER.cmd"):
        source = (ROOT / name).read_text(encoding="utf-8-sig")
        assert 'call "%~dp0POUSSER-GITHUB-FORCE.cmd"' in source
        assert "endlocal & exit /b %RC%" in source
