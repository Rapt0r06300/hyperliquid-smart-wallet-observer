from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-recherche.txt"
PORTABLE_LOCK = ROOT / "requirements-portable.txt"


def _exact_versions(path: Path) -> dict[str, list[tuple[str, str | None]]]:
    exact: dict[str, list[tuple[str, str | None]]] = {}
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
        pin = (match.group("version"), match.group("marker"))
        exact.setdefault(name, []).append(pin)
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

    conditional = {"numpy", "scipy"}
    expected_markers = {'python_version < "3.12"', 'python_version >= "3.12"'}

    for name, pins in research.items():
        assert len(pins) == len(set(pins)), f"duplicate research pin for {name}: {pins}"
        if name in conditional:
            assert len(pins) == 2, f"{name} must have one pin per supported Python range"
            assert {marker for _, marker in pins} == expected_markers
            portable_pin = (portable[name], 'python_version >= "3.12"')
            assert portable_pin in pins, f"{name} >=3.12 pin must match the portable lock"
        else:
            assert pins == [(portable[name], None)]
