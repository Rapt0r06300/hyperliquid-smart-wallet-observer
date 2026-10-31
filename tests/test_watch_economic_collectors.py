from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from hl_observer.ops.collecteur_registry import COLLECTEURS_CAMPAGNE, COLLECTEURS_HARVEST

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "watch_economic_collectors", ROOT / "tools" / "watch_economic_collectors.py"
)
assert SPEC and SPEC.loader
WATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WATCH)


def test_copy_vault_launcher_requests_all_harvest_and_campaign_collectors() -> None:
    expected = set(COLLECTEURS_HARVEST) | {
        str(row["nom"]) for row in COLLECTEURS_CAMPAGNE
    }

    assert len(WATCH.DEFAULT_NAMES) == len(set(WATCH.DEFAULT_NAMES))
    assert set(WATCH.DEFAULT_NAMES) == expected


def test_copy_vault_cmd_preflights_runtime_and_states_raw_safe_destinations() -> None:
    launcher = (ROOT / "LANCER_COLLECTEURS_COPY_VAULT.cmd").read_text(encoding="utf-8")

    assert "--profile copy-vault" in launcher
    assert "--interval-s 30 --duration-s 518400 --lease-duration-s 120" in launcher
    assert "python.exe" in launcher and "sys.version_info >= (3, 11)" in launcher
    assert "import fastapi,httpx,numpy,pandas,psutil,pydantic" in launcher
    assert "runtime\\data" in launcher
    assert "runtime\\recovery\\full\\usable\\shards" in launcher
    assert "aucune installation ni collecte SAFE automatique" in launcher


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
            "protocols": {
                "userfills-live": WATCH.UNBOUND_L2_SOURCE_PROTOCOL,
                "copy-vault-checkpoints": WATCH.CHECKPOINT_COLLECTOR_PROTOCOL,
            },
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
    assert log["status"] == "ACTIVE"
    assert log["missing"] == []
    assert log["paper_read_only"] is True


def test_watchdog_displays_each_collector_log_and_heartbeat_path(tmp_path: Path, capsys) -> None:
    log_path = tmp_path / "runtime" / "logs" / "economic-userfills-live.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("collector output\n", encoding="utf-8")
    heartbeat = tmp_path / "runtime" / "data" / "userfills_live.lock"
    heartbeat.parent.mkdir(parents=True)
    heartbeat.write_text("heartbeat", encoding="utf-8")

    result = WATCH.run_watchdog(
        tmp_path,
        interval_s=30.0,
        duration_s=60.0,
        requested_names=["userfills-live"],
        ensure_fn=lambda *_args, **_kwargs: {
            "status": "ACTIVE", "actifs": {"userfills-live": 4321},
            "manquants": [], "lease": {"lease_id": "lease-test"},
            "paper_read_only": True,
        },
        monotonic_fn=iter((0.0, 0.0)).__next__,
        max_passes=1,
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "[JOURNAUX] Dernières lignes" in output
    assert "userfills-live" in output and "PID 4321" in output
    assert str(log_path.resolve()) in output
    assert str(heartbeat.resolve()) in output
    assert "derniere sortie: collector output" in output
    record = json.loads(
        (tmp_path / "runtime" / "logs" / "economic-collector-watchdog.jsonl")
        .read_text(encoding="utf-8")
    )
    assert record["collector_details"][0]["logs"][0]["bytes"] == log_path.stat().st_size
