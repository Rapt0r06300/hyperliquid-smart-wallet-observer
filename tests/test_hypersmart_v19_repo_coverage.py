from __future__ import annotations

from hl_observer.analysis.v19_repo_matrix import V19_REPO_FUSION_ITEMS, format_repo_fusion_matrix, repo_urls


REQUIRED_URLS = {
    "https://github.com/Rezzecup/whale-wallet-mirror-copy-trader",
    "https://github.com/tony-42069/trader-tony-v4",
    "https://github.com/terauss/Polymarket-Copy-Trading-Bot",
    "https://github.com/freqtrade/freqtrade",
    "https://github.com/ChainInsighter/Solana-Copy-trading-bot",
    "https://github.com/Jackhuang166/hyberliquid-arbitrage-bot",
    "https://github.com/rustjesty/hyperliquid-drift-arbitrage-bot",
    "https://github.com/hummingbot/hummingbot",
    "https://github.com/notlelouch/ArbiBot",
    "https://github.com/gajesh2007/funding-arb-bot",
    "https://github.com/Drakkar-Software/Triangular-Arbitrage",
    "https://github.com/alsk1992/CloddsBot",
    "https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits",
    "https://github.com/MrFadiAi/Polymarket-bot",
    "https://github.com/lihanyu81/polymarket_lp_tool",
    "https://github.com/yangyuan-zhen/PolyWeather",
    "https://github.com/Composio-HQ/polymarket-kalshi-arbitrage-bot",
    "https://github.com/aarora4/Awesome-Prediction-Market-Tools",
    "https://github.com/NYTEMODEONLY/polyterm",
    "https://github.com/txbabaxyz/mlmodelpoly",
    "https://github.com/txbabaxyz/polyrec",
    "https://github.com/evan-kolberg/prediction-market-backtesting",
    "https://github.com/ent0n29/polybot",
    "https://github.com/Polymarket/agents",
    "https://github.com/tradingview/lightweight-charts",
    "https://github.com/Immutal0/Solana-CopyTrading-Bot",
    "https://github.com/Neron888/Polymarket-copy-trading-bot",
    "https://github.com/warp-id/solana-trading-bot",
    "https://github.com/drakkar-software/octobot",
    "https://github.com/JLowo/gengar_polymarket_bot",
    "https://github.com/djienne/Polymarket-bot",
    "https://github.com/Jonmaa/btc-polymarket-bot",
    "https://github.com/CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot",
    "https://github.com/enarjord/passivbot",
    "https://github.com/pydevtop/interexchange-arbitrage-bot",
    "https://github.com/ramilexe/crypto-arbitrage-bot",
}


def test_v19_repo_matrix_covers_all_requested_repositories():
    assert set(repo_urls()) >= REQUIRED_URLS
    assert len(V19_REPO_FUSION_ITEMS) >= len(REQUIRED_URLS)


def test_v19_repo_matrix_has_transform_risk_modules_and_tests_for_each_repo():
    for item in V19_REPO_FUSION_ITEMS:
        assert item.keep_ideas
        assert item.paper_transform
        assert item.real_action_risk
        assert item.target_modules
        assert item.target_tests


def test_v19_repo_matrix_markdown_states_no_real_execution():
    content = format_repo_fusion_matrix()
    assert "no_real_execution=true" in content
    assert "paper_simulation_only=true" in content
    assert "future_profit_guarantee=false" in content
