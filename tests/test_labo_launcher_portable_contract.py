from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "LANCER-RECHERCHE-CONTINUE.cmd"


def _active_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().upper().startswith("REM ")
    ]


def test_continuous_research_launcher_uses_portable_python_and_real_preflight() -> None:
    text = LAUNCHER.read_text(encoding="utf-8", errors="ignore")
    active = _active_lines(text)

    assert 'call "%~dp0tools\\portable_env.cmd"' in text
    assert 'if not defined HYPERSMART_PYTHON' in text
    assert 'set "PYTHONUNBUFFERED=1"' in text
    assert '"%HYPERSMART_PYTHON%" -u tools\\recherche_continue.py dry-run' in active
    assert '"%HYPERSMART_PYTHON%" -u tools\\recherche_continue.py peut-reprendre' in active
    assert all(not line.lower().startswith("python ") for line in active)


def test_launcher_keeps_paper_only_tripwires() -> None:
    text = LAUNCHER.read_text(encoding="utf-8", errors="ignore")
    for expected in (
        'set "HL_ENV=paper"',
        'set "HL_ENABLE_MAINNET_EXECUTION=0"',
        'set "HL_ENABLE_TESTNET_EXECUTION=0"',
        'set "REAL_MAINNET_TRADING=false"',
        'set "TESTNET_ONLY=true"',
    ):
        assert expected in text
