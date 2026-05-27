# HyperSmart Observer Safety

HyperSmart Observer follows a deny-by-default policy.

## Hard rules

- Mainnet execution is forbidden.
- Real-money execution is out of scope.
- No private key is required for research or paper trading.
- Testnet execution is locked by default.
- Future testnet execution must require `--confirm-testnet-only`.
- Secrets must never be logged.

## SafetyViolation

`SafetyViolation` is raised when configuration or an action violates the
runtime policy. It carries a reason code so refusals can be audited.

## Reason codes

- `MAINNET_FORBIDDEN`
- `REAL_MONEY_FORBIDDEN`
- `EXECUTION_DISABLED_BY_DEFAULT`
- `TESTNET_CONFIRMATION_REQUIRED`
- `SECRET_LOGGING_BLOCKED`
- `UNSUPPORTED_PLATFORM`
- `AMBIGUOUS_RUNTIME_MODE`
- `CONFIGURATION_REFUSED`

## Why mainnet is forbidden

The project is a research, analysis, paper trading and testnet mock-USDC lab.
Mainnet trading would expose real capital and is outside Sprint 1 and the
No Real Loss Protocol.

## Sprint 2 read-only network policy

Read-only Hyperliquid collection must be explicitly requested with a network
read flag. The client is limited to the info endpoint, validates wallet
addresses, rejects forbidden execution endpoints and never signs requests.

## Sprint 3 scoring policy

Wallet scores are research-only. They may rank local historical observations,
but they are not signals and never authorize execution. The scorer uses only
local SQLite fills and refuses to create final scores when fills, closed PnL
points, history length or confidence are insufficient.

The risk engine exposes an observation-only gate for wallet scores. A passing
wallet score means "eligible for research observation", not "trade this".

## Sprint 4 paper trading guardrails

Paper trading is a local simulation only. A `PaperIntent` is a hypothetical
request to simulate, and a `PaperTrade` is a SQLite record. Neither can become
an external order in Sprint 4.

Before a paper simulation opens, the risk engine must accept the intent for
`PAPER_SIMULATION_ONLY`. Missing scores, low confidence, low sample quality,
invalid prices, invalid sides, oversized notionals and max-open-trade limits all
produce refusals. Refusals are stored as risk events when configured.

The simulator always applies fee, spread, slippage and latency assumptions so
paper results are not shown as frictionless or guaranteed.

## Long-run runtime and dashboard guardrails

HyperSmart runtime databases must live in `data/`, not in `logs/`. `logs/`
is for text logs only. Clean archives exclude `logs/`, `data/`, SQLite
DB/WAL/SHM files, caches, virtualenvs, archives and `.env`.

The dashboard is read-only HTML. It must not contain controls for trade, buy,
sell, execute, copy trade, connect wallet, private keys or deletion. Explorer
observer and WebSocket monitor are read-only and disabled by default.

## Copy mode guardrails

`copy-run`, `copy-report` and the dashboard copy panels are research-only.
`edge_remaining_bps` is mandatory before a paper/mock-USDC candidate can be
accepted. Unknown deltas, missing edge, stale observations, bad liquidity,
excessive copy degradation and close/reduce actions without a matching local
paper position are refused and written to `no_trade_report`.

Batch 6 testnet remains locked. `promote-testnet-candidates` is a dry-run
refusal/report command only and does not implement a testnet executor.
