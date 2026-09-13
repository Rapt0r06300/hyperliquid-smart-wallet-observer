from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "watch_economic_collectors", ROOT / "tools" / "watch_economic_collectors.py"
)
assert SPEC and SPEC.loader
WATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WATCH)


def test_requested_names_preserve_full_campaign_state(tmp_path: Path) -> None:
    state = tmp_path / WATCH.STATE_RELPATH
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps({"requested": ["bbo-collector", "userfills-live"]}),
        encoding="utf-8",
    )

    assert WATCH._requested_names(tmp_path) == [
        "bbo-collector",
        "userfills-live",
    ]


def test_watchdog_repairs_and_logs_without_stopping_after_one_pass(
    tmp_path: Path,
) -> None:
    calls = []

    def ensure(root, names, **kwargs):
        calls.append((root, names, kwargs))
        return {
            "status": "ACTIVE",
            "actifs": {name: index + 1 for index, name in enumerate(names)},
            "manquants": [],
            "lease": {"lease_id": "lease-test"},
            "paper_read_only": True,
        }

    result = WATCH.run_watchdog(
        tmp_path,
        interval_s=30.0,
        duration_s=60.0,
        ensure_fn=ensure,
        monotonic_fn=iter((0.0, 0.0)).__next__,
        max_passes=1,
    )

    assert result == 0
    assert len(calls) == 1
    assert calls[0][1] == list(WATCH.DEFAULT_NAMES)
    log = json.loads(
        (tmp_path / "runtime/logs/economic-collector-watchdog.jsonl").read_text(
            encoding="utf-8"
        )
    )
    assert log["status"] == "ACTIVE"
    assert log["missing"] == []
    assert log["paper_read_only"] is True
