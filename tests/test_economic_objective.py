from __future__ import annotations

from hl_observer.simulation.economic_objective import canonical_family, evaluate_objective


def _segment(
    *,
    gross: float,
    net: float,
    count: int,
    trade_hash: str,
    fees: float = 0.1,
    spread: float = 0.1,
    slippage: float = 0.1,
    latency: float = 0.1,
    **flags,
):
    return {
        "gross_pnl_usd": gross,
        "fees_usd": fees,
        "spread_cost_usd": spread,
        "slippage_cost_usd": slippage,
        "latency_cost_usd": latency,
        "net_pnl_usd": net,
        "sample_count": count,
        "liquidatable_net": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": count,
        "trade_ids_sha256": trade_hash * 64,
        **flags,
    }


def _proof(**overrides):
    row = {
        "family": "copy_vault",
        "paper_read_only": True,
        "real_execution": False,
        "starting_capital_usd": 1000.0,
        "parameters_frozen": True,
        "opened_positions": 4,
        "closed_positions": 4,
        "gross_pnl_usd": 6.0,
        "fees_usd": 0.5,
        "spread_cost_usd": 0.4,
        "slippage_cost_usd": 0.3,
        "latency_cost_usd": 0.2,
        "net_pnl_usd": 4.6,
        "LIQUIDATABLE_NET": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": 4,
        "trade_ids_sha256": "a" * 64,
        "oos": _segment(
            gross=2.7,
            net=2.2,
            count=2,
            trade_hash="b",
            fees=0.2,
            no_lookahead=True,
        ),
        "forward": _segment(
            gross=2.8,
            net=2.4,
            count=2,
            trade_hash="c",
            post_freeze=True,
        ),
        "placebos": {"beaten": True},
    }
    row.update(overrides)
    return row


def test_arbitrage_alias_ne_cree_pas_une_quatrieme_famille():
    assert canonical_family("arbitrage") == "cross_venue_dislocation_v2"
    assert canonical_family("cross_venue_dislocation") == "cross_venue_dislocation_v2"
    assert canonical_family("cross_venue_dislocation_v1") == "cross_venue_dislocation_v1"


def test_objectif_strict_atteint_avec_preuve_complete():
    result = evaluate_objective(_proof())
    assert result["objective_status"] == "ATTEINT"
    assert result["proof_net_pnl_usd"] == 4.6
    assert result["eligible_net_pnl_usd"] == 4.6


def test_pnl_affiche_sans_slippage_ni_forward_est_non_atteint():
    result = evaluate_objective(_proof(slippage_cost_usd=None, forward=None))
    assert result["objective_status"] == "NON_ATTEINT"
    assert result["eligible_net_pnl_usd"] is None
    assert "UNMEASURED:slippage_cost_usd" in result["objective_reasons"]
    assert "FORWARD_POST_FREEZE_PROOF_MISSING" in result["objective_reasons"]


def test_position_ouverte_et_pnl_non_reconcilie_sont_refuses():
    result = evaluate_objective(_proof(closed_positions=3, net_pnl_usd=5.0))
    assert "POSITIONS_NOT_FULLY_OPENED_AND_CLOSED" in result["objective_reasons"]
    assert "ECONOMIC_RECONCILIATION_FAILED" in result["objective_reasons"]


def test_execution_non_paper_est_refusee():
    result = evaluate_objective(_proof(paper_read_only=False, real_execution=True))
    assert "NOT_PAPER_READ_ONLY" in result["objective_reasons"]


def test_parametres_non_geles_et_cross_mono_jambe_sont_refuses():
    result = evaluate_objective(
        _proof(
            family="cross_venue_dislocation_v2",
            parameters_frozen=False,
            all_positions_two_leg_closed=False,
        )
    )
    assert "PARAMETERS_NOT_FROZEN_BEFORE_EVALUATION" in result["objective_reasons"]
    assert "CROSS_VENUE_TWO_LEG_CLOSE_PROOF_MISSING" in result["objective_reasons"]


def test_pnl_train_ne_compte_jamais_dans_la_preuve_quatre_dollars():
    result = evaluate_objective(
        _proof(
            gross_pnl_usd=101.4,
            net_pnl_usd=100.0,
            oos=_segment(
                gross=0.8,
                net=0.4,
                count=2,
                trade_hash="d",
                no_lookahead=True,
            ),
            forward=_segment(
                gross=0.9,
                net=0.5,
                count=2,
                trade_hash="e",
                post_freeze=True,
            ),
        )
    )

    assert result["proof_net_pnl_usd"] == 0.9
    assert result["eligible_net_pnl_usd"] is None
    assert "TARGET_NET_USD_NOT_REACHED" in result["objective_reasons"]


def test_preuve_exige_des_echantillons_oos_et_forward_non_vides():
    result = evaluate_objective(
        _proof(
            oos={"net_pnl_usd": 2.2, "sample_count": 0, "no_lookahead": True},
            forward={"net_pnl_usd": 2.4, "sample_count": 0, "post_freeze": True},
        )
    )

    assert "OOS_SAMPLE_MISSING" in result["objective_reasons"]
    assert "FORWARD_SAMPLE_MISSING" in result["objective_reasons"]
    assert result["eligible_net_pnl_usd"] is None


def test_preuve_positive_sans_detail_des_couts_est_refusee():
    result = evaluate_objective(
        _proof(
            oos={"net_pnl_usd": 2.2, "sample_count": 2, "no_lookahead": True},
        )
    )

    assert result["proof_net_pnl_usd"] is None
    assert "OOS_UNMEASURED:fees_usd" in result["objective_reasons"]
    assert "OOS_TRADE_ID_PROOF_INCOMPLETE" in result["objective_reasons"]
