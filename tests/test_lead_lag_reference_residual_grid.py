from __future__ import annotations

from hl_observer.backtesting import lead_lag_reference_residual_grid as module


def _row(ts: int, price: float, source: str = "aligned.jsonl") -> dict[str, object]:
    return {"observable_at_ms": ts, "price": price, "source_id": source}


def test_reference_residual_grid_detecte_un_signal_causal_aligne() -> None:
    reference = [_row(1_000, 100.0), _row(2_000, 101.0)]
    follower = [_row(1_000, 10.0), _row(2_000, 10.2)]

    shocks, diagnostics = module.detect_reference_residual_shocks(
        reference,
        follower,
        window_ms=1_000,
        threshold_bps=50.0,
        beta=0.5,
        beta_asof_ms=900,
    )

    assert shocks == [(2_000_000_000, 1.0)]
    assert diagnostics["causal_evaluations"] == 1
    assert diagnostics["signals"] == 1
    assert diagnostics["selection_scope"] == "TRAIN_ONLY_PRE_FREEZE"
    assert diagnostics["heldout_loaded"] is False
    assert diagnostics["real_execution"] is False


def test_reference_residual_grid_echoue_ferme_si_source_non_alignee() -> None:
    reference = [_row(1_000, 100.0, "ref.jsonl"), _row(2_000, 101.0, "ref.jsonl")]
    follower = [_row(1_000, 10.0, "follower.jsonl"), _row(2_000, 10.2, "follower.jsonl")]

    shocks, diagnostics = module.detect_reference_residual_shocks(
        reference,
        follower,
        window_ms=1_000,
        threshold_bps=1.0,
        beta=1.0,
        beta_asof_ms=900,
    )

    assert shocks == []
    assert diagnostics["unmeasurable_reasons"] == {"NO_COMMON_ALIGNED_SOURCE": 1}


def test_reference_residual_grid_refuse_un_beta_connu_apres_le_debut_de_fenetre() -> None:
    rows = [_row(1_000, 100.0), _row(2_000, 101.0)]

    shocks, diagnostics = module.detect_reference_residual_shocks(
        rows,
        rows,
        window_ms=1_000,
        threshold_bps=1.0,
        beta=1.0,
        beta_asof_ms=1_001,
    )

    assert shocks == []
    assert diagnostics["unmeasurable_reasons"] == {"BETA_NOT_CAUSAL": 1}


def test_reference_residual_trial_count_inclut_toutes_les_politiques_predeclarees() -> None:
    expected_per_pair = (
        len(module.REFERENCE_RESIDUAL_BETAS)
        * len(module.REFERENCE_RESIDUAL_WINDOWS_MS)
        * len(module.REFERENCE_RESIDUAL_THRESHOLDS_BPS)
        * len(module.REFERENCE_RESIDUAL_HORIZONS_MS)
        * len(module.REFERENCE_RESIDUAL_DIRECTION_POLICIES)
    )

    assert module.reference_residual_trial_count(2) == 2 * expected_per_pair
    assert module.reference_residual_trial_count(0) == 0
