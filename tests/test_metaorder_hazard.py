from __future__ import annotations

import pytest

from hl_observer.research.metaorder_hazard import (
    UNMEASURABLE,
    compare_metaorders_to_isolated_fills,
)


def test_metaorder_vs_fills_uses_notional_weighted_reconstruction() -> None:
    result = compare_metaorders_to_isolated_fills(
        [{"metaorder_id": "m1", "net_pnl_bps": 15.0}],
        [
            {"metaorder_id": "m1", "net_pnl_bps": 10.0, "notional_usd": 1.0},
            {"metaorder_id": "m1", "net_pnl_bps": 20.0, "notional_usd": 3.0},
        ],
    )

    assert result["status"] == "COMPARABLE"
    assert result["all_matched"] is False
    assert result["comparisons"][0]["isolated_weighted_value"] == pytest.approx(17.5)
    assert result["comparisons"][0]["status"] == "MISMATCH"
    assert result["mismatched_metaorders"] == 1


def test_metaorder_vs_fills_rejette_les_fills_sans_poids_et_ids_inconnus() -> None:
    result = compare_metaorders_to_isolated_fills(
        [{"metaorder_id": "m1", "net_pnl_bps": 10.0}],
        [
            {"metaorder_id": "m1", "net_pnl_bps": 10.0},
            {"metaorder_id": "unknown", "net_pnl_bps": 10.0, "notional_usd": 1.0},
        ],
    )

    assert result["invalid_fills_rejected"] == 1
    assert result["unmatched_fills"] == 1
    assert result["matched_metaorders"] == 0


def test_metaorder_vs_fills_ne_fabrique_pas_de_zero_si_donnees_absentes() -> None:
    result = compare_metaorders_to_isolated_fills([], [])

    assert result["status"] == UNMEASURABLE
    assert result["comparisons"] == []
    assert result["all_matched"] is False


def test_metaorder_vs_fills_refuse_les_ids_agreges_dupliques() -> None:
    result = compare_metaorders_to_isolated_fills(
        [
            {"metaorder_id": "m1", "net_pnl_bps": 10.0},
            {"metaorder_id": "m1", "net_pnl_bps": 10.0},
        ],
        [{"metaorder_id": "m1", "net_pnl_bps": 10.0, "notional_usd": 1.0}],
    )

    assert result["duplicate_metaorders_rejected"] == 1
    assert result["status"] == UNMEASURABLE
