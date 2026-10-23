"""The restore drill must verify the publisher's exact health receipt schema."""
from __future__ import annotations

import hashlib
import json
import sys

import pytest

from tools import restore_durable_state as restore


def _write_fixture(tmp_path, *, schema: str, blocked: bool = False):
    campaigns = tmp_path / "campaigns"
    campaigns.mkdir()
    phase = tmp_path / "phase.json"
    phase.write_text(json.dumps({
        "phase": "COLLECT",
        "epoch": 8,
        "requested_at_utc": None,
        "collection_started_at_utc": None,
        "collection_cutoff_at_utc": None,
        "source_collection_epoch": None,
        "analysis_stage": None,
    }), encoding="utf-8")
    health = tmp_path / "health.json"
    body = {
        "schema_version": schema,
        "phase_consistency": {"status": "BLOCKED" if blocked else "CONSISTENT"},
    }
    body["receipt_digest"] = hashlib.sha256(
        restore.canonical(body).encode()
    ).hexdigest()
    health.write_text(json.dumps(body), encoding="utf-8")
    return campaigns, phase, health


def _run(monkeypatch, tmp_path, *, schema: str, blocked: bool = False, tamper: bool = False):
    campaigns, phase, health = _write_fixture(tmp_path, schema=schema, blocked=blocked)
    if tamper:
        value = json.loads(health.read_text(encoding="utf-8"))
        value["unexpected"] = "tampering"
        health.write_text(json.dumps(value), encoding="utf-8")
    target = tmp_path / "restore.json"
    monkeypatch.setattr(sys, "argv", [
        "restore_durable_state.py",
        "--campaign-dir", str(campaigns),
        "--health", str(health),
        "--phase", str(phase),
        "--output", str(target),
    ])
    return target, restore.main()


@pytest.mark.parametrize("schema", [
    "alina.dataset_health_receipt.v1",
    "alina.dataset_health_receipt.v2",
])
def test_accepts_signed_publisher_schema_and_stays_read_only(tmp_path, monkeypatch, schema):
    target, rc = _run(monkeypatch, tmp_path, schema=schema)
    result = json.loads(target.read_text(encoding="utf-8"))
    assert rc == 0
    assert result["cache_used"] is False
    assert result["paper_only"] and result["read_only"]
    assert result["real_execution"] is False
    digest = result.pop("receipt_digest")
    assert digest == hashlib.sha256(restore.canonical(result).encode()).hexdigest()


def test_tampered_health_digest_is_rejected(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="health receipt digest mismatch"):
        _run(monkeypatch, tmp_path, schema="alina.dataset_health_receipt.v2", tamper=True)


def test_blocked_phase_is_rejected(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="health receipt reports active campaign phase mismatch"):
        _run(monkeypatch, tmp_path, schema="alina.dataset_health_receipt.v2", blocked=True)


def test_unknown_health_schema_is_rejected(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="unsupported health receipt schema"):
        _run(monkeypatch, tmp_path, schema="alina.dataset_health_receipt.v3")
