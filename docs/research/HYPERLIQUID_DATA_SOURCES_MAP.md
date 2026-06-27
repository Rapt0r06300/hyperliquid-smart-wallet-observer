# Hyperliquid Data Sources Map

This research map documents the public data sources that HyperSmart Observer may use for read-only discovery, simulation, and diagnostics. It does not describe a guaranteed profit system. Historical profit, wallet activity, and copied openings are research inputs only; they can still produce losses in live-like simulation.

## Public Sources

- Hyperliquid `/info` REST: bounded read-only calls for user state, fills, open orders, mids, and metadata when network read is explicitly enabled.
- Hyperliquid public WebSocket: market and user-specific public streams, with strict subscription and duration guards.
- Hyperliquid Explorer: public transaction visibility used only as a cautious discovery signal; aggressive scraping, proxy bypass, and rate-limit evasion are refused.
- Local database: previously collected fills, positions, deltas, no-trade decisions, paper ledger, and simulation snapshots.
- Manual imports: CSV, JSON, and JSONL wallet lists with complete addresses only.

## Freshness Rules

- Fresh openings are preferred over historical openings.
- Stale signals must be refused rather than converted into simulated entries.
- Edge remaining must account for spread, slippage, fees, latency, liquidity, and copy degradation.
- Open orders are context only; they are not proof of an executed trade.

## Wallet Selection Use

The data sources are combined to find candidate wallets, rank whale-like wallets, detect same-coin/same-direction clusters, and test paper-only virtual positions. A positive historical PnL does not imply future profit. The correct output is a transparent paper simulation with logs explaining every accepted or refused decision.

## Safety Boundaries

- No real order.
- No private key.
- No signature.
- No `/exchange` call.
- No mainnet execution.
- No testnet executor active in this batch.
- No guaranteed profit claim.

