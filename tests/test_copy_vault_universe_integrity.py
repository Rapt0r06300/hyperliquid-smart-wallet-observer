from __future__ import annotations

from hl_observer.backtesting.copy_vault_universe_integrity import (
    evaluate_copy_vault_universe_integrity,
)


def test_universe_non_declare_fail_closed() -> None:
    result = evaluate_copy_vault_universe_integrity(
        complete_universe=[],
        observed_survivors=[],
        cohort=[],
        correlations={},
        entity_groups={},
    )
    assert result["eligible"] is False
    assert "UNIVERSE_NOT_DECLARED" in result["reasons"]


def test_survivor_hors_univers_et_couverture_incomplete_sont_refuses() -> None:
    result = evaluate_copy_vault_universe_integrity(
        complete_universe=["A", "B"],
        observed_survivors=["A", "C"],
        cohort=[{"wallet": "A", "liquide": False}],
        correlations={},
        entity_groups={},
    )
    assert result["eligible"] is False
    assert set(result["reasons"]) >= {
        "SURVIVOR_OUTSIDE_UNIVERSE",
        "COHORT_COVERAGE_INCOMPLETE",
    }
    assert result["missing_from_cohort"] == ["b"]


def test_sybil_suspect_doit_etre_normalise_dans_meme_entite() -> None:
    result = evaluate_copy_vault_universe_integrity(
        complete_universe=["A", "B"],
        observed_survivors=["A", "B"],
        cohort=[{"wallet": "A", "liquide": False}, {"wallet": "B", "liquide": False}],
        correlations={("a", "b"): 0.99},
        entity_groups={"a": "entity-a", "b": "entity-b"},
    )
    assert result["eligible"] is False
    assert "SYBIL_ENTITY_NORMALIZATION_MISSING" in result["reasons"]


def test_univers_complet_survivorship_corrige_et_sybil_normalise_est_eligible() -> None:
    result = evaluate_copy_vault_universe_integrity(
        complete_universe=["A", "B", "C"],
        observed_survivors=["A", "B"],
        cohort=[
            {"wallet": "A", "liquide": False},
            {"wallet": "B", "liquide": False},
            {"wallet": "C", "liquide": True},
        ],
        correlations={("a", "b"): 0.99},
        entity_groups={"a": "entity-1", "b": "entity-1", "c": "entity-2"},
    )
    assert result["eligible"] is True
    assert result["reasons"] == []
    assert result["survivorship"]["disparus"] == ["c"]
    assert result["cohort_liquidation_evidence"]["n_liquides"] == 1
    assert result["sybil_detection"]["n"] == 1


def test_correlation_malformee_fail_closed_sans_exception() -> None:
    result = evaluate_copy_vault_universe_integrity(
        complete_universe=["A", "B"],
        observed_survivors=["A", "B"],
        cohort=[{"wallet": "A", "liquide": False}, {"wallet": "B", "liquide": True}],
        correlations={("a", "b"): "not-a-number"},  # type: ignore[dict-item]
        entity_groups={"a": "entity-1", "b": "entity-2"},
    )
    assert result["eligible"] is False
    assert "CORRELATION_EVIDENCE_INVALID" in result["reasons"]
