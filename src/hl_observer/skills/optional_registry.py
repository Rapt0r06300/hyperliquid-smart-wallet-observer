"""Optional skill registry (V12, repo 01): lazy deps that NEVER crash when missing."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field


@dataclass(slots=True)
class OptionalSkill:
    name: str
    module: str
    available: bool


@dataclass(slots=True)
class OptionalSkillRegistry:
    _skills: dict[str, OptionalSkill] = field(default_factory=dict)

    def register(self, name: str, module: str) -> OptionalSkill:
        try:
            available = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            available = False            # missing/broken dependency -> unavailable, no crash
        s = OptionalSkill(name=name, module=module, available=available)
        self._skills[name] = s
        return s

    def available(self) -> list[str]:
        return [n for n, s in self._skills.items() if s.available]

    def unavailable(self) -> list[str]:
        return [n for n, s in self._skills.items() if not s.available]


__all__ = ["OptionalSkill", "OptionalSkillRegistry"]
