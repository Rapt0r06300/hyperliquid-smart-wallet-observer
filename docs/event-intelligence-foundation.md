# Event Intelligence foundation

This first implementation turns external information into causal, replayable
research evidence without adding any real-execution surface.

## Objective

Measure the narrow sequence that can matter economically:

external information becomes available to Alina
-> one venue reacts first
-> Hyperliquid reacts later
-> measure how quickly the reaction gap decays
-> only later test whether any remaining gap survives costs and execution limits.

The module does **not** assume that a news item caused a market move and does not
produce a BUY/SELL decision.

## Implemented contracts

### ExternalEvent

The causal clock is intentionally strict:

- publication time: timestamp reported by the upstream source;
- retrieval time: timestamp when the collector retrieved the source;
- ingest time: timestamp when Alina actually possessed the information;
- available time: always equal to ingest time.

A replay attempting to use an event before ingest time is rejected as
FUTURE_INFORMATION.

The archive-oriented R2 representation stores structured facts and provenance,
not article/source text.

### Event-to-market price discovery

The first measurement layer consumes the existing NativeMarketSnapshot contract
used by the multi-venue stack. It:

- builds a per-venue baseline from the latest exploitable snapshot available at
  or before the external event became available;
- ignores pre-ingest market moves as potential post-event reactions;
- detects the first venue whose event-relative move crosses a configurable bps
  threshold;
- measures event-to-first-venue latency;
- measures event-to-Hyperliquid latency;
- measures leader-to-Hyperliquid lag;
- measures peak event-relative venue dispersion;
- measures the half-life of the leader/Hyperliquid reaction gap;
- remains paper/read-only with real_execution=false.

The output is measurement evidence, not proof of causality or profitability.

## PnL discipline

An observed leader-to-Hyperliquid delay is not an edge by itself. Promotion must
remain blocked until a later economic layer proves, out of sample and after
freeze, that the remaining executable opportunity survives:

- spread;
- fees;
- slippage;
- book depth/capacity;
- runtime latency;
- stale/desynchronized data;
- sample-size requirements;
- placebo and no-event controls.

## Next source adapters

The next implementation wave should feed this contract from structured,
source-attributed inputs, prioritizing:

1. World Monitor structured events and cross-source signals;
2. direct upstream sources where practical, so source -> World Monitor -> Alina
   latency can be measured rather than assumed;
3. read-only prediction-market probability changes;
4. news velocity, corroboration and source-diversity features.

No World Monitor API credential is required by this foundation and no hosted API
call is made by it.
