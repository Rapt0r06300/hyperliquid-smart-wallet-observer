# HyperSmart V24 - license and portage audit

Objectif: eviter le copier-coller non maitrise. Les repos servent de source d'idees et de comportements; le code direct n'est admis que licence compatible.

| Repo | Licence | Statut GitHub | Politique | Frontiere d'action reelle |
|---|---|---|---|---|
| [Rezzecup whale-wallet-mirror-copy-trader](https://github.com/Rezzecup/whale-wallet-mirror-copy-trader) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | Real copy execution and wallet signing must stay excluded from runtime. |
| [tony-42069 trader-tony-v4](https://github.com/tony-42069/trader-tony-v4) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | Any external action controller is not imported into the hot path. |
| [terauss Polymarket-Copy-Trading-Bot](https://github.com/terauss/Polymarket-Copy-Trading-Bot) | NOASSERTION (RuntimeError) | RuntimeError | PORT_BEHAVIOR_NO_DIRECT_COPY | Prediction-market execution logic is not reused as real external execution. |
| [freqtrade](https://github.com/freqtrade/freqtrade) | GPL-3.0 (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | Exchange adapters/execution are not activated. |
| [ChainInsighter Solana-Copy-trading-bot](https://github.com/ChainInsighter/Solana-Copy-trading-bot) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | Solana transaction execution and keys are excluded. |
| [Jackhuang166 hyberliquid-arbitrage-bot](https://github.com/Jackhuang166/hyberliquid-arbitrage-bot) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | No dual-leg real orders; missing leg is always NO_TRADE. |
| [rustjesty hyperliquid-drift-arbitrage-bot](https://github.com/rustjesty/hyperliquid-drift-arbitrage-bot) | MIT (repo_api) | ok | COPY_ADAPTED_ALLOWED_WITH_ATTRIBUTION | No Drift/Hyperliquid live hedge execution. |
| [hummingbot](https://github.com/hummingbot/hummingbot) | APACHE-2.0 (repo_api) | ok | COPY_ADAPTED_ALLOWED_WITH_ATTRIBUTION | Gateway/executor patterns are documentation and paper adapters, not real routing. |
| [notlelouch ArbiBot](https://github.com/notlelouch/ArbiBot) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | Execution loop is not ported. |
| [gajesh2007 funding-arb-bot](https://github.com/gajesh2007/funding-arb-bot) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | No funding-capture real position is opened. |
| [Drakkar-Software Triangular-Arbitrage](https://github.com/Drakkar-Software/Triangular-Arbitrage) | AGPL-3.0 (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | Cycle execution and exchange writes are excluded. |
| [alsk1992 CloddsBot](https://github.com/alsk1992/CloddsBot) | MIT (repo_api) | ok | COPY_ADAPTED_ALLOWED_WITH_ATTRIBUTION | Any live executor remains forbidden. |
| [HarrierOnChain Prediction-Markets-Trading-Bot-Toolkits](https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits) | MIT (repo_api) | ok | COPY_ADAPTED_ALLOWED_WITH_ATTRIBUTION | Market-specific order execution is not ported. |
| [MrFadiAi Polymarket-bot](https://github.com/MrFadiAi/Polymarket-bot) | MIT (repo_api) | ok | COPY_ADAPTED_ALLOWED_WITH_ATTRIBUTION | No Polymarket execution runtime. |
| [lihanyu81 polymarket_lp_tool](https://github.com/lihanyu81/polymarket_lp_tool) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | LP/order placement is not activated. |
| [yangyuan-zhen PolyWeather](https://github.com/yangyuan-zhen/PolyWeather) | AGPL-3.0 (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | Prediction-market trades are out of runtime. |
| [Composio-HQ polymarket-kalshi-arbitrage-bot](https://github.com/Composio-HQ/polymarket-kalshi-arbitrage-bot) | NOASSERTION (RuntimeError) | RuntimeError | PORT_BEHAVIOR_NO_DIRECT_COPY | No CLOB or broker action is imported. |
| [aarora4 Awesome-Prediction-Market-Tools](https://github.com/aarora4/Awesome-Prediction-Market-Tools) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | Directory links do not imply runtime integrations. |
| [NYTEMODEONLY polyterm](https://github.com/NYTEMODEONLY/polyterm) | MIT (repo_api) | ok | COPY_ADAPTED_ALLOWED_WITH_ATTRIBUTION | No external execution through agent tools. |
| [txbabaxyz mlmodelpoly](https://github.com/txbabaxyz/mlmodelpoly) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | Model can filter/score only, never force an entry. |
| [txbabaxyz polyrec](https://github.com/txbabaxyz/polyrec) | MIT (repo_api) | ok | COPY_ADAPTED_ALLOWED_WITH_ATTRIBUTION | No prediction-market order routing. |
| [evan-kolberg prediction-market-backtesting](https://github.com/evan-kolberg/prediction-market-backtesting) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | Backtest never implies future profit. |
| [ent0n29 polybot](https://github.com/ent0n29/polybot) | MIT (repo_api) | ok | COPY_ADAPTED_ALLOWED_WITH_ATTRIBUTION | No live execution mode. |
| [Polymarket agents](https://github.com/Polymarket/agents) | MIT (repo_api) | ok | COPY_ADAPTED_ALLOWED_WITH_ATTRIBUTION | Agent is never in hot-path execution. |
| [tradingview lightweight-charts](https://github.com/tradingview/lightweight-charts) | APACHE-2.0 (repo_api) | ok | COPY_ADAPTED_ALLOWED_WITH_ATTRIBUTION | Chart interactions are read-only. |
| [Immutal0 Solana-CopyTrading-Bot](https://github.com/Immutal0/Solana-CopyTrading-Bot) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | No Solana transaction code in runtime. |
| [Neron888 Polymarket-copy-trading-bot](https://github.com/Neron888/Polymarket-copy-trading-bot) | NOASSERTION (RuntimeError) | RuntimeError | PORT_BEHAVIOR_NO_DIRECT_COPY | No Polymarket runtime. |
| [warp-id solana-trading-bot](https://github.com/warp-id/solana-trading-bot) | MS-PL (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | No Solana execution. |
| [drakkar-software octobot](https://github.com/drakkar-software/octobot) | GPL-3.0 (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | No exchange execution. |
| [JLowo gengar_polymarket_bot](https://github.com/JLowo/gengar_polymarket_bot) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | No external action. |
| [djienne Polymarket-bot](https://github.com/djienne/Polymarket-bot) | MIT (repo_api) | ok | COPY_ADAPTED_ALLOWED_WITH_ATTRIBUTION | No prediction-market execution. |
| [Jonmaa btc-polymarket-bot](https://github.com/Jonmaa/btc-polymarket-bot) | NOASSERTION (repo_api) | ok | PORT_BEHAVIOR_NO_DIRECT_COPY | No Polymarket runtime. |
| [CarlosIbCu polymarket-kalshi-btc-arbitrage-bot](https://github.com/CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot) | NOASSERTION (RuntimeError) | RuntimeError | PORT_BEHAVIOR_NO_DIRECT_COPY | No CLOB execution. |
| [enarjord passivbot](https://github.com/enarjord/passivbot) | NOASSERTION (RuntimeError) | RuntimeError | PORT_BEHAVIOR_NO_DIRECT_COPY | No exchange adapter execution. |
| [pydevtop interexchange-arbitrage-bot](https://github.com/pydevtop/interexchange-arbitrage-bot) | NOASSERTION (RuntimeError) | RuntimeError | PORT_BEHAVIOR_NO_DIRECT_COPY | No external exchange actions. |
| [ramilexe crypto-arbitrage-bot](https://github.com/ramilexe/crypto-arbitrage-bot) | NOASSERTION (RuntimeError) | RuntimeError | PORT_BEHAVIOR_NO_DIRECT_COPY | No routed trade. |

## Synthese

- repos_couverts=36
- licences_permissives=11
- licences_a_revoir=25
- runtime_actif=src/hl_observer
- paper_only=true
- real_execution=false
- future_profit_guarantee=false