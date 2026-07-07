# GitHub Source To Target Map

This file maps external repositories to HyperSmart targets. It does not claim code was copied. Direct copying is blocked until license and runtime safety are reviewed.

| Repo family | Source concept | HyperSmart target | Current status |
|---|---|---|---|
| Copy-trading bots | Watchlist, leader mirroring, proportional paper sizing | `src/hl_observer/copy_wallet`, `src/hl_observer/signals`, `src/hl_observer/simulation` | PARTIAL |
| Hyperliquid arbitrage | Spread/funding scanners | `src/hl_observer/arbitrage`, `src/hl_observer/funding` | PARTIAL |
| Frameworks | Connector/strategy separation | `src/hl_observer/connectors`, `src/hl_observer/strategies` | PARTIAL |
| Backtesting frameworks | Dry-run, replay, lookahead checks | `src/hl_observer/backtesting` | PARTIAL |
| Dashboard/chart libs | Equity curve, markers, diagnostics | `src/hl_observer/ui`, `src/hl_observer/dashboard` | PARTIAL |
| Agent/research repos | Offline explanation and no-trade reports | `src/hl_observer/research` | PARTIAL |

## Phase 0 target
All sources ultimately feed local paper events. PnL truth is `PaperLedger`.
