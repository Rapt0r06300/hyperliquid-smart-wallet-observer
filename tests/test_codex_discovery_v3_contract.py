from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8").casefold()


def test_skill_requires_discovery_tournament_rediscovery_and_diverse_pool() -> None:
    text = _text(".agents/skills/alina-quant-research/SKILL.md")
    assert "discovery" in text
    assert "tournament" in text
    assert "rediscovery" in text
    assert "default to **12" in text or "12 structurally distinct" in text
    assert "hard minimum is 8" in text or "minimum" in text and "8" in text
    assert "5 distinct mechanism archetypes" in text or "5" in text and "archetype" in text
    assert "hypothesis_ledger" in text
    assert "baseline=true" in text
    assert "parameter_only" in text
    assert "improve" in text and "combine" in text and "pivot" in text and "stop" in text
    assert "needs-challenger" in text
    assert "3 consecutive" in text
    assert ">=4" in text or ">= 4" in text


def test_discovery_reference_requires_predictive_targets_and_cpu_escalation() -> None:
    text = _text(".agents/skills/alina-quant-research/references/discovery-v31.md")
    assert "12 candidates" in text
    assert "5 archetypes" in text
    assert "champion-challenger" in text
    assert "quantiles" in text
    assert "hazard" in text
    assert "expected net edge" in text
    assert "hayashi-yoshida" in text
    assert "hawkes" in text
    assert "transfer-entropy" in text
    assert "gradient boosting" in text
    assert "the cpu is not quota" in text


def test_runbook_encodes_single_llm_local_compute_and_machine_daily_contract() -> None:
    text = _text("docs/CODEX_GOAL_RUNBOOK.md")
    assert "un seul agent llm" in text
    assert "aucun sous-agent" in text
    assert "codex_quant_batch.py" in text
    assert "0,99" in text or "0.99" in text
    assert "2 jours utc complets" in text
    assert "+4.00 usd net/jour" in text
    assert "needs-rediscovery" in text
    assert "needs-challenger" in text
    assert "12 hypothèses" in text
    assert "5 archétypes" in text


def test_runbook_treats_recent_head_mechanisms_as_existing_baselines() -> None:
    text = _text("docs/CODEX_GOAL_RUNBOOK.md")
    assert "lead-lag maker/taker/streaming" in text
    assert "cross-venue v5" in text
    assert "copy-vault" in text
    assert "baseline=true" in text
    assert "base_sha" in text
    assert "delta git" in text


def test_agents_stays_compact_and_points_to_v31() -> None:
    text = _text("AGENTS.md")
    assert "discovery v3.1" in text
    assert "codex_hypothesis_ledger.py" in text
    assert "codex_goal_runbook.md" in text
    assert "needs-challenger" in text
    assert "sous-agents ia interdits" in text
    assert "+4.00 usd net" in text
