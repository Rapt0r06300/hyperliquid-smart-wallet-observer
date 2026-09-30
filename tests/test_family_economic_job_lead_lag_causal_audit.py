from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "src" / "hl_observer" / "ops" / "family_economic_job.py"


def test_lead_lag_full_alone_runs_diagnostic_causal_audit() -> None:
    text = JOB.read_text(encoding="utf-8")
    assert 'request["suite"] == "lead-lag-full"' in text
    assert '"03_lead_lag_causal_audit"' in text
    assert '"lead_lag_causal_audit.py"' in text
    assert "Autopsie causale Lead-Lag 8 bps diagnostic-only" in text


def test_family_job_keeps_paper_only_guards_after_new_step() -> None:
    text = JOB.read_text(encoding="utf-8")
    assert '"paper_only": True' in text
    assert '"real_execution": False' in text
    assert '"start_live_collection": False' in text
    assert "_assert_execution_disabled()" in text


def test_diagnostic_step_is_after_canonical_campaign_and_before_connection_audit() -> None:
    text = JOB.read_text(encoding="utf-8")
    campaign = text.index('"02_economic_campaigns"')
    diagnostic = text.index('"03_lead_lag_causal_audit"')
    connection = text.index('"04_connection_audit"')
    assert campaign < diagnostic < connection
