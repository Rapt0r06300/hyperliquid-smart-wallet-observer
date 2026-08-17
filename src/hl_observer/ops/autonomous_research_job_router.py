"""Narrow autonomous-job router for FULL/COLD economic family suites.

The canonical worker intentionally stays conservative.  This wrapper broadens
its economic-suite allowlist only for the three active economic families whose
FULL/COLD adapters are already implemented.  No execution flags are changed.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.ops import autonomous_research_job as canonical_job

FAMILY_ECONOMIC_SUITES = frozenset(
    {
        "copy-vault-full",
        "lead-lag-full",
        "cross-venue-full",
    }
)


def allowed_economic_suites() -> frozenset[str]:
    return frozenset(canonical_job.ECONOMIC_SUITES) | FAMILY_ECONOMIC_SUITES


def validate_request(raw: Mapping[str, Any]) -> dict[str, Any]:
    original = canonical_job.ECONOMIC_SUITES
    canonical_job.ECONOMIC_SUITES = set(allowed_economic_suites())
    try:
        return canonical_job.validate_request(raw)
    finally:
        canonical_job.ECONOMIC_SUITES = original


def main(argv: Iterable[str] | None = None) -> int:
    original = canonical_job.ECONOMIC_SUITES
    canonical_job.ECONOMIC_SUITES = set(allowed_economic_suites())
    try:
        return canonical_job.main(argv)
    finally:
        canonical_job.ECONOMIC_SUITES = original


__all__ = [
    "FAMILY_ECONOMIC_SUITES",
    "allowed_economic_suites",
    "main",
    "validate_request",
]


if __name__ == "__main__":
    raise SystemExit(main())
