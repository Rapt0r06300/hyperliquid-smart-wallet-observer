# HyperSmart V23 - License and Portage Audit

Scope: local Hyperliquid research/simulation only. This file records what can be copied directly and what must be reimplemented behaviorally.

Source metadata was refreshed with `python tools/github_fusion_intake.py --network-read --output-dir docs/research`.

## Summary

- Repos audited by metadata tool: 36
- Direct copy allowed only when license is permissive and attribution/tests are added.
- GPL/AGPL/MS-PL/unknown/no-license repos are treated as `PORT_BEHAVIOR`, not raw source copy.
- Runtime remains `src/hl_observer`.
- All imported behavior must end at RiskEngine/PaperEngine/backtest/dashboard only.
- Real external trading remains forbidden.

## Generated Source

- JSON: `docs/research/hypersmart_v19_github_code_intake.json`
- Markdown: `docs/research/HYPERSMART_V19_GITHUB_CODE_INTAKE.md`
- Queue: `docs/research/HYPERSMART_V19_GITHUB_FUSION_QUEUE.md`

## Current Portage Decisions

| Repo family | License outcome | V23 decision | HyperSmart modules already connected | Tests |
|---|---|---|---|---|
| Copy-wallet repos with missing/unknown license | no raw copy | PORT_BEHAVIOR | `copy_wallet/*`, `risk/risk_engine_v3.py`, `paper_trading/*` | `tests/test_refactor_fusion_wallet_copy_e2e.py` |
| Hummingbot / permissive connectors | Apache-2.0 | COPY_ADAPTED or PORT_BEHAVIOR in small modules | `connectors/*`, `paper_trading/paper_engine.py` | `tests/test_v12_connectors_research.py`, `tests/test_paper_engine_realized_unrealized_pnl_equity.py` |
| Funding/arbitrage repos | mixed | PORT_BEHAVIOR unless permissive and isolated | `arbitrage/*`, `funding/*` | `tests/test_refactor_fusion_arbitrage_e2e.py`, `tests/test_refactor_fusion_funding_e2e.py` |
| Freqtrade/OctoBot/AGPL/GPL strategy repos | GPL/AGPL | PORT_BEHAVIOR only | `optimization/profit_optimizer.py`, `backtesting/*` | `tests/test_refactor_fusion_backtest_e2e.py`, `tests/test_hypersmart_v19_negative_pnl_audit.py` |
| TradingView lightweight-charts | Apache-2.0 | COPY_ADAPTED only with attribution; current work is local adapter usage | `ui/static/*` | `tests/test_v12_chart_series.py` |

## Safety Boundary

- PaperIntent can be created.
- PaperTrade can be simulated.
- Backtest orders can be replayed.
- `/exchange`, signatures, private keys, wallet-connect and real orders must not be executable in runtime.
- Fixtures may appear only when labeled as fixtures and never as live market data.

## Next Portage Work

1. Replace remaining fixture-only sections in `refactor_fusion/runner.py` with optional real runtime inputs when available.
2. Keep fixtures as E2E contract tests, not as UI PnL truth.
3. Add attribution headers if any permissive source code is ever copied directly.
4. Extend dashboard payload with PnL truth mode and export-state counts.
