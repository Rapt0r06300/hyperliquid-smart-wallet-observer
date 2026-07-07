# HyperSmart V23 - Module Portage Matrix

| Module family | Original feature | HyperSmart target | Conflict decision | Test file | Status |
|---|---|---|---|---|---|
| Copy wallet | leader mirror, proportional sizing, latency/slippage budget | `copy_wallet`, `risk`, `paper_trading` | Hyperliquid fills/deltas only; no external execution | `tests/test_refactor_fusion_wallet_copy_e2e.py` | DONE slice |
| Arbitrage | cross venue spread after costs | `arbitrage` | paper opportunity only; CEX fixture in E2E until live source exists | `tests/test_refactor_fusion_arbitrage_e2e.py` | DONE slice |
| Funding | funding spike scan | `funding` | no hedge execution; paper signal only | `tests/test_refactor_fusion_funding_e2e.py` | DONE slice |
| Backtest | fee/slippage/delay replay | `backtesting` | no lookahead; negative results preserved | `tests/test_refactor_fusion_backtest_e2e.py` | DONE slice |
| PnL audit | decision logs + snapshot truth | `analysis/negative_pnl_auditor.py` | separate fresh session PnL from historical decision cache | `tests/test_hypersmart_v19_negative_pnl_audit.py` | DONE |
| Dashboard payload | panels for loss/copy/arbitrage/funding/backtest | `dashboard/*`, `refactor_fusion/runner.py` | fixtures labeled; no fake live truth | `tests/test_refactor_fusion_dashboard_e2e.py` | DONE slice |

Safety boundary: Paper/local simulation only; `real_execution=false` for every module; real external trading, wallet connect, private key, signature, live order and operational `/exchange` remain forbidden.
