"""Conservative dependency-aware test selection."""
from __future__ import annotations

import ast
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TestImpactPlan:
    changed_files: tuple[str, ...]
    impacted_tests: tuple[str, ...]
    full_suite_required: bool
    reason: str
    graph_fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return {
            "changed_files": list(self.changed_files),
            "impacted_tests": list(self.impacted_tests),
            "full_suite_required": self.full_suite_required,
            "reason": self.reason,
            "graph_fingerprint": self.graph_fingerprint,
        }


def select_impacted_tests(root: Path, changed_files: Iterable[str | Path]) -> TestImpactPlan:
    root = root.resolve()
    changed = tuple(sorted({_relative_change(root, Path(item)) for item in changed_files}))
    tests = sorted(path for path in root.glob("tests/test_*.py") if path.is_file())
    graph: dict[str, set[str]] = {}
    for test in tests:
        rel = test.relative_to(root).as_posix()
        graph[rel] = _imports(test)
    graph_fingerprint = hashlib.sha256(repr(sorted((key, sorted(value)) for key, value in graph.items())).encode()).hexdigest()
    if any(_requires_full_suite(path) for path in changed):
        return TestImpactPlan(changed, tuple(_rel(root, test) for test in tests), True, "GLOBAL_CONFIGURATION_CHANGED", graph_fingerprint)
    if not changed:
        return TestImpactPlan((), (), False, "NO_CODE_CHANGES", graph_fingerprint)
    impacted: set[str] = set()
    for test, imports in graph.items():
        test_text = (root / test).read_text(encoding="utf-8", errors="replace").lower()
        for changed_path in changed:
            stem = Path(changed_path).stem.lower()
            module = Path(changed_path).with_suffix("").as_posix().replace("/", ".").lower()
            if changed_path.startswith("tests/") or stem in test_text or module in imports:
                impacted.add(test)
                break
    uncertain_python = any(path.endswith((".py", ".pyi")) for path in changed) and not impacted
    if uncertain_python:
        return TestImpactPlan(changed, tuple(_rel(root, test) for test in tests), True, "PYTHON_CHANGE_WITHOUT_SAFE_TEST_MAPPING", graph_fingerprint)
    return TestImpactPlan(changed, tuple(sorted(impacted)), False, "DEPENDENCY_IMPACT", graph_fingerprint)


def _imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except SyntaxError:
        return set()
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name.lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.add(node.module.lower())
    return values


def _requires_full_suite(path: str) -> bool:
    normalized = path.lower()
    return normalized.endswith(("pyproject.toml", "requirements.txt", "requirements-ci-tools.txt")) or normalized.startswith(".github/")


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _relative_change(root: Path, path: Path) -> str:
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()


__all__ = ["TestImpactPlan", "select_impacted_tests"]
