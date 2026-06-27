# HyperSmart Observer Roadmap

## Sprint 1

Secure foundations: config, safety, models, SQLite, repositories, CLI, tests.

## Sprint 2

Read-only Hyperliquid `/info`: `userFills`, `userFillsByTime`,
`clearinghouseState`, `openOrders`, pagination and rate-limit handling.
Implemented as a bounded collector with explicit network opt-in.

## Sprint 3

Wallet scoring: net PnL after fees, winrate, profit factor, drawdown,
confidence scoring and insufficient-sample refusal.
Implemented as a local SQLite scorer. Scores are research-only, require enough
fills/history/closed-PnL points, and store refusal reasons instead of inventing
missing trade-level data.

## Sprint 4

Realistic paper trading: fees, slippage, latency, stress tests and forward
testing. Sprint 4 should consume Sprint 3 scores only through risk gates and
must remain local paper simulation with no execution.
Implemented as a local paper simulator with `PaperIntent`, stored paper trades,
fees, spread, slippage, latency and risk-event refusals.

## Sprint 5

Local dashboard: wallet rankings, score summaries, paper simulations, refused
paper intents and risk logs. Sprint 5 must remain read-only UI/reporting.
Long-run RC adds the first read-only dashboard export plus runtime hygiene,
archive tooling, Explorer observer scaffolding, WebSocket read-only planning,
wallet discovery, lifecycle reconstruction, ranking V2, pattern detection,
local backtesting and an automated safety audit.

## Sprint 6

Locked testnet executor with mock USDC only and explicit confirmation. In the
current copy-mode batch this is documentation/refusal only; no executor is
active.

## Copy Observer Batches

- Batch 1: leaderboard shortlist, delta detector, SignalCandidate,
  `edge_remaining_bps`, no-trade report.
- Batch 2: local shortlist file, copy tables, source health/failure surfaces,
  duplicate guard schema and bounded collection rules.
- Batch 3: read-only WebSocket planning for shortlist users, max 10
  user-specific subscriptions, duration-limited dry-run.
- Batch 4: local replay/backtesting with fees, spread, slippage and latency.
- Batch 5: read-only paper mock USDC dashboard UX.
- Batch 6: future testnet is locked/documented only; no executor is active.

## Out of scope

Mainnet trading remains out of scope.
