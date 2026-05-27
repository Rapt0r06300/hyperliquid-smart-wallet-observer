# HyperSmart Copy Observer Batch 1

Batch 1 implements the safe research-only foundation for the requested Hyperliquid wallet-following workflow.

## Architecture

1. Leaderboard shortlist: full wallet addresses only, minimum history, consistency, drawdown, execution-quality and PnL-concentration filters.
2. Copy loop dry-run: observes locally stored leader positions, fills, position deltas and open orders. Default polling is 300 seconds.
3. Reports: dashboard copy status, leader activity and no-trade report.

## Delta Classification

Supported labels:

- `OPEN_LONG`
- `OPEN_SHORT`
- `ADD`
- `INCREASE`
- `REDUCE`
- `CLOSE_LONG`
- `CLOSE_SHORT`
- `UNKNOWN`

Open/add/increase may become paper research candidates if all gates pass. Reduce/close/unknown are reported as no-trade reasons.

## Edge Remaining

`edge_remaining_bps` is mandatory. It is computed after pessimistic copy-degradation costs:

- taker fees;
- spread;
- slippage;
- latency decay;
- adverse selection;
- funding cost placeholder;
- liquidity assumptions.

If the value is non-positive or below the configured minimum, the signal is rejected and logged as a no-trade outcome.

## Safety

This batch is `PAPER_MOCK_USDC` dry-run only. It does not add a testnet executor, does not sign, does not create orders, does not call `/exchange`, and does not support mainnet.

No LLM is used in the copy detection, risk gate, or paper decision hot path.
