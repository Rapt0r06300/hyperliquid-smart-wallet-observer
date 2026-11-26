from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "runtime" / "codex_research" / "run_copy_v21_entry_capacity_daily_lock_train.py"
SPEC = importlib.util.spec_from_file_location("copy_v21_train_reproducer_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
REPRODUCER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPRODUCER)


def test_non_reproducible_frozen_inputs_are_persisted_without_running_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source.jsonl"
    source.write_bytes(b"changed")
    freeze_path = tmp_path / "freeze.json"
    expected = b"frozen"
    freeze_path.write_text(
        json.dumps(
            {
                "freeze": {
                    "dataset_provenance": {
                        "files": [
                            {
                                "path": "source.jsonl",
                                "exists": True,
                                "size_bytes": len(expected),
                                "fingerprint": hashlib.sha256(expected).hexdigest(),
                                "fingerprint_method": "FULL_SHA256",
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "reports" / "reproduction.json"
    previous_report = b'{"previous_success":true}\n'
    output.parent.mkdir(parents=True)
    output.write_bytes(previous_report)
    monkeypatch.setattr(REPRODUCER, "ROOT", tmp_path)
    monkeypatch.setattr(REPRODUCER, "FREEZE_PATH", freeze_path)
    monkeypatch.setattr(REPRODUCER, "OUTPUT", output)
    monkeypatch.setattr(
        REPRODUCER,
        "_load_pipeline",
        lambda: pytest.fail("replay must not run when frozen inputs differ"),
    )

    assert REPRODUCER.main() == 2

    assert output.read_bytes() == previous_report
    refusal_reports = list(output.parent.glob("reproduction_refusal_*.json"))
    assert len(refusal_reports) == 1
    refusal_path = refusal_reports[0]
    report = json.loads(refusal_path.read_text(encoding="utf-8"))
    assert report["status"] == "COPY_V21_FROZEN_INPUTS_NOT_REPRODUCIBLE"
    assert report["reproduction_only"] is True
    assert report["economically_proven"] is False
    assert report["economic_proof_allowed"] is False
    assert report["sample_count"] is None
    assert report["daily_mean_net_pnl_usd"] is None
    assert report["input_audit"]["reproduction_allowed"] is False
    assert not refusal_path.with_suffix(refusal_path.suffix + ".tmp").exists()
    stderr_payload = json.loads(capsys.readouterr().err)
    assert stderr_payload["status"] == "COPY_V21_FROZEN_INPUTS_NOT_REPRODUCIBLE"
    assert stderr_payload["output"] == str(refusal_path)

