# World Monitor integration for Event Intelligence

This integration treats World Monitor as a structured, read-only intelligence
source. It does not treat World Monitor scores or classifications as trading
instructions.

## Implemented read-only surfaces

Only three hosted REST endpoints are currently allowlisted:

- `GET /api/intelligence/v1/list-cross-source-signals`
- `GET /api/news/v1/list-feed-digest`
- `GET /api/prediction/v1/list-prediction-markets`

The hosted `api.worldmonitor.app` server requires a World Monitor API key for
server-to-server data calls. The client refuses the request locally when that key
is absent. A self-hosted-compatible base URL can be supplied explicitly.

No POST, webhook registration, scenario mutation, order endpoint, prediction-market
CLOB client, private key, or real-execution surface is present.

## Why these three surfaces come first

### Cross-source signals

World Monitor already emits structured cross-domain detections such as military
flight surges, GPS jamming, cyber escalation, shipping disruption, sanctions
surges, infrastructure outages, market stress and weather extremes.

Alina stores those detections as external evidence. Their severity is not assumed
to predict price direction.

### News digest

The digest exposes quantitative metadata that is more useful to Alina than article
text:

- publication timestamp;
- World Monitor first-seen timestamp;
- publisher;
- current-cycle corroboration/source count;
- cross-cycle mention count;
- story lifecycle phase;
- importance score;
- credibility score;
- threat category/confidence;
- alert flag;
- extracted tickers;
- coverage state.

Alina does not archive the headline, snippet or article body in the R1/R2 event
record. The event identifier hashes the minimum source expression needed for stable
deduplication without preserving that expression in the archive record.

Coverage states such as `stale` and `unavailable` are fail-closed for signal
features. Stale evidence can remain available for audit but cannot drive a live or
replay signal.

### Prediction markets

Prediction-market data is read-only. Alina records a prediction event only after
two causal snapshots exist and the absolute probability move exceeds a configured
threshold. The current default research threshold is 5 percentage points.

No Polymarket trading/CLOB/private-key capability is introduced.

## First quantitative features

The first derived layer now measures:

- unique news events per minute;
- unique publishers;
- source-diversity ratio;
- number of corroborated events;
- breaking-story count;
- alert count;
- corroboration-weighted velocity;
- mean importance score;
- mean credibility score;
- maximum corroboration count;
- current news count versus prior equal-duration buckets;
- causal news-velocity z-score.

All windows use `ingest_ts_ms`. Publication time or source first-seen time may be
stored as evidence but cannot move an event earlier than the instant Alina actually
received it.

## Economic path

These signals feed the existing Event Intelligence price-discovery measurement:

external event
-> first venue reaction
-> Hyperliquid reaction
-> leader-to-Hyperliquid lag
-> reaction-gap half-life
-> later executable-cost evaluation.

The presence of a delay is not considered an edge. Promotion remains blocked until
the candidate survives spread, fees, slippage, depth/capacity, runtime latency,
sample-size, placebo/no-event controls, chronological OOS and post-freeze forward
paper validation.

## Next implementation waves

1. Persistent append-only R1/R2 event archive with checksums and Data Vault
   compatibility.
2. Source-health/freshness bridge into Alina's existing fail-closed source-health
   model.
3. News-leads-market and prediction-leading candidate generation using the
   event-to-market measurement already merged.
4. Direct upstream adapters for selected primary sources so Alina can measure
   source -> World Monitor -> Alina latency rather than assume World Monitor is
   fastest.
5. Event-conditioned Lead-Lag/Cross-Venue/Copy-Vault scoreboards with incremental
   net PnL versus the no-event baseline.
