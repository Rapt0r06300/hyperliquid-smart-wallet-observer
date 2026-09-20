# Event Intelligence causal candidates

This layer turns structured external events into research candidates only when the
market itself confirms that a measurable price-discovery lag still exists.

It is deliberately stricter than a news trading rule.

## Causal sequence

At a decision timestamp Alina may use only:

1. an external event already ingested by Alina;
2. a recent pre-event baseline for each venue;
3. market snapshots whose receive timestamp is not later than the decision time;
4. current BBO snapshots still inside the freshness budget.

Future snapshots are ignored even if they exist in a replay file.

## Candidate states

- WATCH: the event is valid but a non-Hyperliquid venue has not yet confirmed a
  sufficiently large move.
- UNMEASURABLE: the market lag may exist but required economic or market evidence
  is missing, including the cost floor.
- REJECTED: source quality, freshness, executable room, or net room failed.
- CANDIDATE: a non-Hyperliquid venue confirmed direction, Hyperliquid still lags at
  its executable BBO side, and configured costs leave minimum net room.

A CANDIDATE is still not a promoted trading strategy.

## Executable-side rule

For an upward leader move, Hyperliquid is measured at its ask.

For a downward leader move, Hyperliquid is measured at its bid.

This prevents a mid-price lag from being counted as room that could not have been
entered at the observed BBO.

## Costs

The candidate engine does not invent fees or slippage.

The caller must supply a cost_floor_bps that represents the economic floor for the
experiment. If it is absent, the result is UNMEASURABLE/COST_FLOOR_MISSING.

The initial filter is:

gross executable room
minus cost floor
equals net research room.

A candidate passes only if net research room remains above the configured minimum.

This is still a pre-backtest filter. Full promotion must later use actual venue fees,
spread, depth/VWAP slippage, runtime latency, fill probability, capacity and exit
economics.

## Event-quality gates

News candidates can require minimum World Monitor importance and credibility.

Prediction candidates require a minimum absolute probability change.

Cross-source candidates can require a minimum structured-event severity.

Corroboration and the number of market venues confirming the same direction are
configurable rather than hard-coded assumptions.

Coverage states partial, stale, unavailable, error and disabled are fail-closed.

## PnL validation path

The intended research path is:

external event
-> market leader confirmation
-> executable Hyperliquid lag
-> cost-aware candidate
-> replay outcome
-> matched no-event control
-> placebo timestamps
-> chronological OOS
-> frozen forward paper validation
-> incremental net PnL versus the existing module baseline.

No candidate should be considered an edge merely because the leader-to-Hyperliquid
gap was positive once.
