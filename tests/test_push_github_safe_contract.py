"""Contract for explicit local Codex -> single GitHub main publishing."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "nt", reason="le helper s'execute via Windows PowerShell")
def test_stage_publishable_changes_ignores_runtime_directories(tmp_path: Path):
    git_exe = shutil.which("git")
    assert git_exe is not None
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ("init", "-b", "main"),
        ("config", "user.name", "Alina Test"),
        ("config", "user.email", "alina-test@example.invalid"),
    ):
        subprocess.run((git_exe, *args), cwd=repo, check=True, capture_output=True)
    (repo / ".gitignore").write_text("data/\nlogs/\nruntime/\n", encoding="utf-8")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run((git_exe, "add", "."), cwd=repo, check=True)
    subprocess.run((git_exe, "commit", "-m", "base"), cwd=repo, check=True, capture_output=True)
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "data").mkdir()
    (repo / "logs").mkdir()
    (repo / "data" / "shard.jsonl").write_text("{}\n", encoding="utf-8")
    (repo / "logs" / "collector.log").write_text("live\n", encoding="utf-8")

    helper = ROOT / "tools" / "push_github_safe.ps1"
    harness = tmp_path / "stage-test.ps1"
    harness.write_text(
        """
param([string]$Helper, [string]$GitExecutable, [string]$Repo)
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Helper, [ref]$tokens, [ref]$errors)
foreach ($name in @('Invoke-Git', 'Get-GitText', 'Stage-PublishableChanges')) {
    $fn = $ast.Find({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true)
    if ($null -eq $fn) { throw "Fonction absente: $name" }
    Invoke-Expression $fn.Extent.Text
}
$script:GitExecutable = $GitExecutable
Set-Location -LiteralPath $Repo
Stage-PublishableChanges
& $GitExecutable diff --cached --name-only
""".strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        (
            "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(harness), "-Helper", str(helper), "-GitExecutable", git_exe,
            "-Repo", str(repo),
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "app.py"


def test_codex_push_does_not_force_reset_or_rewrite_remote_history():
    ps = (ROOT / "tools" / "push_github_safe.ps1").read_text(encoding="utf-8")
    assert '$env:GIT_LFS_SKIP_SMUDGE = "1"' in ps
    assert 'Invoke-Git @("push", "origin", "main:main")' in ps
    assert 'Invoke-Git @("commit", "-m", "chore(codex): sauvegarder modifications locales Alina")' in ps
    assert '"add", "-A", "--", "."' in ps
    assert '"merge", "--no-edit", $Ref' in ps
    assert '"fetch", "--prune", "origin", "main"' in ps
    assert 'if ($allowed -cnotcontains $remoteUrl)' in ps
    assert 'if (-not (Test-Git @("diff", "--cached", "--quiet")))' in ps
    assert 'Fichier potentiellement secret interdit' in ps
    assert 'Fichier > 95 Mio' in ps
    assert 'Get-RemoteMainSha' in ps
    assert 'Invoke-Git @("push", "--force"' not in ps
    assert 'Invoke-Git @("reset", "--hard"' not in ps


def test_button_retains_main_and_propagates_push_failure():
    button = (ROOT / "POUSSER-GITHUB-FORCE.cmd").read_text(encoding="utf-8")
    assert "tools\\push_github_safe.ps1" in button
    assert 'for %%G in (git.exe)' in button
    assert 'call "%~dp0PREPARER_GIT_PORTABLE.cmd"' in button
    assert "if errorlevel 1 goto :git_install_failed" in button
    assert ':git_ready' in button
    assert "if not \"%RC%\"==\"0\" goto :echec_code" in button
    assert "endlocal & exit /b %RC%" in button
    assert "git push --force" not in button.lower()


def test_alias_buttons_invoke_single_canonical_push():
    for name in ("POUSSER_TOUT_LE_TRAVAIL.cmd", "REPARER_ET_POUSSER.cmd"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert 'call "%~dp0POUSSER-GITHUB-FORCE.cmd"' in text
        assert 'endlocal & exit /b %RC%' in text
