# HyperSmart V23 - GitHub Engine Matrix

This matrix summarizes the executable V23 slice. Full license metadata lives in `docs/research/HYPERSMART_V19_GITHUB_CODE_INTAKE.md`.

| Tier | Engine | Repos mapped | What is ported now | HyperSmart modules | E2E status |
|---|---|---|---|---|---|
| P0 | Wallet copy | copy-wallet repos, Hummingbot connector concepts | mirror candidate, tier/rank decay, proportional sizing, slippage budget, RiskEngineV3, paper journal | `copy_wallet/*`, `risk/risk_engine_v3.py` | PASS targeted |
| P0 | Negative PnL audit | Freqtrade-like validation concepts | decisions + snapshot + embedded decision cache + export state | `analysis/negative_pnl_auditor.py` | PASS targeted |
| P1 | Arbitrage | Hyperliquid/CEX arbitrage repos | spread after cost, liquidity/depth guard, paper opportunity | `arbitrage/*` | PASS targeted |
| P1 | Funding | funding arb repos | funding window + spike paper signal | `funding/*` | PASS targeted |
| P1 | Backtest | prediction-market/freqtrade backtesting ideas | delay/fee/slippage replay, negative PnL preserved | `backtesting/*` | PASS targeted |
| P1 | Dashboard | TradingView/dashboard ideas | dashboard payload with safety flags and real/fixture labels | `dashboard/*` | PASS targeted |

No PnL is fabricated. Fixtures are contract tests only.
Safety boundary: Paper/local simulation only; `real_execution=false` for every engine; real external trading, wallet connect, private key, signature, live order and operational `/exchange` remain forbidden.
