from __future__ import annotations

import importlib.util
import json
import os
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
        "copy-vault-checkpoints",
    ]


def test_copy_vault_checkpoint_writer_cannot_be_omitted_from_live_profile() -> None:
    assert "copy-vault-checkpoints" in WATCH.DEFAULT_NAMES
    assert WATCH._copy_vault_required_names(["userfills-live"]) == [
        "userfills-live", "copy-vault-checkpoints",
    ]
    assert WATCH._copy_vault_required_names(["bbo-collector"]) == ["bbo-collector"]


def test_checkpoint_gap_health_is_separate_from_collector_liveness(tmp_path: Path) -> None:
    heartbeat_path = tmp_path / "runtime/research_lab/heartbeats/copy-vault-checkpoints.json"
    heartbeat_path.parent.mkdir(parents=True)
    heartbeat_path.write_text(json.dumps({
        "pid": 123,
        "ts_ms": 1_000_000,
        "protocol": WATCH.CHECKPOINT_COLLECTOR_PROTOCOL,
        "metriques": {"gaps_critiques": 45},
    }), encoding="utf-8")
    assert WATCH._checkpoint_evidence_health(
        tmp_path, {"copy-vault-checkpoints": 123}, now_ms=1_000_001,
    ) == {"status": "GAPS_REPORTED", "reported_gaps": 45}
    assert WATCH._checkpoint_evidence_health(
        tmp_path, {"copy-vault-checkpoints": 124}, now_ms=1_000_001,
    )["status"] == "HEARTBEAT_UNVERIFIED"


def test_un_recu_non_mesurable_ne_devient_pas_zero_gap(tmp_path: Path) -> None:
    heartbeat_path = tmp_path / "runtime/research_lab/heartbeats/copy-vault-checkpoints.json"
    heartbeat_path.parent.mkdir(parents=True)
    heartbeat_path.write_text(json.dumps({
        "pid": 123,
        "ts_ms": 1_000_000,
        "protocol": WATCH.CHECKPOINT_COLLECTOR_PROTOCOL,
        "metriques": {"coverage_receipt_status": "UNMEASURABLE"},
    }), encoding="utf-8")

    assert WATCH._checkpoint_evidence_health(
        tmp_path, {"copy-vault-checkpoints": 123}, now_ms=1_000_001,
    ) == {"status": "EVIDENCE_UNMEASURABLE", "reported_gaps": None}


def test_heartbeat_proven_avec_gap_non_nul_est_rejete(tmp_path: Path) -> None:
    heartbeat_path = tmp_path / "runtime/research_lab/heartbeats/copy-vault-checkpoints.json"
    heartbeat_path.parent.mkdir(parents=True)
    heartbeat_path.write_text(json.dumps({
        "pid": 123,
        "ts_ms": 1_000_000,
        "protocol": WATCH.CHECKPOINT_COLLECTOR_PROTOCOL,
        "metriques": {"coverage_receipt_status": "PROVEN", "gaps_critiques": 1},
    }), encoding="utf-8")

    assert WATCH._checkpoint_evidence_health(
        tmp_path, {"copy-vault-checkpoints": 123}, now_ms=1_000_001,
    ) == {"status": "HEARTBEAT_INCONSISTENT", "reported_gaps": None}


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


def test_watchdog_allows_extra_attached_collector(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        WATCH, "renew_bounded_collection_lease",
        lambda *_args, **_kwargs: {"renewed": True, "reason": "OK"},
    )
    WATCH.run_watchdog(
        tmp_path,
        interval_s=30.0,
        duration_s=60.0,
        requested_names=["bbo-collector"],
        ensure_fn=lambda *_args, **_kwargs: {
            "actifs": {"bbo-collector": 101, "copy-vault-checkpoints": 202},
            "manquants": [], "lease": {"lease_id": "lease-test"},
            "paper_read_only": True,
        },
        monotonic_fn=iter((0.0, 0.0)).__next__,
        max_passes=1,
    )
    log = json.loads(
        (tmp_path / "runtime/logs/economic-collector-watchdog.jsonl").read_text(
            encoding="utf-8"
        )
    )
    assert log["status"] == "STARTING"
    assert log["missing"] == []


def test_watchdog_degrade_un_processif_actif_mais_heartbeat_donnees_fige(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    now_s = 1_800_000_000.0
    heartbeat = tmp_path / "runtime/data/bbo_heartbeat.json"
    heartbeat.parent.mkdir(parents=True)
    heartbeat.write_text('{"ts": 1800000000}', encoding="utf-8")
    os.utime(heartbeat, (now_s - 600, now_s - 600))
    names = ["bbo-collector", "userfills-live", "copy-vault-checkpoints"]
    monkeypatch.setattr(WATCH.time, "time", lambda: now_s)
    monkeypatch.setattr(
        WATCH, "renew_bounded_collection_lease",
        lambda *_args, **_kwargs: {"renewed": True, "reason": "OK"},
    )

    WATCH.run_watchdog(
        tmp_path,
        interval_s=30.0,
        duration_s=60.0,
        requested_names=names,
        ensure_fn=lambda _root, requested, **_kwargs: {
            "actifs": {name: 100 + index for index, name in enumerate(requested)},
            "manquants": [],
            "lease": {"lease_id": "lease-test"},
            "protocols": {
                "userfills-live": WATCH.UNBOUND_L2_SOURCE_PROTOCOL,
                "copy-vault-checkpoints": WATCH.CHECKPOINT_COLLECTOR_PROTOCOL,
            },
            "paper_read_only": True,
        },
        monotonic_fn=iter((0.0, 0.0)).__next__,
        max_passes=1,
    )

    journal = tmp_path / "runtime/logs/economic-collector-watchdog.jsonl"
    log = json.loads(journal.read_text(encoding="utf-8"))
    assert log["status"] == "DEGRADED"
    assert log["stream_heartbeats"]["bbo-collector"]["status"] == "STALE"
    assert "bbo-collector" in capsys.readouterr().out


def test_heartbeat_health_reads_file_age_without_opening_payload(tmp_path: Path) -> None:
    heartbeat = tmp_path / "runtime/data/bbo_heartbeat.json"
    heartbeat.parent.mkdir(parents=True)
    # The collector payload can be large; health inspection must only stat the file.
    heartbeat.write_bytes(b"{" + b" " * (2 * 1024 * 1024))
    os.utime(heartbeat, (1_799_999_990.0, 1_799_999_990.0))

    result = WATCH.collector_heartbeat_health(
        tmp_path, ["bbo-collector"], now_s=1_800_000_000.0,
    )

    assert result["bbo-collector"]["status"] == "FRESH"
    assert result["bbo-collector"]["age_s"] == 10.0
    assert result["bbo-collector"]["threshold_s"] >= 120


def test_heartbeat_health_distinguishes_missing_and_future_files(tmp_path: Path) -> None:
    future = tmp_path / "runtime/research_lab/heartbeats/allmids-collector.json"
    future.parent.mkdir(parents=True)
    future.write_text("{}", encoding="utf-8")
    os.utime(future, (1_800_000_060.0, 1_800_000_060.0))

    result = WATCH.collector_heartbeat_health(
        tmp_path, ["bbo-collector", "allmids-collector"], now_s=1_800_000_000.0,
    )

    assert result["bbo-collector"]["status"] == "MISSING"
    assert result["allmids-collector"]["status"] == "FUTURE"
    assert result["allmids-collector"]["future_by_s"] == 60.0


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
