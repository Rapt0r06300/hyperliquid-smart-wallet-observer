from __future__ import annotations

from hl_observer.simulation.economic_objective import (
    canonical_family,
    evaluate_daily_net,
    evaluate_objective,
)


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
        "vault_generalization": {"sample_count": 20, "net_bps": 3.0},
        "copy_checkpoint_integrity": {
            "schema_version": "hypersmart.copy_vault_checkpoint_integrity.v1",
            "receipt_valid": True,
            "writer_role": "BOUND_WRITER",
            "writer_run_id": "writer-clean-1",
            "clean_epoch_ms": 1_000,
            "duplicate_checkpoint_ids": 0,
            "quarantined_checkpoint_metaorders": 0,
            "proof_trade_count": 4,
            "expected_proof_trade_count": 4,
            "all_proof_trades_exact_checkpoint_bound": True,
            "all_proof_trades_same_writer_run": True,
            "all_proof_trades_post_clean_epoch": True,
        },
        "daily_target_required": True,
        "daily_evidence": {
            "schema_version": "hypersmart.daily_net_evidence.v1",
            "target_net_usd_per_day": 4.0,
            "sample_count": 1,
            "observed_trade_count": 4,
            "missing_trade_timestamps": 0,
            "missing_trade_net": 0,
            "days": [
                {
                    "date_utc": "2024-09-05",
                    "net_pnl_usd": 4.6,
                    "trade_count": 4,
                    "at_or_above_target": True,
                }
            ],
            "total_net_pnl_usd": 4.6,
            "mean_daily_net_pnl_usd": 4.6,
            "min_daily_net_pnl_usd": 4.6,
            "all_days_at_or_above_target": True,
        },
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


def test_copy_refuse_heldout_absent_trop_petit_ou_negatif():
    missing = evaluate_objective(_proof(vault_generalization=None))
    assert "COPY_HELDOUT_VAULT_PROOF_MISSING" in missing["objective_reasons"]

    small = evaluate_objective(
        _proof(vault_generalization={"sample_count": 4, "net_bps": 3.0})
    )
    assert "COPY_HELDOUT_VAULT_SAMPLE_TOO_SMALL" in small["objective_reasons"]

    negative = evaluate_objective(
        _proof(vault_generalization={"sample_count": 20, "net_bps": -0.1})
    )
    assert "COPY_HELDOUT_VAULT_NET_NOT_POSITIVE" in negative["objective_reasons"]


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


def test_preuve_non_liquidable_reste_non_certifiable():
    result = evaluate_objective(_proof(LIQUIDATABLE_NET=False))
    assert result["objective_status"] == "NON_ATTEINT"
    assert result["eligible_net_pnl_usd"] is None
    assert "NOT_LIQUIDATABLE_NET" in result["objective_reasons"]


def test_placebo_non_battu_reste_non_certifiable():
    result = evaluate_objective(_proof(placebos={"beaten": False}))
    assert result["objective_status"] == "NON_ATTEINT"
    assert result["eligible_net_pnl_usd"] is None
    assert "PLACEBO_NOT_BEATEN" in result["objective_reasons"]


def test_preuve_dupliquee_reste_non_certifiable():
    result = evaluate_objective(_proof(duplicate_trade_ids=1))
    assert result["objective_status"] == "NON_ATTEINT"
    assert result["eligible_net_pnl_usd"] is None
    assert "DUPLICATE_TRADE_IDENTITIES" in result["objective_reasons"]


def test_copy_checkpoint_integrity_gate_fails_closed_without_clean_epoch() -> None:
    missing = evaluate_objective(_proof(copy_checkpoint_integrity=None))
    assert missing["objective_status"] == "NON_ATTEINT"
    assert "COPY_CHECKPOINT_INTEGRITY_NOT_CLEAN" in missing["objective_reasons"]

    quarantined = evaluate_objective(
        _proof(
            copy_checkpoint_integrity={
                **_proof()["copy_checkpoint_integrity"],
                "duplicate_checkpoint_ids": 1,
                "quarantined_checkpoint_metaorders": 1,
                "all_proof_trades_post_clean_epoch": False,
            }
        )
    )
    assert quarantined["objective_status"] == "NON_ATTEINT"
    assert "COPY_CHECKPOINT_INTEGRITY_NOT_CLEAN" in quarantined["objective_reasons"]


def test_daily_net_groups_only_supplied_closed_trades_by_utc_day() -> None:
    result = evaluate_daily_net(
        [
            {"exit_ts_ms": 1_725_571_200_000, "net_pnl_usd": 4.25},
            {"exit_ts_ms": 1_725_571_200_001, "net_pnl_usd": -0.25},
            {"exit_ts_ms": 1_725_657_600_000, "net_pnl_usd": 5.0},
        ]
    )

    assert result["total_net_pnl_usd"] == 9.0
    assert result["mean_daily_net_pnl_usd"] == 4.5
    assert result["min_daily_net_pnl_usd"] == 4.0
    assert result["all_days_at_or_above_target"] is True


def test_daily_net_fails_closed_for_missing_timestamp_or_bad_day() -> None:
    result = evaluate_daily_net(
        [
            {"exit_ts_ms": 1_725_571_200_000, "net_pnl_usd": 3.99},
            {"net_pnl_usd": 10.0},
        ]
    )

    assert result["missing_trade_timestamps"] == 1
    assert result["min_daily_net_pnl_usd"] == 3.99
    assert result["all_days_at_or_above_target"] is False


def test_daily_net_accepts_nanosecond_close_timestamps() -> None:
    result = evaluate_daily_net(
        [{"exit_ts_ns": 1_725_571_200_000_000_000, "net_pnl_usd": 4.25}]
    )

    assert result["days"][0]["date_utc"] == "2024-09-05"
    assert result["all_days_at_or_above_target"] is True


def test_daily_target_is_a_strict_per_family_gate() -> None:
    below = evaluate_objective(
        _proof(
            daily_evidence={
                **_proof()["daily_evidence"],
                "min_daily_net_pnl_usd": 3.99,
                "all_days_at_or_above_target": False,
            }
        )
    )
    assert below["objective_status"] == "NON_ATTEINT"
    assert "DAILY_NET_TARGET_NOT_REACHED" in below["objective_reasons"]

    missing = evaluate_objective(_proof(daily_evidence=None))
    assert "DAILY_NET_PROOF_MISSING" in missing["objective_reasons"]
