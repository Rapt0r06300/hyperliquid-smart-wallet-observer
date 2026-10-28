"""Keep canonical policy and generated evidence aligned with Copy-Vault-only scope."""

from __future__ import annotations

from pathlib import Path

from hl_observer.research.lois_mesurees import markdown as measured_laws_markdown

ROOT = Path(__file__).resolve().parents[1]
SPEC = (
    ROOT / "docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md"
).read_text(encoding="utf-8")


def test_claude_uses_the_current_verdict_vocabulary() -> None:
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "PROVEN / PROMISING / MORE_DATA / UNMEASURABLE / REJECTED" in claude
    assert "PROVEN / MORE_DATA / UNMEASURABLE / KILL" not in claude


def test_canonical_spec_labels_retired_strategy_text_as_inactive() -> None:
    lowered = SPEC.lower()
    stale_instructions = (
        "all three active strategy families",
        "the three active research families",
        "for the three active families",
        "the three families remain independently provable",
        "the three active modules",
        "+5 usd net/day per active family",
        "64 gib ceiling on **new**",
    )
    for instruction in stale_instructions:
        assert instruction not in lowered, (
            f"stale normative instruction remains: {instruction}"
        )

    assert "current copyvault-only operating scope" in lowered
    assert "historical and inactive" in lowered
    assert "default new-download budget is **8 gib**" in lowered


def test_copy_vault_target_is_only_the_terminal_economic_gate() -> None:
    current_policy = SPEC.split("## Canonical-spec governance", maxsplit=1)[0].lower()
    assert "at least +5 usd net/day" in current_policy
    assert "200 usd paper" in current_policy
    assert "terminal economic gate" in current_policy
    assert "after technical corrections and oos/forward-paper evidence" in current_policy


def test_current_analysis_pipeline_runs_copy_vault_only() -> None:
    analysis_pipeline = SPEC.split("### BACKTEST", maxsplit=1)[1]
    analysis_pipeline = analysis_pipeline.split("### SCOREBOARD", maxsplit=1)[0].lower()

    assert "run copy-vault only" in analysis_pipeline
    assert "run the three research families independently" not in analysis_pipeline
    assert "per utc day per module" not in analysis_pipeline


def test_retired_multi_family_research_sections_are_explicitly_historical() -> None:
    lowered = SPEC.lower()
    assert "### edge research program v2 — historical and inactive" in lowered

    convergence = lowered.split(
        "### profitability convergence v6 — historical and inactive", maxsplit=1
    )[1].split("#### economic-distance-to-target accounting", maxsplit=1)[0]
    assert "current economic milestone" not in convergence
    assert "that multi-family target is historical and inactive" in convergence
    assert "the only current economic target is copy-vault's +5 usd net/day" in convergence


def test_active_documents_have_one_copy_vault_target_and_no_old_multi_family_target() -> None:
    runbook = (ROOT / "docs/CODEX_GOAL_RUNBOOK.md").read_text(encoding="utf-8").lower()
    constitution = (ROOT / "docs/HYPERSMART_CONSTITUTION.md").read_text(encoding="utf-8").lower()
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()
    current = (ROOT / "docs/CURRENT_STATE.md").read_text(encoding="utf-8").lower()

    for document in (runbook, constitution, security, current):
        assert "5.00 usd" in document or "5 usd" in document
        assert "copy-vault" in document
    assert "les trois familles" not in runbook
    assert "par famille" not in security
    assert "3×4" not in constitution
    assert "3×4" not in current


def test_measured_laws_preserve_history_without_claiming_runtime_scope() -> None:
    rendered = measured_laws_markdown().lower()
    source = (
        ROOT / "src/hl_observer/research/lois_mesurees.py"
    ).read_text(encoding="utf-8").lower()
    assert "confirmé — en production" not in rendered
    assert "stratégie en production" not in source
    assert "disabled_by_scope" in rendered
    assert "~2 % apr mesuré sur hype" in rendered
