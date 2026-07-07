# Architecture Phase 0

## Decision
The active runtime is `src/hl_observer`. The older `hyper_smart_observer` package remains a compatibility bridge for historical commands and safety checks.

## Phase 0 Scope
Phase 0 creates two foundations:

1. A small central `core` package for config, structured logging, errors, retry, circuit breaker, state snapshots.
2. A ledger-based paper simulation package that can explain PnL from events.

## New Runtime Modules
- `src/hl_observer/core/config.py`: simulation-only core config.
- `src/hl_observer/core/error_handler.py`: structured error events and JSONL output.
- `src/hl_observer/core/circuit_breaker.py`: CLOSED/OPEN/HALF_OPEN breaker.
- `src/hl_observer/core/retry.py`: bounded retry with exponential backoff.
- `src/hl_observer/core/state_manager.py`: atomic JSON state snapshots.
- `src/hl_observer/core/main.py`: factory for the core runtime.

## Paper Ledger Modules
- `src/hl_observer/simulation/paper_event.py`: canonical paper event taxonomy.
- `src/hl_observer/simulation/paper_ledger.py`: cash, positions, realized/unrealized PnL, fees, funding, equity, drawdown.
- `src/hl_observer/simulation/orderbook_execution_simulator.py`: L2-book-based paper fills, partial/missed fill detection.
- `src/hl_observer/simulation/slippage_model.py`: average fill and slippage estimation.
- `src/hl_observer/simulation/fee_model.py`: fee calculation.
- `src/hl_observer/simulation/funding_payment_tracker.py`: funding cash impact.
- `src/hl_observer/simulation/pnl_reconciliation.py`: single equation to detect PnL drift.
- `src/hl_observer/audit/simulation_realism_audit.py`: verifies ledger snapshots expose enough accounting truth and reconciliation.

## Runtime Boundary
The Phase 0 ledger is not a replacement for the existing `paper_trading.PaperEngine`; it is the accounting source of truth to progressively wire into it. The existing engine remains preserved.

## Safety Boundary
No new module imports exchange SDKs, signs payloads, sends orders, or calls `/exchange`. All actions are local paper events.

---

## Architecture cible confirmée — 2026-07-02 (STEP 2)

**Runtime canonique** : `src/hl_observer` (lancé par `tools/start_hypersmart_simulation.ps1` → `python -m hl_observer ui`, port 8794).

**Flux de référence (end-to-end)** :
collecte HL read-only (`hyperliquid/` REST + `realtime/` WS + `collection/`)
→ normalisation (`normalization/`, `market_data/`)
→ features/microstructure (`features/`, `market_signals/`)
→ scoring wallets (`scoring/`, `wallets/`)
→ décision + edge net + no-trade (`signals/`, `edge/`, `decision` = `signals/`+`risk/`)
→ risk gate (`risk/`)
→ sizing (`copy_wallet/`, `copy_mode/`)
→ **moteur PnL runtime** (`hyper_smart_observer/dydx_v4` engine+live_observer, ACTIVE_BRIDGE)
→ **ledger comptable** (`src/hl_observer/paper_trading` + `ledger`, source de vérité)
→ réconciliation (`audit/` pnl_audit + `pnl_reconciliation`)
→ dashboard read-only (`ui/`, `dashboard/`)
→ backtest/replay parité (`backtest/`, `backtesting/`).

**Principe** : additif. On renforce l'existant, on n'introduit pas de 3ᵉ architecture, on ne recrée pas de dossiers doublons. Les doublons historiques constatés (`backtest/`+`backtesting/`, `copy_wallet/`+`copy_mode/`+`copying/`+`following/`, `simulation/`+`paper_trading/`) sont documentés comme dette à consolider progressivement, pas à supprimer.

**Garde-fou sécurité** (inchangé) : read-only + paper-only. Aucun endpoint d'exécution réel, aucune clé, aucune signature réelle. Mots trading autorisés en sim/test/mock/doc ; seule l'action réelle est interdite.
