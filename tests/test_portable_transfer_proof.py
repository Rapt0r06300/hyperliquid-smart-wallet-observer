from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops import portable_transfer_proof as PTP


def _manifest(root: Path, source: str = "pc-a") -> None:
    (root / "PORTABLE_FULL_CLONE_MANIFEST.json").write_text(
        json.dumps({"source_machine_fingerprint": source}), encoding="utf-8"
    )


def test_same_physical_machine_is_refused_before_commands(tmp_path: Path) -> None:
    _manifest(tmp_path)
    called = []
    result = PTP.prove_transferred_clone(
        tmp_path, current_fingerprint=lambda: "pc-a",
        runner=lambda *args, **kwargs: called.append((args, kwargs)),
    )
    assert result["portable_ready"] is False
    assert result["reason"] == "physical_pc_b_required"
    assert called == []


def test_full_hash_failure_stops_target_proof(tmp_path: Path) -> None:
    _manifest(tmp_path)
    result = PTP.prove_transferred_clone(
        tmp_path, current_fingerprint=lambda: "pc-b",
        clone_verifier=lambda *_args, **kwargs: {"ok": False, "full_hash": kwargs["full_hash"]},
    )
    assert result["reason"] == "full_hash_verification_failed"
    assert result["clone_verification"]["full_hash"] is True


def test_complete_pc_b_command_graph_can_be_proven(tmp_path: Path) -> None:
    _manifest(tmp_path)
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(list(command))
        return {"ok": True, "returncode": 0}

    result = PTP.prove_transferred_clone(
        tmp_path, collection_seconds=900, runner=runner,
        collection_runner=lambda *_args, **_kwargs: {"ok": True, "returncode": 0},
        asset_verifier=lambda *_args, **_kwargs: {"ok": True},
        current_fingerprint=lambda: "pc-b",
        clone_verifier=lambda *_args, **_kwargs: {"ok": True, "full_hash": True},
    )
    assert result["portable_ready"] is True
    assert [step["name"] for step in result["steps"]] == [
        "portable_check", "portable_smoke", "github_push_self_check", "archive_self_check",
        "collection_15_minutes_and_clean_stop",
        "replay_full", "replay_deep",
    ]
    assert any("portable-check" in command for command in calls)
    assert any("deep" in command for command in calls)


def test_collection_shorter_than_fifteen_minutes_cannot_certify(tmp_path: Path) -> None:
    _manifest(tmp_path)
    result = PTP.prove_transferred_clone(
        tmp_path, collection_seconds=899,
        runner=lambda *_args, **_kwargs: {"ok": True, "returncode": 0},
        collection_runner=lambda *_args, **_kwargs: {"ok": True, "returncode": 0},
        asset_verifier=lambda *_args, **_kwargs: {"ok": True},
        current_fingerprint=lambda: "pc-b",
        clone_verifier=lambda *_args, **_kwargs: {"ok": True},
    )
    assert result["portable_ready"] is False
    assert result["reason"] == "collection_below_900_seconds"


def test_runtime_collection_failure_is_fail_closed(tmp_path: Path) -> None:
    _manifest(tmp_path)
    result = PTP.prove_transferred_clone(
        tmp_path, collection_seconds=900,
        runner=lambda *_args, **_kwargs: {"ok": True, "returncode": 0},
        collection_runner=lambda *_args, **_kwargs: {"ok": False, "reason": "ui_health_timeout"},
        asset_verifier=lambda *_args, **_kwargs: {"ok": True},
        current_fingerprint=lambda: "pc-b",
        clone_verifier=lambda *_args, **_kwargs: {"ok": True},
    )
    assert result["portable_ready"] is False
    assert result["reason"] == "collection_proof_failed"


def test_missing_post_transfer_assets_stop_before_launch(tmp_path: Path) -> None:
    _manifest(tmp_path)
    result = PTP.prove_transferred_clone(
        tmp_path,
        current_fingerprint=lambda: "pc-b",
        clone_verifier=lambda *_args, **_kwargs: {"ok": True},
        asset_verifier=lambda *_args, **_kwargs: {"ok": False, "missing": ["tools/python/python.exe"]},
    )
    assert result["reason"] == "post_transfer_assets_failed"
    assert result["steps"] == []
