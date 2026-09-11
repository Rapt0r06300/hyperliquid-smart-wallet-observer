from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-recherche.txt"
PORTABLE_LOCK = ROOT / "requirements-portable.txt"


def _exact_versions(path: Path) -> dict[str, str]:
    exact: dict[str, str] = {}
    pattern = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s]+)$")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.fullmatch(line)
        assert match is not None, f"dependency must use an exact version pin: {line}"
        exact[match.group("name").casefold()] = match.group("version")
    return exact


def _portable_versions(path: Path) -> dict[str, str]:
    exact: dict[str, str] = {}
    pattern = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s]+)\s+--hash=sha256:[0-9a-f]{64}$")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        match = pattern.fullmatch(line)
        if match is not None:
            exact[match.group("name").casefold()] = match.group("version")
    return exact


def test_research_optional_dependencies_are_exact_pinned_and_match_portable_lock():
    research = _exact_versions(REQUIREMENTS)
    portable = _portable_versions(PORTABLE_LOCK)

    assert set(research) == {"optuna", "cmaes", "scipy", "numpy", "pyarrow", "lz4"}
    for name, version in research.items():
        assert portable[name] == version
