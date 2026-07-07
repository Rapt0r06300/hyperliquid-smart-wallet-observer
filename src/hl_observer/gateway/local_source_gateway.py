"""Local source gateway aggregating read-only connectors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class LocalSourceStatus:
    sources: tuple[str, ...]
    healthy_count: int
    read_only: bool = True


def local_source_status(source_names: Iterable[str]) -> LocalSourceStatus:
    names = tuple(str(name) for name in source_names if str(name))
    return LocalSourceStatus(sources=names, healthy_count=len(names))


__all__ = ["LocalSourceStatus", "local_source_status"]
