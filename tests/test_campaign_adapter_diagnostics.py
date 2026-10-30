from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

import pytest

from hl_observer.control_plane.campaign_adapters import AdapterContext, run_one_unit


def _context(tmp_path: Path, **partition_overrides: object) -> AdapterContext:
    partition = {
        "output_root": str(tmp_path),
        "duration_s": 1,
        **partition_overrides,
    }
    return AdapterContext(
        campaign_id="diagnostic-campaign",
        kind="copy_vault_collection",
        unit_id="unit-001",
        soft_deadline_epoch=time.time() + 60,
        partition=partition,
    )


def _write_bundle(
    output: Path,
    *,
    shard_count: int,
    safe_count: int,
    partial_count: int,
    reject_count: int,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "family": "copy_vault_fills",
                "record_count": 1,
                "trade_count": 1,
                "trade_count_exact": True,
                "bytes": 8,
                "uncompressed_size_exact": True,
                "uncompressed_bytes": 8,
            }
        ),
        encoding="utf-8",
    )
    (output / "BUNDLE_INDEX.json").write_text(
        json.dumps(
            {
                "manifests": ["manifest.json"],
                "shard_count": shard_count,
                "safe_count": safe_count,
                "partial_count": partial_count,
                "reject_count": reject_count,
            }
        ),
        encoding="utf-8",
    )
    (output / "collection_summary.json").write_text(
        json.dumps(
            {
                "accepted_frames": 1,
                "persisted_frames": 1,
                "l2_frames": 0,
                "queue_drops": 0,
            }
        ),
        encoding="utf-8",
    )


def test_soft_deadline_diagnostic_is_timeout_not_empty() -> None:
    context = AdapterContext(
        "diagnostic-campaign",
        "copy_vault_collection",
        "unit-001",
        time.time() - 1,
        {},
    )

    result = run_one_unit(context)

    assert result.status == "CONTINUATION_REQUIRED"
    diagnostic = result.payload["unit_diagnostic"]
    assert diagnostic["schema"] == "alina.copy_vault.adapter_unit_diagnostic.v1"
    assert diagnostic["state"] == "TIMED_OUT"
    assert diagnostic["reason"] == "soft_deadline"
    assert diagnostic["deadline_exceeded"] is True
    assert diagnostic["counts"] == {
        "selected_count": None,
        "completed_count": None,
        "published_count": None,
        "safe_qualified_count": None,
    }
    assert diagnostic["state"] != "EMPTY"


def test_subprocess_timeout_keeps_unit_unpublished(tmp_path: Path) -> None:
    def runner(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(["adapter"], 1)

    result = run_one_unit(_context(tmp_path), runner=runner)

    assert result.status == "CONTINUATION_REQUIRED"
    assert result.payload.get("bundle_root") is None
    assert result.payload["unit_diagnostic"]["state"] == "TIMED_OUT"
    assert result.payload["unit_diagnostic"]["reason"] == "adapter_timeout"
    assert result.payload["last_durable_checkpoint"] is None


def test_unavailable_output_root_is_a_fail_closed_diagnostic(
    tmp_path: Path,
) -> None:
    configured_root = tmp_path / "output-root-file"
    configured_root.write_text("not a directory\n", encoding="utf-8")

    result = run_one_unit(
        _context(configured_root),
        runner=lambda *_args, **_kwargs: pytest.fail(
            "runner must not start when the output root is unavailable"
        ),
    )

    assert result.status == "FAILED"
    assert result.payload["reason"] == "output_root_unavailable"
    assert result.payload["failure_category"] == "OUTPUT_PATH"
    assert result.payload["unit_diagnostic"]["state"] == "FAILED"
    assert result.payload["unit_diagnostic"]["safe_publication_allowed"] is False


def test_subprocess_timeout_preserves_checkpoint_from_output_root(tmp_path: Path) -> None:
    output = tmp_path / "diagnostic-campaign" / "unit-001"
    checkpoint = output / "checkpoint.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text('{"cursor": 9}\n', encoding="utf-8")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()

    def runner(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(["adapter"], 1)

    result = run_one_unit(
        _context(
            tmp_path,
            last_durable_checkpoint={
                "id": "checkpoint-9",
                "path": str(checkpoint),
                "sha256": digest,
            },
        ),
        runner=runner,
    )

    assert result.status == "CONTINUATION_REQUIRED"
    assert result.payload["last_durable_checkpoint"] == {
        "id": "checkpoint-9",
        "path": str(checkpoint.resolve()),
        "sha256": digest,
        "verified": True,
    }
    assert result.payload["unit_diagnostic"]["last_durable_checkpoint"] == (
        result.payload["last_durable_checkpoint"]
    )


def test_subprocess_timeout_preserves_partial_output_for_diagnosis(
    tmp_path: Path,
) -> None:
    def runner(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(
            ["adapter"],
            1,
            output="partial stdout",
            stderr="partial stderr",
        )

    result = run_one_unit(_context(tmp_path), runner=runner)

    assert result.status == "CONTINUATION_REQUIRED"
    assert result.payload["reason"] == "adapter_timeout"
    assert result.payload["partial_stdout"] == "partial stdout"
    assert result.payload["partial_stderr"] == "partial stderr"
    assert result.payload.get("bundle_root") is None


def test_valid_empty_response_is_unavailable_and_distinct_from_timeout(
    tmp_path: Path,
) -> None:
    class Result:
        returncode = 0
        stdout = "valid empty response"
        stderr = ""

    result = run_one_unit(_context(tmp_path), runner=lambda *_a, **_k: Result())

    assert result.status == "UNAVAILABLE"
    assert result.payload["reason"] == "no_durable_collection_events"
    assert result.payload["unit_diagnostic"]["state"] == "EMPTY"
    assert result.payload["unit_diagnostic"]["state"] != "TIMED_OUT"
    assert "bundle_root" not in result.payload
    assert result.payload["counts"]["safe_qualified_count"] is None


def test_interruption_after_verified_checkpoint_is_restartable(tmp_path: Path) -> None:
    output = tmp_path / "diagnostic-campaign" / "unit-001"
    checkpoint = output / "checkpoint.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text('{"cursor": 17}\n', encoding="utf-8")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()

    def runner(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("worker crashed after durable checkpoint")

    result = run_one_unit(
        _context(
            tmp_path,
            selected_count=3,
            attempt=2,
            last_durable_checkpoint={
                "id": "checkpoint-17",
                "path": str(checkpoint),
                "sha256": digest,
            },
        ),
        runner=runner,
    )

    assert result.status == "CONTINUATION_REQUIRED"
    assert result.progressed is True
    assert result.payload["reason"] == "adapter_interrupted"
    assert "bundle_root" not in result.payload
    assert result.payload["unit_diagnostic"]["state"] == "INTERRUPTED"
    assert result.payload["unit_diagnostic"]["attempt"] == 2
    assert result.payload["last_durable_checkpoint"] == {
        "id": "checkpoint-17",
        "path": str(checkpoint.resolve()),
        "sha256": digest,
        "verified": True,
    }
    assert result.payload["counts"]["selected_count"] == 3


def test_restart_reuses_the_same_unit_output_after_checkpoint(tmp_path: Path) -> None:
    output = tmp_path / "diagnostic-campaign" / "unit-001"
    checkpoint = output / "checkpoint.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text('{"cursor": 17}\n', encoding="utf-8")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    partition = {
        "selected_count": 1,
        "attempt": 2,
        "last_durable_checkpoint": {
            "id": "checkpoint-17",
            "path": str(checkpoint),
            "sha256": digest,
        },
    }
    first_calls: list[list[str]] = []

    def interrupted(cmd: list[str], **_kwargs: object) -> object:
        first_calls.append(cmd)
        raise RuntimeError("restart requested")

    first = run_one_unit(
        _context(tmp_path, **partition),
        runner=interrupted,
    )
    assert first.status == "CONTINUATION_REQUIRED"

    class Result:
        returncode = 0
        stdout = "resumed and published"
        stderr = ""

    def resumed(cmd: list[str], **_kwargs: object) -> object:
        assert cmd[cmd.index("--output") + 1] == str(output)
        _write_bundle(
            output,
            shard_count=1,
            safe_count=1,
            partial_count=0,
            reject_count=0,
        )
        return Result()

    second = run_one_unit(
        _context(tmp_path, **partition),
        runner=resumed,
    )
    assert second.status == "COMPLETE"
    assert second.payload["unit_diagnostic"]["state"] == "COMPLETE"
    assert second.payload["unit_diagnostic"]["safe_publication_allowed"] is True
    assert second.payload["counts"]["safe_qualified_count"] == 1
    assert first_calls and first_calls[0][first_calls[0].index("--output") + 1] == str(output)


def test_partial_bundle_cannot_be_published_as_safe(tmp_path: Path) -> None:
    output = tmp_path / "diagnostic-campaign" / "unit-001"

    class Result:
        returncode = 0
        stdout = "partial"
        stderr = ""

    def runner(cmd: list[str], **_kwargs: object) -> object:
        target = Path(cmd[cmd.index("--output") + 1])
        _write_bundle(
            target,
            shard_count=1,
            safe_count=0,
            partial_count=1,
            reject_count=0,
        )
        return Result()

    result = run_one_unit(_context(tmp_path), runner=runner)

    assert result.status == "PARTIAL"
    assert result.payload["reason"] == "collection_publication_unproven"
    assert result.payload["publication_blockers"] == [
        "not_all_shards_safe",
        "partial_shards_present",
    ]
    assert result.payload.get("bundle_root") is None
    assert result.payload["unit_diagnostic"]["safe_publication_allowed"] is False
    assert result.payload["counts"]["safe_qualified_count"] == 0
    assert output.exists()


def test_missing_shard_count_is_partial_not_an_uncaught_type_error(
    tmp_path: Path,
) -> None:
    class Result:
        returncode = 0
        stdout = "bundle with incomplete index"
        stderr = ""

    def runner(cmd: list[str], **_kwargs: object) -> object:
        target = Path(cmd[cmd.index("--output") + 1])
        target.mkdir(parents=True, exist_ok=True)
        (target / "manifest.json").write_text(
            json.dumps({"family": "copy_vault_fills", "record_count": 1}),
            encoding="utf-8",
        )
        (target / "BUNDLE_INDEX.json").write_text(
            json.dumps(
                {
                    "manifests": ["manifest.json"],
                    "safe_count": 1,
                    "partial_count": 0,
                    "reject_count": 0,
                }
            ),
            encoding="utf-8",
        )
        (target / "collection_summary.json").write_text(
            json.dumps(
                {
                    "accepted_frames": 1,
                    "persisted_frames": 1,
                    "l2_frames": 0,
                    "queue_drops": 0,
                }
            ),
            encoding="utf-8",
        )
        return Result()

    result = run_one_unit(_context(tmp_path), runner=runner)

    assert result.status == "PARTIAL"
    assert result.payload["reason"] == "collection_publication_unproven"
    assert "shard_counts_unproven" in result.payload["publication_blockers"]
    assert result.payload["unit_diagnostic"]["state"] == "PARTIAL"
    assert result.payload["unit_diagnostic"]["safe_publication_allowed"] is False

