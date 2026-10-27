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
    tmp_path: Path, monkeypatch,
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

    monkeypatch.setattr(
        WATCH, "renew_bounded_collection_lease",
        lambda *_args, **_kwargs: {"renewed": True, "reason": "OK"},
    )

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
    assert log["status"] == "STARTING"
    assert log["missing"] == []
    assert log["paper_read_only"] is True


def test_watchdog_displays_the_latest_line_for_each_worker(tmp_path: Path, monkeypatch, capsys) -> None:
    names = ["bbo-collector", "userfills-live"]
    logs = tmp_path / "runtime" / "logs"
    logs.mkdir(parents=True)
    (logs / "economic-bbo-collector.log").write_text(
        "connected\nreceived=42 coin=kPEPE\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        WATCH, "renew_bounded_collection_lease",
        lambda *_args, **_kwargs: {"renewed": True, "reason": "OK"},
    )

    WATCH.run_watchdog(
        tmp_path,
        interval_s=30.0,
        duration_s=60.0,
        requested_names=names,
        ensure_fn=lambda *_args, **_kwargs: {
            "actifs": {"bbo-collector": 101, "userfills-live": 202},
            "manquants": [], "lease": {"lease_id": "lease-test"},
            "paper_read_only": True,
        },
        monotonic_fn=iter((0.0, 0.0)).__next__,
        max_passes=1,
    )

    output = capsys.readouterr().out
    assert "[WORKER] bbo-collector — PID 101 — received=42 coin=kPEPE" in output
    assert "[WORKER] userfills-live — PID 202 — journal absent ou illisible" in output


def test_watchdog_log_rotation_is_bounded_and_keeps_recent_records(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(WATCH, "_WATCHDOG_LOG_MAX_BYTES", 180)
    root = tmp_path

    for index in range(4):
        WATCH._append_log(root, {"sequence": index, "details": "x" * 300})

    path = root / "runtime" / "logs" / "economic-collector-watchdog.jsonl"
    retained = [
        json.loads(line)["sequence"]
        for log_path in (path, *(path.with_name(f"{path.name}.{i}") for i in range(1, 4)))
        if log_path.exists()
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert retained == [3, 2, 1, 0]
