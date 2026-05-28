# HYPERSMART ARCHITECTURE RECONCILIATION

## Context
The project contains two distinct package structures: `hyper_smart_observer` (root) and `src/hl_observer`.

## Functional Mapping

| Function | hyper_smart_observer | src/hl_observer | Recommended Official Path |
|---|---|---|---|
| CLI | `hyper_smart_observer.app.main` | `hl_observer.cli` | `hl_observer.cli` (more complete) |
| Config | `hyper_smart_observer.app.config.AppConfig` | `hl_observer.config.settings.Settings` | `hl_observer.config.settings.Settings` |
| /info Client | `HyperliquidInfoClient` | `RestInfoClient` | `RestInfoClient` |
| WebSocket | `WebSocketManager` | `WsClient` | `WsClient` |
| Copy Mode | `hyper_smart_observer/copy_mode/` | `src/hl_observer/copying/` | Merge into `src/hl_observer/copying/` |
| Preflight | `hyper_smart_observer/copy_mode/preflight.py` | (Missing or separate) | Use `hyper_smart_observer` version for now |
| Candidate Importer | `candidate_importer.py` | `leaderboard_import.py` | `leaderboard_import.py` |
| Leaderboard Selector | `leaderboard_selector.py` | `leaderboard_autoselect.py` | `leaderboard_autoselect.py` |
| Delta Detector | `delta_detector.py` | `position_delta_detector.py` | `position_delta_detector.py` |
| Edge Remaining | `edge.py` | `edge_remaining.py` | `edge_remaining.py` |
| No-Trade Report | `no_trade_report.py` | `no_trade_analyzer.py` | Merge into `src/hl_observer/reports/` |
| Paper Trading | `hyper_smart_observer/paper_trading/` | `src/hl_observer/paper/` | `src/hl_observer/paper/` |
| Backtest | `hyper_smart_observer/backtesting/` | `src/hl_observer/backtest/` | `src/hl_observer/backtest/` |
| Dashboard | `hyper_smart_observer/dashboard/` | `src/hl_observer/ui/` | `src/hl_observer/ui/` (FastAPI-based) |
| Archive Clean | `hyper_smart_observer/runtime/archive.py` | `src/hl_observer/runtime/hygiene.py` | `src/hl_observer/runtime/hygiene.py` |
| Safety Audit | `hyper_smart_observer/audit/safety_audit.py` | `src/hl_observer/security/safety_audit.py` | `src/hl_observer/security/safety_audit.py` |

## Recommendation
The `src/hl_observer` structure is the more mature, feature-rich, and UI-integrated architecture. However, some specific logic in `hyper_smart_observer` (especially around Job B and preflight) should be migrated to `src/hl_observer` to achieve a single unified codebase.

**Official Target Architecture:** `src/hl_observer`.
**Immediate Action:** Use `src/hl_observer` for UI and persistence, but keep `hyper_smart_observer` for existing "Copy Loop" CLI commands until full migration.
