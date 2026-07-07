# HyperSmart V23 - Source to Target File Map

| Repo | Source behavior | Decision | Target file(s) | Tests | Status |
|---|---|---|---|---|---|
| Rezzecup / terauss / copy-wallet family | mirror leader fills, proportional sizing, no-trade on weak edge | PORT_BEHAVIOR | `src/hl_observer/copy_wallet/*`, `src/hl_observer/risk/risk_engine_v3.py` | `tests/test_refactor_fusion_wallet_copy_e2e.py` | WIRED |
| Hummingbot / connector family | connector boundaries, read-only adapter shape | PORT_BEHAVIOR/COPY_ADAPTED if attributed later | `src/hl_observer/connectors/*` | `tests/test_v12_connectors_research.py` | PARTIAL |
| Hyperliquid arbitrage repos | cross-source spread after fees/slippage/funding | PORT_BEHAVIOR | `src/hl_observer/arbitrage/*` | `tests/test_refactor_fusion_arbitrage_e2e.py` | WIRED |
| Funding arbitrage repos | rolling funding window, spike detection | PORT_BEHAVIOR | `src/hl_observer/funding/*` | `tests/test_refactor_fusion_funding_e2e.py` | WIRED |
| Freqtrade/backtesting repos | no-lookahead replay, strategy tournament | PORT_BEHAVIOR | `src/hl_observer/backtesting/*`, `src/hl_observer/optimization/*` | `tests/test_refactor_fusion_backtest_e2e.py` | WIRED |
| Dashboard/chart repos | local dashboard payload and chart adapter | PORT_BEHAVIOR/COPY_ADAPTED only if attribution added | `src/hl_observer/dashboard/*`, `src/hl_observer/ui/static/*` | `tests/test_refactor_fusion_dashboard_e2e.py` | WIRED |

No row claims raw source copy. Current state is behavior porting plus local paper tests only.
Real external trading remains forbidden for every mapped module: `real_execution=false`, no wallet connect, no private key, no signature, no live order, no operational `/exchange`.
