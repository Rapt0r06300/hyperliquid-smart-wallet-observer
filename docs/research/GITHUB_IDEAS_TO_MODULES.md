# GitHub Ideas To HyperSmart Modules

| Source | What to reproduce | Decision | Target module | Test |
|---|---|---|---|---|
| Rezzecup whale mirror | Wallet mirror, proportional sizing, slippage budget | PORT_BEHAVIOR | `src/hl_observer/copy_wallet`, `src/hl_observer/simulation` | `tests/test_paper_ledger.py` |
| terauss Polymarket copy | Multi-trader hot path, dedupe, conflict resolver | PORT_BEHAVIOR | `src/hl_observer/signals`, `src/hl_observer/copy_mode` | existing copy tests |
| ChainInsighter | Copy session controller, latency monitoring | PORT_BEHAVIOR | `src/hl_observer/copy_wallet`, `src/hl_observer/core` | `tests/test_retry_policy.py` |
| tony trader | Risk flags, exits, dashboard explanation | PORT_BEHAVIOR | `src/hl_observer/risk`, `src/hl_observer/dashboard` | existing risk/UI tests |
| Jackhuang Hyperliquid arb | Hyperliquid spread scanner | PORT_BEHAVIOR | `src/hl_observer/arbitrage` | arbitrage tests |
| rustjesty arb | Dual-leg hedge simulation, basis/funding | PORT_BEHAVIOR | `src/hl_observer/arbitrage`, `src/hl_observer/simulation` | funding tests |
| gajesh funding arb | Funding history, spike detection, payment tracking | PORT_BEHAVIOR | `src/hl_observer/funding`, `src/hl_observer/simulation/funding_payment_tracker.py` | `tests/test_paper_ledger.py` |
| Hummingbot | Connector/strategy/paper execution architecture | INSPIRE_ONLY | `src/hl_observer/connectors`, `src/hl_observer/strategies` | connector tests |
| ArbiBot | Low-latency event queue, graceful shutdown | PORT_BEHAVIOR | `src/hl_observer/realtime`, `src/hl_observer/core` | circuit/retry tests |
| Triangular-Arbitrage | Graph cycles and path cost | PORT_BEHAVIOR | `src/hl_observer/arbitrage` | triangular tests |
| Freqtrade | Dry-run, backtest, lookahead/recursive analysis | PORT_BEHAVIOR | `src/hl_observer/backtesting` | backtest tests |
| OctoBot/Passivbot/polyrec | Strategy config, protection, replay/reporting | PORT_BEHAVIOR | `src/hl_observer/strategies`, `src/hl_observer/backtesting` | strategy tests |
| TradingView lightweight-charts | Chart payload design | INSPIRE_ONLY | `src/hl_observer/ui/static`, `src/hl_observer/dashboard` | UI/chart tests |
| Polymarket agents/CloddsBot/Harrier | Research tools and explanations | RESEARCH_ONLY | `src/hl_observer/research`, docs | LLM not hot path tests |

## Rule
No GitHub idea can bypass risk gates, paper ledger accounting, or no-real-trade constraints.
