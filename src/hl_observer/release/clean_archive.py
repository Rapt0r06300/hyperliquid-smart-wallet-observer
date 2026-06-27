"""Clean archive plan (V12 capability U - reproducible export, no secrets/logs/fake).

Computes which files belong in a shareable archive of the project and which are
excluded (secrets, logs, caches, runtime data), then verifies the included set
contains no fabricated-data generators (via the fake-data scanner). Pure: it builds
and verifies a PLAN; writing the zip is a thin, separate IO step. No order, no fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hl_observer.security.fake_data_scanner import scan_for_fake_data

_EXCLUDE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", ".pytest_cache", ".ruff_cache",
    "logs", "tmp_pytest", "tmp", "node_modules", "data", "runtime", "dist", "build",
}
_SECRET_SUFFIXES = {".pem", ".key", ".p12", ".keystore"}


def _exclude_reason(rel: Path) -> str | None:
    parts = set(rel.parts)
    if parts & _EXCLUDE_DIRS:
        return "excluded_dir"
    name = rel.name
    if name == ".env" or (name.startswith(".env") and not name.endswith(".example")):
        return "secret_env"
    if rel.suffix in _SECRET_SUFFIXES:
        return "secret_file"
    return None


@dataclass(frozen=True, slots=True)
class CleanArchivePlan:
    included: tuple[str, ...]
    excluded: tuple[tuple[str, str], ...]
    clean: bool
    blockers: tuple[str, ...]
    fake_findings: int = 0

    def to_dict(self) -> dict:
        return {
            "included": list(self.included),
            "excluded": [{"path": p, "reason": r} for p, r in self.excluded],
            "clean": self.clean,
            "blockers": list(self.blockers),
            "fake_findings": self.fake_findings,
        }


def build_clean_archive_plan(root: str | Path = ".") -> CleanArchivePlan:
    root = Path(root)
    included: list[str] = []
    excluded: list[tuple[str, str]] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        reason = _exclude_reason(rel)
        if reason:
            excluded.append((str(rel), reason))
        else:
            included.append(str(rel))

    blockers: list[str] = []
    fake = scan_for_fake_data([root])  # included tree must invent nothing
    if fake:
        blockers.append(f"fake-data generators in archive: {len(fake)}")
    return CleanArchivePlan(
        included=tuple(included),
        excluded=tuple(excluded),
        clean=not blockers,
        blockers=tuple(blockers),
        fake_findings=len(fake),
    )


__all__ = ["CleanArchivePlan", "build_clean_archive_plan"]
