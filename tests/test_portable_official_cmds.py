from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "nt", reason="Windows CMD relocation proof")
def test_all_official_cmds_resolve_their_own_root_from_foreign_cwd(tmp_path: Path) -> None:
    foreign_cwd = tmp_path / "chemin avec espaces et accent é"
    foreign_cwd.mkdir()
    env = {
        **os.environ,
        "CI": "true",
        "HYPERSMART_NO_PAUSE": "1",
        "HYPERSMART_PUSH_NO_PAUSE": "1",
        "HYPERSMART_NO_OPEN_REPORT": "1",
    }
    cases = (
        ("LANCER_HYPERSMART.cmd", ["portable-check"], "PORTABLE_LAUNCHER_CHECK_OK", 90),
        (
            "ANALYSER_BACKTESTS_REPLAYS.cmd",
            ["portable-smoke"],
            '"schema": "hypersmart.portable_smoke.v1"',
            300,
        ),
        ("POUSSER-GITHUB-FORCE.cmd", ["--portable-self-check"], "PORTABLE_GITHUB_PUSH_CHECK_OK", 30),
        ("CREER_ARCHIVE_PORTABLE.cmd", ["--portable-self-check"], "PORTABLE_ARCHIVE_CHECK_OK", 30),
    )
    for filename, arguments, marker, timeout in cases:
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", str(ROOT / filename), *arguments],
            cwd=foreign_cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        assert completed.returncode == 0, f"{filename}:\n{output[-4000:]}"
        assert marker in output, f"{filename}: success marker missing\n{output[-4000:]}"
