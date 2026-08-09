"""The two release launchers must stay embedded-runtime-only and bounded."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_analysis_launcher_has_noninteractive_portable_smoke():
    text = (ROOT / "ANALYSER_BACKTESTS_REPLAYS.cmd").read_text(
        encoding="utf-8", errors="replace"
    )
    lowered = text.casefold()
    assert 'call "%~dp0tools\\portable_env.cmd"' in lowered
    assert '"%analysis_mode%"=="portable-smoke"' in lowered
    assert '"%analysis_mode%"=="portable-check"' in lowered
    assert "hl_observer.ops.portable_smoke" in lowered
    assert lowered.index("portable-smoke") < lowered.index("hl_observer.ops.lab_alpha")
    assert 'set "py=python"' not in lowered
    assert "where py" not in lowered
    assert "py -3" not in lowered


def test_analysis_launcher_routes_all_documented_profiles():
    text = (ROOT / "ANALYSER_BACKTESTS_REPLAYS.cmd").read_text(
        encoding="utf-8", errors="replace"
    ).casefold()
    for profile in ("quick", "full", "deep", "maximum"):
        assert f'"%analysis_mode%"=="{profile}"' in text
    assert "hl_observer.ops.historical_analysis_suite" in text


def test_main_launcher_portable_check_resolves_embedded_python_first():
    text = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="replace")
    lowered = text.casefold()
    assert 'call "%~dp0tools\\portable_env.cmd"' in lowered
    assert "portable-check" in lowered
    assert "tools\\portable_runtime.py" in lowered
    assert lowered.index("portable_env.cmd") < lowered.index("portable-check")
    assert '"%hypersmart_python%" tools\\portable_runtime.py' in lowered
    assert "--require-embedded --json" in lowered
    assert "portable_launcher_check_ok" in lowered
    assert "endlocal & exit /b %rc%" in lowered


def test_main_launcher_never_invokes_an_unqualified_python_command():
    text = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="replace")
    command_lines = [line for line in text.splitlines() if not line.lstrip().upper().startswith("REM")]
    executable_text = "\n".join(command_lines)
    assert re.search(r"(?im)^\s*python(?:\.exe)?\s", executable_text) is None
    assert re.search(r"(?i)&\s*python(?:\.exe)?\s", executable_text) is None
