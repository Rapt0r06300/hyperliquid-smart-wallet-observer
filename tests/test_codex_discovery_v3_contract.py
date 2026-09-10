from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8").casefold()


def test_skill_requires_discovery_tournament_rediscovery_and_eight_hypotheses() -> None:
    text = _text(".agents/skills/alina-quant-research/SKILL.md")
    assert "discovery" in text
    assert "tournament" in text
    assert "rediscovery" in text
    assert "at least 8" in text or ">=8" in text or ">= 8" in text
    assert "hypothesis_ledger" in text
    assert "baseline=true" in text
    assert "parameter_only" in text
    assert "improve" in text and "combine" in text and "pivot" in text and "stop" in text


def test_runbook_encodes_single_llm_local_compute_and_machine_daily_contract() -> None:
    text = _text("docs/CODEX_GOAL_RUNBOOK.md")
    assert "un seul agent llm" in text
    assert "aucun sous-agent" in text
    assert "codex_quant_batch.py" in text
    assert "0,99" in text or "0.99" in text
    assert "2 jours utc complets" in text
    assert "+4.00 usd net/jour" in text
    assert "needs-rediscovery" in text


def test_runbook_treats_recent_head_mechanisms_as_existing_baselines() -> None:
    text = _text("docs/CODEX_GOAL_RUNBOOK.md")
    assert "lead-lag maker/taker/streaming" in text
    assert "cross-venue v5" in text
    assert "copy-vault" in text
    assert "baseline=true" in text
    assert "base_sha" in text
    assert "delta git" in text


def test_agents_stays_compact_and_points_to_v3() -> None:
    text = _text("AGENTS.md")
    assert "discovery v3" in text
    assert "codex_hypothesis_ledger.py" in text
    assert "codex_goal_runbook.md" in text
    assert "sous-agents ia interdits" in text
    assert "+4.00 usd net" in text
