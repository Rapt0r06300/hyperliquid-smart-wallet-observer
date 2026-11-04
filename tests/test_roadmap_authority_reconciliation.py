from __future__ import annotations

from pathlib import Path

from hl_observer.ops.roadmap_authority_reconciliation import (
    inventory_complementary_ideas,
    reconcile_authority,
    reconcile_legacy_775,
)

ROOT = Path(__file__).resolve().parents[1]


def test_authority_reconciliation_is_complete_without_reconstructing_history() -> None:
    result = reconcile_authority(ROOT).as_dict()
    assert result["complete"] is True
    assert result["legacy_775"]["status"] == "SOURCE_LOSS_CLOSED"
    assert result["legacy_775"]["literal_reconstruction_claimed"] is False
    assert result["v5_776_plus"]["pre_run_775_is_separate"] is True
    assert result["complementary_ideas"]["idea_count"] == 100
    assert result["documentation"]["historical_sources_are_not_current_authority"] is True


def test_legacy_775_reconciliation_rejects_a_false_literal_reconstruction(tmp_path: Path) -> None:
    source = ROOT / "docs/PRE_RUN_775_CANONICAL_STATUS.json"
    target = tmp_path / "docs/PRE_RUN_775_CANONICAL_STATUS.json"
    target.parent.mkdir()
    payload = source.read_text(encoding="utf-8").replace(
        '"exact_literal_reconstruction_claimed": false',
        '"exact_literal_reconstruction_claimed": true',
    )
    target.write_text(payload, encoding="utf-8")
    result = reconcile_legacy_775(tmp_path)
    assert result["complete"] is False
    assert result["status"] == "INVALID"
    assert result["mismatches"]["exact_literal_reconstruction_claimed"]["actual"] is True


def test_complementary_ideas_are_not_promoted_to_implementation() -> None:
    result = inventory_complementary_ideas(ROOT)
    assert result["complete"] is True
    assert result["status"] == "INVENTORIED_NOT_PROMOTED"
    assert "not implementation" in result["promotion_rule"]


def test_documentation_inventory_has_current_and_historical_hashes() -> None:
    result = reconcile_authority(ROOT).documentation
    assert result["current_sources"]
    assert result["historical_sources"]
    assert all(len(value) == 64 for value in result["current_sources"].values())
    assert all(len(value) == 64 for value in result["historical_sources"].values())
