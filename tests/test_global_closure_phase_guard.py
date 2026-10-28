from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.verify_global_closure_phase import verify_phase_snapshot


def _analyze_state(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "phase": "ANALYZE",
        "epoch": 9,
        "requested_at_utc": "2026-10-28T09:00:00Z",
        "collection_started_at_utc": "2026-10-27T09:00:00Z",
        "collection_cutoff_at_utc": "2026-10-28T09:00:00Z",
        "source_collection_epoch": 8,
        "analysis_stage": "SCOREBOARD",
        **overrides,
    }


def _write_state(path: Path, state: dict[str, object]) -> None:
    path.write_text(json.dumps(state), encoding="utf-8")


def test_phase_snapshot_accepts_exact_validated_state(tmp_path: Path) -> None:
    state_path = tmp_path / "alina-phase.json"
    _write_state(state_path, _analyze_state())

    actual = verify_phase_snapshot(
        state_path,
        phase="ANALYZE",
        stage="SCOREBOARD",
        epoch="9",
        source_collection_epoch="8",
        cutoff="2026-10-28T09:00:00Z",
    )

    assert actual == {
        "phase": "ANALYZE",
        "stage": "SCOREBOARD",
        "epoch": "9",
        "source_collection_epoch": "8",
        "cutoff": "2026-10-28T09:00:00Z",
    }


@pytest.mark.parametrize(
    ("changed_state", "expected"),
    [
        ({"phase": "COLLECT", "epoch": 10, "analysis_stage": None,
          "source_collection_epoch": None, "collection_cutoff_at_utc": None},
         {"phase": "ANALYZE", "stage": "SCOREBOARD", "epoch": "9",
          "source_collection_epoch": "8", "cutoff": "2026-10-28T09:00:00Z"}),
        ({"epoch": 10},
         {"phase": "ANALYZE", "stage": "SCOREBOARD", "epoch": "9",
          "source_collection_epoch": "8", "cutoff": "2026-10-28T09:00:00Z"}),
        ({"analysis_stage": "DONE"},
         {"phase": "ANALYZE", "stage": "SCOREBOARD", "epoch": "9",
          "source_collection_epoch": "8", "cutoff": "2026-10-28T09:00:00Z"}),
        ({"source_collection_epoch": 7},
         {"phase": "ANALYZE", "stage": "SCOREBOARD", "epoch": "9",
          "source_collection_epoch": "8", "cutoff": "2026-10-28T09:00:00Z"}),
        ({"collection_cutoff_at_utc": "2026-10-27T09:00:00Z"},
         {"phase": "ANALYZE", "stage": "SCOREBOARD", "epoch": "9",
          "source_collection_epoch": "8", "cutoff": "2026-10-28T09:00:00Z"}),
    ],
)
def test_phase_snapshot_refuses_stale_or_changed_state(
    tmp_path: Path,
    changed_state: dict[str, object],
    expected: dict[str, str],
) -> None:
    state_path = tmp_path / "alina-phase.json"
    _write_state(state_path, _analyze_state(**changed_state))

    with pytest.raises(ValueError, match="phase snapshot changed"):
        verify_phase_snapshot(state_path, **expected)


def test_phase_snapshot_refuses_malformed_canonical_state(tmp_path: Path) -> None:
    state_path = tmp_path / "alina-phase.json"
    _write_state(state_path, _analyze_state(epoch=0))

    with pytest.raises(SystemExit, match="invalid phase epoch"):
        verify_phase_snapshot(
            state_path,
            phase="ANALYZE",
            stage="SCOREBOARD",
            epoch="9",
            source_collection_epoch="8",
            cutoff="2026-10-28T09:00:00Z",
        )


def test_phase_snapshot_rejects_boolean_epoch(tmp_path: Path) -> None:
    state_path = tmp_path / "alina-phase.json"
    _write_state(state_path, _analyze_state(epoch=True))

    with pytest.raises(SystemExit, match="invalid phase epoch"):
        verify_phase_snapshot(
            state_path,
            phase="ANALYZE",
            stage="SCOREBOARD",
            epoch="9",
            source_collection_epoch="8",
            cutoff="2026-10-28T09:00:00Z",
        )


def test_workflow_cli_verifies_snapshot_and_fails_cleanly_when_stale(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "alina-phase.json"
    _write_state(state_path, _analyze_state())
    script = Path(__file__).resolve().parents[1] / "tools" / "verify_global_closure_phase.py"
    command = [
        sys.executable,
        str(script),
        "--state",
        str(state_path),
        "--phase",
        "ANALYZE",
        "--stage",
        "SCOREBOARD",
        "--epoch",
        "9",
        "--source-collection-epoch",
        "8",
        "--cutoff",
        "2026-10-28T09:00:00Z",
    ]

    current = subprocess.run(command, capture_output=True, text=True, check=False)
    assert current.returncode == 0
    assert "canonical phase snapshot verified" in current.stdout

    _write_state(state_path, _analyze_state(epoch=10))
    stale = subprocess.run(command, capture_output=True, text=True, check=False)
    assert stale.returncode != 0
    assert "phase snapshot changed" in stale.stderr
