from hyper_smart_observer.app.config import RuntimeMode, load_config


def test_hypersmart_default_config_is_research_only(monkeypatch, tmp_path):
    monkeypatch.delenv("HYPERSMART_MODE", raising=False)
    config = load_config(tmp_path / "missing.env")

    assert config.runtime_mode == RuntimeMode.RESEARCH_ONLY
    assert not config.allow_mainnet
    assert not config.execution_enabled
    assert not config.enable_network_reads
    assert config.http_timeout_seconds == 15.0
    assert config.http_max_retries == 2
    assert config.info_max_pages_per_wallet == 5
    assert config.min_fills_to_score == 30
    assert config.min_history_days_to_score == 7.0
    assert config.min_closed_pnl_points == 10
    assert config.score_require_net_pnl is True
    assert config.score_min_confidence == 0.60
    assert config.enable_paper_trading is True
    assert config.paper_max_position_notional == 100.0
    assert config.paper_max_open_trades == 3
    assert config.paper_fee_rate_bps == 5.0
    assert config.paper_slippage_bps == 5.0


def test_hypersmart_database_path_default(monkeypatch, tmp_path):
    monkeypatch.delenv("HYPERSMART_DATABASE_PATH", raising=False)
    config = load_config(tmp_path / "missing.env")

    assert config.database_path.as_posix().endswith("data/hypersmart_observer.sqlite3")
