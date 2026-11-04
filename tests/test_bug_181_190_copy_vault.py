from hl_observer.audit.copy_vault_runtime_audit_controls import (
    backtest_risk_gate_receipt,
    capital_allocation_receipt,
    correlated_exposure_receipt,
    daily_loss_persistence_receipt,
    execution_path_receipt,
    legacy_import_receipt,
    leverage_fresh_mark_receipt,
    startup_secret_receipt,
    subprocess_binary_receipt,
    trading_flag_receipt,
)


def test_bug_181_forbidden_execution_path_is_not_reachable():
    receipt = execution_path_receipt(reachable_modules=["paper", "audit"], forbidden_reachable=["executor"])
    assert receipt["status"] == "PROVEN"


def test_bug_182_environment_requires_explicit_paper_flags():
    receipt = trading_flag_receipt(env={"PAPER_ONLY": True, "READ_ONLY": True, "LIVE_TRADING": False})
    assert receipt["status"] == "PROVEN"


def test_bug_183_startup_does_not_read_private_secrets():
    assert startup_secret_receipt(observed_secret_names=[])["status"] == "PROVEN"
    assert startup_secret_receipt(observed_secret_names=["PRIVATE_KEY"])["status"] == "REJECTED"


def test_bug_184_legacy_import_is_side_effect_free():
    assert legacy_import_receipt(exchange_call_detected=False, import_side_effect_free=True)["status"] == "PROVEN"


def test_bug_185_trading_subprocess_is_rejected():
    assert subprocess_binary_receipt(command=["python", "paper_report.py"])["status"] == "PROVEN"
    assert subprocess_binary_receipt(command=["trading-binary"])["status"] == "REJECTED"


def test_bug_186_backtest_must_recheck_risk_gate():
    assert backtest_risk_gate_receipt(risk_gate_rechecked=False, paper_mode=True)["status"] == "REJECTED"
    assert backtest_risk_gate_receipt(risk_gate_rechecked=True, paper_mode=True)["status"] == "PROVEN"


def test_bug_187_positions_cannot_exceed_capital():
    assert capital_allocation_receipt(position_notionals_usd=[60, 50], capital_usd=100)["status"] == "REJECTED"
    assert capital_allocation_receipt(position_notionals_usd=[60, 40], capital_usd=100)["status"] == "PROVEN"


def test_bug_188_correlated_exposure_is_aggregated_by_cluster():
    receipt = correlated_exposure_receipt(exposures_by_cluster={"btc-beta": 120}, max_exposure_usd=100)
    assert receipt["status"] == "REJECTED"


def test_bug_189_stale_marks_fail_leverage_closed():
    receipt = leverage_fresh_mark_receipt(leverage=2, max_leverage=3, mark_age_ms=10_000, max_mark_age_ms=1_000)
    assert receipt["status"] == "REJECTED"


def test_bug_190_daily_loss_survives_restart():
    receipt = daily_loss_persistence_receipt(previous_loss_usd=5, current_loss_usd=7, persisted=True)
    assert receipt["status"] == "PROVEN"
