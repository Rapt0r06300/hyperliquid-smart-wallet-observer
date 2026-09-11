from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-recherche.txt"
PORTABLE_LOCK = ROOT / "requirements-portable.txt"


def _research_pins(path: Path) -> dict[str, list[tuple[str, str | None]]]:
    pins: dict[str, list[tuple[str, str | None]]] = {}
    pattern = re.compile(
        r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s;]+)"
        r"(?:;\s*(?P<marker>python_version\s*(?:<|>=)\s*\"3\.12\"))?$"
    )
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.fullmatch(line)
        assert match is not None, f"dependency must use an exact version pin: {line}"
        name = match.group("name").casefold()
        pins.setdefault(name, []).append((match.group("version"), match.group("marker")))
    return pins


def _portable_versions(path: Path) -> dict[str, str]:
    exact: dict[str, str] = {}
    pattern = re.compile(
        r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s]+)\s+--hash=sha256:[0-9a-f]{64}$"
    )
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        match = pattern.fullmatch(line)
        if match is not None:
            exact[match.group("name").casefold()] = match.group("version")
    return exact


def test_research_optional_dependencies_are_exact_pinned_and_match_portable_lock():
    research = _research_pins(REQUIREMENTS)
    portable = _portable_versions(PORTABLE_LOCK)

    assert set(research) == {"optuna", "cmaes", "scipy", "numpy", "pyarrow", "lz4"}

    for name in {"optuna", "cmaes", "pyarrow", "lz4"}:
        assert research[name] == [(portable[name], None)]

    expected_markers = {'python_version < "3.12"', 'python_version >= "3.12"'}
    for name in {"numpy", "scipy"}:
        assert len(research[name]) == 2
        by_marker = {marker: version for version, marker in research[name]}
        assert set(by_marker) == expected_markers
        assert by_marker['python_version >= "3.12"'] == portable[name]
        assert by_marker['python_version < "3.12"'] != portable[name]
