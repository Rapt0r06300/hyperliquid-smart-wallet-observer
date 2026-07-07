"""PaperStrategyRegistry (V12 capability M).

Versioned, deny-by-default registry of paper-only strategies. The decision layer
asks ``is_usable(strategy_id, context=...)`` before running a strategy. There is
NO execution surface: the registry stores definitions and answers queries — it
never places, signs, or sends anything.
"""

from __future__ import annotations

from hl_observer.storage.run_context import RunContext
from hl_observer.strategies.models import StrategyDefinition


class PaperStrategyRegistry:
    def __init__(self) -> None:
        # strategy_id -> {version: StrategyDefinition}
        self._by_id: dict[str, dict[int, StrategyDefinition]] = {}

    def register(self, definition: StrategyDefinition, *, replace: bool = False) -> None:
        versions = self._by_id.setdefault(definition.strategy_id, {})
        if definition.version in versions and not replace:
            raise ValueError(
                f"strategy {definition.key} already registered (use replace=True)"
            )
        versions[definition.version] = definition

    def is_registered(self, strategy_id: str) -> bool:
        return bool(self._by_id.get(strategy_id))

    def versions(self, strategy_id: str) -> list[int]:
        return sorted(self._by_id.get(strategy_id, {}))

    def get(self, strategy_id: str, *, version: int | None = None) -> StrategyDefinition | None:
        versions = self._by_id.get(strategy_id)
        if not versions:
            return None
        if version is None:
            return versions[max(versions)]
        return versions.get(version)

    def all(self) -> list[StrategyDefinition]:
        return [self.get(sid) for sid in sorted(self._by_id) if self.get(sid)]

    def enabled(self) -> list[StrategyDefinition]:
        return [d for d in self.all() if d.enabled]

    def for_context(self, context: RunContext) -> list[StrategyDefinition]:
        return [d for d in self.enabled() if d.valid_in(context)]

    def is_usable(self, strategy_id: str, *, context: RunContext) -> bool:
        """Deny-by-default: unregistered / disabled / wrong-context strategy is not usable."""
        defn = self.get(strategy_id)
        if defn is None or not defn.enabled:
            return False
        return defn.valid_in(context)


__all__ = ["PaperStrategyRegistry"]
