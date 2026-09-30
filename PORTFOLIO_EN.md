# HyperSmart Observer — Quantitative Research System (paper trading)

> A **read-only** observation and backtesting engine for Hyperliquid, built to **rigorously test
> trading strategies and honestly reject those without a real edge** after costs. Zero real execution,
> zero money at risk — rigor over results.

## In one sentence
I built, from scratch, a system that collects real market data, reconstructs the positions of
"smart-money wallets," and evaluates strategies with professional-grade anti-overfitting discipline —
then concludes *honestly* about what works and what does not.

## What makes this project stand out
Most trading projects show a flattering backtest and promise profits. This one does the opposite:
**it is built not to fool itself.** Every strategy is judged out-of-sample, with real costs, a
robustness test, and a **random-strategy control**. Knowing *when not to trade* is the core skill of a
real quant.

## Technical architecture
- **Read-only collection**: REST Indexer API + multiplexed **WebSocket firehose**, with reconnect,
  gap recovery, pagination, deduplication.
- **SQLite storage** without duplicates; crash-proof "replay" recording (per-process, atomic writes).
- **Position reconstruction** by wallet/subaccount/market/side (OPEN/ADD/REDUCE/CLOSE lifecycle).
- **Replay engine**: 15-dimensional scenario space, database up to **150 M** scenarios, streaming search.
- **Realistic execution simulation**: fees, spread, slippage, latency, copy degradation, plus maker
  (adverse selection) and grid market-making models.
- **From-scratch ML**: logistic regression via gradient descent, train-only standardization.
- **Safety rails**: *paper-only / testnet-locked*, verified by tests — no real order is possible.

## Scientific methodology
Out-of-sample validation (temporal train/test) · anti-overfitting (deployment gate + plateau check) ·
Monte-Carlo bootstrap · **random-strategy control** (the best must beat chance) · real costs everywhere ·
stress-testing on adverse regimes.

## Research studies conducted (all out-of-sample, real costs)

| Study | Question | Honest verdict |
|---|---|---|
| Copy-trading | Does copying whales pay? | No — ~13 bps copy degradation; median edge negative |
| Calibration (1.4 M scenarios) | Is there a winning SL/TP? | No — `robust=0`, none holds out-of-sample |
| Maker entry | Does saving the spread help? | No — 16% fill rate, adverse selection |
| Grid / market-making | Does the "grinder" work? | No — breakeven when calm, catastrophic in trends |
| Mean reversion | A different statistical mechanism? | No — raw edge ~0.6 bps, 20× too small vs costs |
| Mechanism scan + **random** | Which one is best? | All lose; 0/50 random strategies positive (meta-proof) |
| Oracle exit | Is it the SL/TP? | Perfect-exit ceiling +$50k *unrealizable*; a prediction, not calibration, problem |
| Predictive model (ML) | Can we predict winners? | Faint signal, but 15× too weak + regime shift |

**Cross-cutting, quantified and meta-proven conclusion**: in this market, at retail scale, **friction
exceeds the small edges**. The best measured choice is *not to trade*.

## Safety & ethics
Designed to be **impossible to turn into a real loss**: read-only, local simulation, no keys, no
signatures, no deposits. A responsible approach.

## Skills demonstrated
Python · modular architecture · data engineering (REST/WebSocket, SQLite) · concurrent programming ·
quantitative methods (backtesting, OOS validation, Monte-Carlo, cost modeling) · **from-scratch ML** ·
scientific rigor & intellectual honesty · automated testing · technical writing.

## What I learned
That a liquid market is hard to beat, and *why*: public edges disappear, latency costs, transaction
costs eat small advantages, and regimes shift. And above all — that **a research system's value is
measured by its honesty**, not by a flattering PnL number.
