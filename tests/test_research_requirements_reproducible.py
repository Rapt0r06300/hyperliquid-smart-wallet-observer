from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-recherche.txt"
PORTABLE_LOCK = ROOT / "requirements-portable.txt"


def _locked_versions(path: Path) -> dict[str, tuple[str, str]]:
    locked: dict[str, tuple[str, str]] = {}
    pattern = re.compile(
        r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s]+)\s+--hash=sha256:(?P<hash>[0-9a-f]{64})$"
    )
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.fullmatch(line)
        assert match is not None, f"dependency must be exact + sha256 locked: {line}"
        locked[match.group("name").casefold()] = (match.group("version"), match.group("hash"))
    return locked


def test_research_optional_dependencies_are_exact_hash_locked_and_match_portable_lock():
    research = _locked_versions(REQUIREMENTS)
    portable = _locked_versions(PORTABLE_LOCK)

    assert set(research) == {"optuna", "cmaes", "scipy", "numpy", "pyarrow", "lz4"}
    for name, pin in research.items():
        assert portable[name] == pin
