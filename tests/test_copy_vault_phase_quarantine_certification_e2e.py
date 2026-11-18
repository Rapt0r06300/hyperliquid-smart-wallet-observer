from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from hl_observer.ops.final_economic_certification import certify_campaign
from tools.collect_cloud_copy_vault import copy_vault_market_envelopes

ROOT = Path(__file__).resolve().parents[1]


def _write_phase_and_manifest(root: Path) -> tuple[Path, Path]:
    phase_path = root / "control" / "alina-phase.json"
    phase_path.parent.mkdir(parents=True, exist_ok=True)
    phase_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "phase": "ANALYZE",
                "epoch": 8,
                "requested_at_utc": "2026-11-01T00:00:00Z",
                "collection_started_at_utc": "2026-10-31T23:00:00Z",
                "collection_cutoff_at_utc": "2026-11-01T00:00:00Z",
                "source_collection_epoch": 7,
                "analysis_stage": "REPLAY",
            }
        ),
        encoding="utf-8",
    )
    manifest_path = root / "replay.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "alina.resumable_campaign.v2",
                "campaign_id": "copy-vault-e8-replay-proof",
                "creation_phase": "ANALYZE",
                "phase_epoch": 8,
                "source_collection_epoch": 7,
                "collection_cutoff_at_utc": "2026-11-01T00:00:00Z",
                "kind": "replay",
            }
        ),
        encoding="utf-8",
    )
    return phase_path, manifest_path


def _run_phase_gate(phase_path: Path, manifest_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "phase_gate.py"),
            "manifest",
            "--state",
            str(phase_path),
            "--manifest",
            str(manifest_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_copy_vault_e2e_gates_epoch_quarantine_and_pnl_refusal(tmp_path: Path) -> None:
    phase_path, manifest_path = _write_phase_and_manifest(tmp_path)

    accepted = _run_phase_gate(phase_path, manifest_path)
    assert accepted.returncode == 0, accepted.stderr

    stale = json.loads(manifest_path.read_text(encoding="utf-8"))
    stale["phase_epoch"] = 7
    manifest_path.write_text(json.dumps(stale), encoding="utf-8")
    rejected = _run_phase_gate(phase_path, manifest_path)
    assert rejected.returncode != 0
    assert "manifest phase/epoch mismatch" in rejected.stderr

    envelopes = copy_vault_market_envelopes(
        {
            "channel": "trades",
            "data": [
                {
                    "coin": "ETH",
                    "time": 1_000,
                    "hash": "trade-1",
                    "px": "100.0",
                    "sz": "0.1",
                    "side": "A",
                },
                {
                    "coin": "ETH",
                    "time": 1_000,
                    "hash": "",
                    "px": "NaN",
                    "sz": "0.1",
                    "side": "A",
                },
            ],
        },
        receive_wall_ms=1_000,
        receive_mono_ns=42,
        connection_id="fixture",
    )
    assert [envelope.channel for envelope in envelopes] == [
        "copy_vault_trades",
        "copy_vault_unknown",
    ]
    assert envelopes[1].parsed_summary["data_gate_ready"] is False
    assert envelopes[1].parsed_summary["unclassified_reason"].startswith("TRADE_ROW_")

    refused = certify_campaign("copy_vault", None)
    assert refused["certified"] is False
    assert refused["eligible_net_pnl_usd"] is None
    assert refused["reasons"] == ["CAMPAIGN_MISSING_OR_UNREADABLE"]
