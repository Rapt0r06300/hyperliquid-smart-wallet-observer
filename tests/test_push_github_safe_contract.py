"""Contract for explicit local Codex -> single GitHub main publishing."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_codex_push_does_not_force_reset_or_rewrite_remote_history():
    ps = (ROOT / "tools" / "push_github_safe.ps1").read_text(encoding="utf-8")
    assert 'Invoke-Git @("push", "origin", "main:main")' in ps
    assert 'Invoke-Git @("commit", "-m", "chore(codex): sauvegarder modifications locales Alina")' in ps
    assert '"add", "-A", "--", "."' in ps
    assert '"merge", "--no-edit", $Ref' in ps
    assert '"fetch", "--prune", "origin", "main"' in ps
    assert 'if ($allowed -cnotcontains $remoteUrl)' in ps
    assert 'if (-not (Test-Git @("diff", "--cached", "--quiet")))' in ps
    assert ':(exclude)runtime' in ps and ':(exclude)archive' in ps
    assert 'Fichier potentiellement secret interdit' in ps
    assert 'Fichier > 95 Mio' in ps
    assert 'Get-RemoteMainSha' in ps
    assert 'Invoke-Git @("push", "--force"' not in ps
    assert 'Invoke-Git @("reset", "--hard"' not in ps


def test_button_retains_main_and_propagates_push_failure():
    button = (ROOT / "POUSSER-GITHUB-FORCE.cmd").read_text(encoding="utf-8")
    assert "tools\\push_github_safe.ps1" in button
    assert 'for %%G in (git.exe)' in button
    assert "if not \"%RC%\"==\"0\" goto :echec_code" in button
    assert "endlocal & exit /b %RC%" in button
    assert "git push --force" not in button.lower()


def test_alias_buttons_invoke_single_canonical_push():
    for name in ("POUSSER_TOUT_LE_TRAVAIL.cmd", "REPARER_ET_POUSSER.cmd"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert 'call "%~dp0POUSSER-GITHUB-FORCE.cmd"' in text
        assert 'endlocal & exit /b %RC%' in text
