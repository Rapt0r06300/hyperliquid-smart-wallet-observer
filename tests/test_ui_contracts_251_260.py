from hl_observer.ops.copy_vault_ui_controls import (
    economic_writer_uniqueness_receipt,
    final_cmd_powershell_override_receipt,
    health_vs_profit_alert_receipt,
    http_refresh_without_pnl_recompute_receipt,
    launcher_vs_strategy_state_receipt,
    local_pnl_vs_certified_receipt,
    refusal_module_link_receipt,
    safe_corpus_status_receipt,
    ui_disabled_family_receipt,
    wallet_stream_delay_receipt,
)


def test_lch251_requires_one_economic_writer() -> None:
    assert economic_writer_uniqueness_receipt([{"writer_id": "w1", "active": True}])["status"] == "PROVEN"
    assert economic_writer_uniqueness_receipt([{"writer_id": "w1", "active": True}, {"writer_id": "w1", "active": False}])["status"] == "REJECTED"


def test_lch252_separates_launcher_and_strategy_state() -> None:
    assert launcher_vs_strategy_state_receipt({"state": "RUNNING"}, {"state": "PAPER"})["status"] == "PROVEN"
    assert launcher_vs_strategy_state_receipt({}, {"state": "PAPER"})["status"] == "UNMEASURABLE"


def test_lch253_reconciles_cmd_and_powershell_override() -> None:
    row = {"cmd_value": "paper", "powershell_value": "paper", "effective_source": "CMD", "conflict": False}
    assert final_cmd_powershell_override_receipt([row])["status"] == "PROVEN"
    row["powershell_value"] = "live"
    assert final_cmd_powershell_override_receipt([row])["status"] == "REJECTED"


def test_lch254_links_refusal_to_module() -> None:
    row = {"refusal_code": "NO_BOOK", "module": "book_loader", "reason": "missing SAFE book"}
    assert refusal_module_link_receipt([row])["status"] == "PROVEN"
    assert refusal_module_link_receipt([{"refusal_code": "NO_BOOK"}])["status"] == "UNMEASURABLE"


def test_lch255_exposes_wallet_delay() -> None:
    row = {"wallet": "w1", "source_ts_ms": 10, "observed_ts_ms": 20}
    assert wallet_stream_delay_receipt([row])["status"] == "PROVEN"
    assert wallet_stream_delay_receipt([{"wallet": "w1", "source_ts_ms": 20, "observed_ts_ms": 10}])["status"] == "UNMEASURABLE"


def test_lch256_separates_local_and_certified_pnl() -> None:
    row = {"origin": "LOCAL_PAPER", "source_ref": "receipt:1", "certified": False}
    assert local_pnl_vs_certified_receipt([row])["status"] == "PROVEN"
    row["certified"] = True
    assert local_pnl_vs_certified_receipt([row])["status"] == "REJECTED"


def test_lch257_ui_cannot_activate_disabled_family() -> None:
    row = {"family": "Copy-Vault", "scope_state": "ACTIVE", "execution_enabled": False}
    assert ui_disabled_family_receipt([row])["status"] == "PROVEN"
    row["family"] = "Arbitrage"
    assert ui_disabled_family_receipt([row])["status"] == "REJECTED"


def test_lch258_safe_status_keeps_gaps_visible() -> None:
    result = safe_corpus_status_receipt({"safe_shards": 10, "gap_count": 2})
    assert result["status"] == "PROVEN"
    assert result["coverage_state"] == "GAPPED"


def test_lch259_http_refresh_does_not_recompute_pnl() -> None:
    row = {"refresh_kind": "HTTP_STATUS", "pnl_recomputed": False, "pnl_cache_hash": "sha"}
    assert http_refresh_without_pnl_recompute_receipt([row])["status"] == "PROVEN"
    row["pnl_recomputed"] = True
    assert http_refresh_without_pnl_recompute_receipt([row])["status"] == "REJECTED"


def test_lch260_health_and_profit_alerts_are_separate() -> None:
    row = {"alert_type": "HEALTH", "code": "collector_down", "healthy": False}
    assert health_vs_profit_alert_receipt([row])["status"] == "PROVEN"
    row["code"] = "profit_down"
    assert health_vs_profit_alert_receipt([row])["status"] == "REJECTED"
