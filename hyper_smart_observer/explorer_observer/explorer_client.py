from __future__ import annotations

from pathlib import Path

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.app.safety import SafetyViolation
from hyper_smart_observer.explorer_observer.explorer_models import ExplorerEvent
from hyper_smart_observer.explorer_observer.explorer_normalization import normalize_explorer_event


class ExplorerClient:
    """Experimental explorer observer, disabled by default.

    It intentionally does not hardcode private or unstable endpoints. Manual
    imports and fixtures are supported; network probing requires explicit flags.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def fetch_recent_events(self, *, network_read: bool = False) -> list[ExplorerEvent]:
        if not self.config.explorer_observer_enabled or not network_read:
            raise SafetyViolation(
                "CONFIGURATION_REFUSED",
                "Explorer observer network reads are disabled by default.",
            )
        raise SafetyViolation(
            "CONFIGURATION_REFUSED",
            "Explorer network endpoint is not verified; use manual imports/fixtures.",
        )

    def import_events(self, rows: list[dict]) -> list[ExplorerEvent]:
        return [normalize_explorer_event(row, source="manual_import") for row in rows]

    def import_jsonl(self, path: Path) -> list[ExplorerEvent]:
        import json

        events: list[ExplorerEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(normalize_explorer_event(json.loads(line), source=str(path)))
        return events
