from __future__ import annotations

import pytest

from hl_observer.research.exit_factory import (
    comparer_sortie_autonome_et_suivi_aveugle,
    simuler_exit,
)


def test_comparaison_autonome_et_aveugle_partage_chemins_couts_et_risque() -> None:
    chemins = [[0.0, 10.0, 20.0, 5.0], [0.0, -5.0, 12.0, 8.0]]

    result = comparer_sortie_autonome_et_suivi_aveugle(
        chemins,
        regle_autonome="TAKE_PROFIT",
        regle_aveugle="HORIZON_FIXE",
        tp_bps=15.0,
        horizon=3,
        cost_bps=9.0,
        risk_penalty_bps=1.0,
    )

    assert result["status"] == "COMPARABLE"
    assert result["same_paths"] is True
    assert result["same_costs"] is True
    assert result["autonomous"]["n"] == result["blind_follow"]["n"] == 2
    assert result["delta_net_moyen_bps"] == pytest.approx(7.5)
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False


def test_comparaison_refuse_une_regle_non_gelee() -> None:
    result = comparer_sortie_autonome_et_suivi_aveugle(
        [[0.0, 1.0]],
        regle_autonome=None,
    )

    assert result["status"] == "NO_FROZEN_AUTONOMOUS_RULE"
    assert result["autonomous"] is None


def test_simulation_de_sortie_rejette_un_cout_non_fini() -> None:
    with pytest.raises(ValueError, match="cost_bps"):
        simuler_exit([0.0, 1.0], regle="HORIZON_FIXE", cost_bps=float("nan"))
