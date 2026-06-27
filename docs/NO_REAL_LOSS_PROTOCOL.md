# No Real Loss Protocol

No Real Loss means no real capital is exposed by the software.

It does **not** mean guaranteed profit. It means:

- observe first;
- collect read-only data first;
- simulate locally first;
- use paper trading before any testnet work;
- keep testnet mock USDC locked until explicit confirmation;
- keep mainnet out of scope.

The software must refuse ambiguous or unsafe configuration. If data is
insufficient, the correct decision is refusal.

## Wallet scoring

Scoring a wallet does not expose capital because it uses local historical data
only. A score is an observation aid, not an instruction to trade. If the local
fills do not contain enough usable history or closed PnL points, the correct
result is `INSUFFICIENT_DATA`, `NEEDS_MORE_HISTORY` or `INVALID_DATA`.

## Paper trading

Paper trading cannot expose capital because it is stored and simulated locally.
The goal is not to hide losses; the goal is to model losses, fees, spread,
slippage and latency before any future testnet work is considered.

A local paper profit is not a guarantee. It is only a simulated result under
the assumptions configured for the run.

## Runtime and archive safety

No real loss also means no fragile operational packaging. Runtime files such as
active SQLite databases are not source artifacts. Clean archives must exclude
runtime DBs and logs so a locked database cannot block a release and cannot be
mistaken for versioned source.

Explorer observation, WebSocket monitoring, ranking, pattern detection and
backtesting remain research-only. They do not create executable orders.

## Copy observer interpretation

Copy-mode output is observation and local paper/mock-USDC simulation only.
`edge_remaining_bps` is a measurement gate, not a promise. A rejected
`SignalCandidate` is recorded in `no_trade_report`; an accepted candidate is
only eligible for local paper accounting and is never an external order.
