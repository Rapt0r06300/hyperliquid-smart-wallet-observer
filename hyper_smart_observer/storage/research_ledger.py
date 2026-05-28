from __future__ import annotations
import json
import os
from datetime import datetime, UTC
from pathlib import Path

class ResearchHistoryLedger:
    """
    An append-only chronological record of observation events.
    Stored as JSONL for easy analysis by Codex.
    """
    def __init__(self, root_dir: Path):
        self.log_path = root_dir / "data" / "research_history_ledger.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record_event(self, event_type: str, data: dict):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "data": data
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def get_last_n_events(self, n: int = 10) -> list[dict]:
        if not self.log_path.exists():
            return []
        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(line) for line in lines[-n:]]
