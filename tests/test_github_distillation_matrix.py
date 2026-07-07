from hl_observer.strategies.github_distillation import (
    distillation_status_counts,
    priority_distillation_matrix,
)


def test_priority_distillation_matrix_covers_first_repos_to_audit():
    matrix = priority_distillation_matrix()
    repo_ids = {idea.repo_id for idea in matrix}

    assert "17_rezzecup_whale_wallet_mirror_copy_trader" in repo_ids
    assert "15_chaininsighter_solana_copy_trading_bot" in repo_ids
    assert "28_jackhuang166_hyberliquid_arbitrage_bot" in repo_ids
    assert "22_freqtrade" in repo_ids
    assert "33_hummingbot" in repo_ids
    assert "35_enarjord_passivbot" in repo_ids
    assert "11_prediction_market_backtesting" in repo_ids
    assert "13_polymarket_agents" in repo_ids
    assert "14_tradingview_lightweight_charts" in repo_ids


def test_distilled_github_ideas_are_not_direct_runtime_engines():
    matrix = priority_distillation_matrix()

    assert matrix
    assert all(idea.direct_runtime_execution is False for idea in matrix)
    assert all(idea.activation_rule.strip() for idea in matrix)


def test_distillation_matrix_targets_the_single_hypersmart_pipeline():
    matrix = priority_distillation_matrix()
    joined_targets = " ".join(" ".join(idea.target_modules) for idea in matrix)

    assert "risk" in joined_targets
    assert "paper" in joined_targets
    assert "backtest" in joined_targets
    assert "dashboard" in joined_targets
    assert "ui" in joined_targets


def test_distillation_status_counts_are_stable():
    counts = distillation_status_counts()

    assert counts["SHADOW_RESEARCH"] >= 7
    assert counts["VALIDATION"] == 1
    assert counts["UI_ONLY"] == 1
