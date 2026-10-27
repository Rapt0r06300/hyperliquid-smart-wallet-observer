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


def test_measured_laws_preserve_history_without_claiming_runtime_scope() -> None:
    rendered = measured_laws_markdown().lower()
    source = (
        ROOT / "src/hl_observer/research/lois_mesurees.py"
    ).read_text(encoding="utf-8").lower()
    assert "confirmé — en production" not in rendered
    assert "stratégie en production" not in source
    assert "disabled_by_scope" in rendered
    assert "~2 % apr mesuré sur hype" in rendered
