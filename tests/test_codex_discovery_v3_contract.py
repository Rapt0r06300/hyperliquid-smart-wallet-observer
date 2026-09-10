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
    assert "12" in text
    assert "minimum" in text and "8" in text
    assert "5" in text and "archetype" in text
    assert "hypothesis_ledger" in text
    assert "parameter_only" in text
    assert "improve" in text and "combine" in text and "pivot" in text and "stop" in text
    assert "needs-challenger" in text
    assert "3" in text and "challenger" in text


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


def test_runbook_preserves_machine_daily_contract() -> None:
    text = _text("docs/CODEX_GOAL_RUNBOOK.md")
    assert "un seul agent llm" in text
    assert "aucun sous-agent" in text
    assert "codex_quant_batch.py" in text
    assert "0,99" in text or "0.99" in text
    assert "2 jours utc complets" in text
    assert "+4.00 usd net/jour" in text
    assert "needs-rediscovery" in text
    assert "needs-challenger" in text


def test_runbook_preserves_model_budget_policy_without_bloating_agents() -> None:
    runbook = _text("docs/CODEX_GOAL_RUNBOOK.md")
    agents = _text("AGENTS.md")
    assert "gpt-5.6 sol" in runbook
    assert "high" in runbook or "élevé" in runbook
    assert "fast off" in runbook
    assert "xhigh" in runbook and "exception" in runbook
    assert "gpt-5.6 sol" not in agents


def test_runbook_treats_recent_head_mechanisms_as_existing_baselines() -> None:
    text = _text("docs/CODEX_GOAL_RUNBOOK.md")
    assert "lead-lag maker/taker/streaming" in text
    assert "cross-venue v5" in text
    assert "copy-vault" in text
    assert "base_sha" in text
    assert "delta git" in text


def test_agents_routes_through_v32_compact_context_and_max_quota_saving() -> None:
    text = _text("AGENTS.md")
    assert len(text) < 6500
    assert "discovery v3.2" in text
    assert "python tools/codex_research_context.py --auto" in text
    assert "process_memory" in text
    assert "codex_semantic_discovery.py" in text
    assert "historique git complet" in text and "interdit" in text
    assert "775" in text and "interdit" in text
    assert "sous-agents ia" in text and "interdits" in text
    assert "+4.00 usd net" in text


def test_v32_runbook_and_skill_make_context_first_and_model_turns_sparse() -> None:
    runbook = _text("docs/CODEX_GOAL_RUNBOOK.md")
    skill = _text(".agents/skills/alina-quant-research/SKILL.md")
    reference = _text(".agents/skills/alina-quant-research/references/discovery-v32.md")
    for text in (runbook, skill):
        assert "discovery v3.2" in text
        assert "python tools/codex_research_context.py --auto" in text
        assert "codex_semantic_discovery.py" in text
        assert "process_memory" in text
        assert "pas de scan" in text or "ne pas rescanner" in text
    assert "1 décision modèle" in runbook
    assert "résumé compact" in runbook
    assert "cpu" in reference and "semantic" in reference
    assert "retest" in reference and "veto" in reference
