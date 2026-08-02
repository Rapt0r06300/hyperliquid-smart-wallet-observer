"""The two release launchers must stay embedded-runtime-only and bounded."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_analysis_launcher_has_noninteractive_portable_smoke():
    text = (ROOT / "ANALYSER_BACKTESTS_REPLAYS.cmd").read_text(
        encoding="utf-8", errors="replace"
    )
    lowered = text.casefold()
    assert 'call "%~dp0tools\\portable_env.cmd"' in lowered
    assert 'if /i "%~1"=="portable-smoke"' in lowered
    assert "hl_observer.ops.portable_smoke" in lowered
    assert lowered.index("portable-smoke") < lowered.index("hl_observer.ops.lab_alpha")
    assert 'set "py=python"' not in lowered
    assert "where py" not in lowered
    assert "py -3" not in lowered


def test_main_launcher_portable_check_resolves_embedded_python_first():
    text = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="replace")
    lowered = text.casefold()
    assert 'call "%~dp0tools\\portable_env.cmd"' in lowered
    assert "portable-check" in lowered
    assert "tools\\portable_runtime.py" in lowered
    assert lowered.index("portable_env.cmd") < lowered.index("portable-check")
