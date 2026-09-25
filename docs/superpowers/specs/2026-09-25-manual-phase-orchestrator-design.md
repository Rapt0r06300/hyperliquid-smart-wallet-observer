# Manual Phase Orchestrator Design

## Objective

Replace the current mixed continuous campaign behavior with one explicit, versioned operating phase for Alina Smart Flow on GitHub:

- `IDLE`: no new heavy work starts.
- `COLLECT`: only data-collection work is created and scheduled.
- `ANALYZE`: collection drains, then quality checks, replay, backtests, module PnL proof, and scoreboard run without starting new collection windows.

The user controls phase changes manually through ChatGPT/GitHub. GitHub-hosted runners remain the only compute target. No self-hosted runner and no user PC may be used.

The design must preserve strict paper/read-only behavior and must never enable real orders.

## Source of truth

Dataset V2 owns the phase state because it already owns campaign manifests and durable collection metadata.

Create:

`control/alina-phase.json`

Required fields:

```json
{
  "phase": "IDLE",
  "epoch": 1,
  "requested_at_utc": "2026-09-25T00:00:00Z",
  "collection_started_at_utc": null,
  "collection_cutoff_at_utc": null,
  "source_collection_epoch": null,
  "analysis_stage": null
}
```

Rules:

- `phase` is exactly one of `IDLE`, `COLLECT`, or `ANALYZE`.
- `epoch` increments on every phase transition.
- A collection session is identified by its collection epoch.
- Old campaigns from a prior epoch stay auditable but may never become runnable merely because the system later returns to `COLLECT`.
- Every workflow reading the phase file fails closed on invalid JSON, an unknown phase, or missing required fields.

## Phase transitions

### IDLE -> COLLECT

When the user says to start collection:

1. update the phase file to `COLLECT`;
2. increment `epoch`;
3. set `collection_started_at_utc` to the transition time;
4. clear `collection_cutoff_at_utc`;
5. clear `source_collection_epoch`;
6. clear `analysis_stage`;
7. trigger the orchestration path through the phase-file push and retain a low-frequency scheduled safety trigger.

Only collection campaign kinds from the active epoch may be selected.

### COLLECT -> ANALYZE

When the user says to stop collection and analyze:

1. update the phase file to `ANALYZE`;
2. increment `epoch`;
3. store the just-finished collection epoch in `source_collection_epoch`;
4. set `collection_cutoff_at_utc` to the transition time;
5. set `analysis_stage` to `DRAIN`.

No new collection campaign may be created after the cutoff.

A collection worker that was already claimed before the transition may finish and publish its current bounded unit. New claims for collection work from the prior collection epoch are refused after the phase transition.

Pending or continuation-required collection campaigns from old epochs remain inert and are not resumed in a later session.

### ANALYZE -> IDLE

After the analysis pipeline reaches its terminal stage, the control plane may set `analysis_stage` to `DONE`. The phase remains `ANALYZE` until the user explicitly requests `IDLE` or a new `COLLECT` session. This keeps the completed analysis state inspectable.

## Collection phase

The collection phase reuses the existing native collectors and Dataset V2 publishing path rather than creating a competing data stack.

Collection work includes, where supported by the current repository:

- Hyperliquid market data and BBO/microstructure;
- native Binance, Bybit, OKX, Gate, and Bitget feeds;
- Copy-Vault public discovery, frozen selection, bounded user-specific observation, and REST reconciliation;
- official archive collection where useful;
- event-intelligence collection when it is an input to existing research.

Collection units remain bounded below the GitHub-hosted job maximum. A session is continuous at the orchestration level: after one bounded unit publishes, another current-epoch unit can be created or selected while the phase remains `COLLECT`.

Every published bundle keeps the existing Dataset V2 integrity contract: immutable release assets, run manifest, source/code SHA, hashes, timestamps, quality state, and fail-closed publication.

## Collector completeness and usability contract

The `COLLECT` phase optimizes for the maximum **usable replay-grade evidence**, not raw byte volume. A source or channel that cannot meet minimum provenance and integrity requirements is still allowed to be archived as raw evidence, but it may not silently become SAFE replay input.

### Universe coverage

At the start of each collection epoch, build and persist a fresh public perpetual-market universe from all currently supported native venues.

Requirements:

- do not use one permanently hard-coded coin shortlist as the total collection universe;
- discover the full public perpetual universe that the existing venue adapters can represent;
- compute cross-venue intersections and venue-specific markets;
- shard the universe into bounded GitHub-hosted collection batches;
- prioritize liquid/cross-venue candidates for highest-frequency microstructure capture while continuing to rotate through the broader eligible universe;
- preserve the exact universe snapshot, venue symbols, selection timestamp, and code SHA used for each epoch;
- if a venue discovery call fails, record the failure explicitly instead of silently shrinking the universe.

CCXT or other scouts remain discovery-only and may not replace working native collectors.

### Required market evidence

Collect the richest public evidence that each supported venue exposes and the current project can validate.

The target evidence families are:

- BBO / top of book;
- L2 order book at the deepest practical public level for the native adapter;
- public trades and aggregate trades where available;
- mark, index, last and oracle/reference prices where exposed;
- funding rate and realized funding settlements where public endpoints permit;
- open interest;
- 24h volume / liquidity context where exposed;
- public liquidations where exposed;
- replay-critical instrument metadata such as tick size, size precision, leverage/margin rules, contract multiplier and listing/delisting state;
- authoritative archive/backfill sources when they improve continuity or exact-count verification.

Current native capabilities must be reused. In particular, the design must preserve existing Hyperliquid/Binance clock and depth collectors, Bybit public L2/trade/ticker/liquidation feeds, OKX book/trade/ticker/funding/open-interest/mark/index feeds, and existing Gate/Bitget native adapters. Missing useful public channels in an existing adapter should be added rather than creating a competing collector stack.

A channel is not considered covered merely because a connection exists. The run manifest must report per venue, instrument and channel whether observations were actually received.

### Replay-grade timestamps and provenance

Every admitted market event must preserve, when the source provides them:

- exchange event timestamp;
- local receive wall-clock timestamp;
- local monotonic receive timestamp;
- clock-offset evidence and probe RTT;
- connection identifier;
- sequence/update identifier;
- reconnect/reset counters;
- source URL/API family;
- transport type;
- read-only/authentication state;
- collector code SHA.

If an exchange does not provide a timestamp or sequence, the collector records that fact explicitly. It must never fabricate an exchange timestamp or sequence.

Clock probes must be refreshed during long collection windows, not only once at startup.

### Book integrity and gap detection

For stateful order books:

- require a valid snapshot before deltas are considered usable;
- validate sequence/update continuity whenever the venue exposes sequence information;
- reset and reacquire state after reconnect or desynchronization;
- reject crossed/invalid BBO state;
- record reconnects, resets, stale intervals and missing updates;
- preserve enough raw payload to reconstruct and audit the book transformation.

Queue overflow is never ignored. Existing writer-queue drops must increase the corresponding gap/integrity counters.

Any unexplained gap that can affect execution simulation must remain visible to replay and quality gates.

### Trades and reconciliation

Where an authoritative public REST/archive reference exists, reconcile captured trades against it.

Existing Hyperliquid, Binance, Bybit and OKX reconciliation paths remain mandatory. Equivalent official reconciliation should be added for Gate/Bitget when their public APIs allow a deterministic comparison.

If exact reconciliation is unavailable for a venue/channel, mark the evidence `UNVERIFIED` or the appropriate lower quality state. Do not promote it to exact-count SAFE evidence merely because the WebSocket stayed connected.

Deduplicate events using stable venue identifiers where possible. Reconnect overlap must not create artificial trade volume.

### Runner-boundary continuity

A GitHub collection session consists of multiple bounded jobs, so job boundaries are part of the data-quality model.

Each boundary must:

- checkpoint the last durable timestamps/sequences per stream;
- start the successor from a persisted epoch/universe definition;
- use bounded overlap or authoritative backfill when the venue permits it;
- deduplicate overlap deterministically;
- record any uncovered interval as a gap;
- never synthesize missing BBO/L2 events.

The collection controller should start the next bounded window early enough to minimize avoidable dead time, while respecting API and GitHub concurrency limits.

### Copy-Vault completeness

Copy-Vault keeps two distinct evidence layers:

1. **broad public universe evidence** for discovery/scoring across all qualifying open public vaults;
2. **bounded live evidence** for user-specific WebSocket observation under Hyperliquid per-IP limits.

The broad universe must not be arbitrarily capped before scoring. Live lanes must rotate deterministically across the frozen universe or its causally scored priority set so that runner limits do not permanently starve most candidates.

For every observed vault preserve:

- frozen selection time and selection reason;
- public position snapshots before/after the live window;
- forward user fills;
- REST `userFillsByTime` reconciliation for the exact forward interval;
- execution-relevant L2 for leader-traded instruments when captured;
- reconnect/drop/gap evidence.

Pre-selection history may be used only where the existing research protocol explicitly permits TRAIN/history. It may never be mislabeled as forward evidence.

### Quality gates

Every collection epoch produces a machine-readable coverage and integrity report before analysis may advance from `QUALITY`.

At minimum report:

- expected vs observed venues;
- expected vs observed instruments;
- expected vs observed channels;
- event counts and byte counts;
- first/last exchange and receive timestamps;
- clock-offset and RTT distributions;
- reconnect/reset counts;
- queue drops;
- detected sequence/time gaps;
- reconciliation status and mismatch counts;
- stale-data intervals;
- instrument-metadata availability;
- SAFE/PARTIAL/REJECT/UNMEASURABLE counts and reasons.

A bundle may be marked SAFE only when the evidence needed by its intended replay/backtest is present and internally consistent.

The quality gate is fail-closed: missing fees, missing execution-critical book data, unresolved timestamp ambiguity, unbounded queue loss, failed reconciliation, or materially incomplete coverage must prevent that evidence from being used as if it were complete.

### Data-volume policy

The collector should maximize coverage **within public API limits, GitHub-hosted runtime limits, and durable publication capacity**.

When resources are constrained, prioritize in this order:

1. data required to simulate executable price and fills;
2. data required to prove timing/causality;
3. data required for funding/carrying-cost and position context;
4. broader universe discovery and lower-frequency context.

Do not sacrifice BBO/L2/trade integrity merely to increase the number of symbols.

Raw evidence should be compressed and rotated in bounded shards, with immutable hashes and manifests, so increased coverage does not make replay provenance ambiguous.


## Copy-Vault behavior

The current complete public vault universe remains discoverable and auditable, but the phase orchestrator must not attempt to make thousands of user-specific WebSocket subscriptions simultaneously.

The current Hyperliquid per-IP user-specific subscription guard remains authoritative. Copy-Vault work therefore stays sharded into bounded lanes and is serialized where required by the shared GitHub-hosted egress IP behavior.

The collection epoch is attached to each frozen selection and campaign so stale lanes from a previous session cannot be mistaken for current forward evidence.

REST reconciliation and frozen-selection rules remain causal. No pre-selection future information may be admitted as forward proof.

## Analysis phase

The analysis phase is an ordered state machine:

`DRAIN -> QUALITY -> REPLAY -> BACKTEST -> PNL_PROOF -> SCOREBOARD -> DONE`

### DRAIN

- do not create or claim new collection work;
- wait only for already-claimed collection units from the source collection epoch to finish or for their leases to expire;
- do not wait for unclaimed old collection backlog.

### QUALITY

- reconcile/index all published manifests from the source collection epoch;
- validate hashes, timestamps, continuity/gaps, source/code SHA, exact-count checks where applicable, and Dataset V2 quality policy;
- label unusable data `PARTIAL`/`REJECT` rather than silently using it;
- freeze the set of SAFE evidence eligible for the analysis run.

### REPLAY

Run replay only on the frozen SAFE evidence set for the source collection epoch and its permitted historical context.

Replay output must preserve gap information; it may not invent continuity across missing BBO/L2 windows.

### BACKTEST

Run the three research families independently:

- Copy-Vault;
- Lead-Lag;
- Cross-Venue Dislocation.

Keep existing TRAIN/validation/OOS/forward causality rules and all execution-cost assumptions.

### PNL_PROOF

Evaluate module-level net PnL after explicit fees, spread, slippage, latency, capacity, and fill assumptions.

The target remains a separately proven net result of at least 4 USD per module. PnL may not be combined across modules to rescue a failing module.

### SCOREBOARD

Publish the current economic and quality scoreboard, including at minimum:

- net PnL;
- ROI;
- profit factor;
- drawdown;
- expected shortfall where available;
- hit rate;
- capacity;
- fill quality;
- latency;
- OOS/forward status;
- data-quality/gap status.

If required costs or evidence are missing, report `UNMEASURABLE` instead of fabricating a result.

## Campaign identity and epoch isolation

Every newly created resumable campaign gets phase metadata sufficient to identify:

- creation phase;
- phase epoch;
- source collection epoch for analysis campaigns;
- collection cutoff for analysis campaigns.

The controller must filter due work by the current phase and matching epoch/source epoch before building matrices.

Workers perform a second fail-closed phase check before claiming work. This prevents a queued workflow from starting stale work after a phase change.

Existing historical campaign manifests are not deleted.

## Workflow changes

Dataset V2 is the orchestration home.

Expected changes are concentrated in:

- `.github/workflows/create-resumable-campaigns.yml`
- `.github/workflows/resumable-campaign-controller.yml`
- `.github/workflows/resumable-campaign-worker.yml`
- phase-control helper code/tests under `tools/` and `tests/`
- `control/alina-phase.json`

The main Alina repository should only receive the smallest required campaign-model/CLI changes and tests needed for epoch metadata, phase filtering, and analysis staging.

Legacy manual diagnostic workflows may remain available, but they must not bypass the phase guard for normal operation.

## Trigger model

Use two triggers:

1. push on `control/alina-phase.json` for fast reaction to a user command;
2. a low-frequency scheduled controller trigger as recovery if a dispatch or runner is delayed.

The schedule is a watchdog, not an independent source of intent. The phase file is always authoritative.

The implementation must not rely on a permanently running GitHub job.

## Concurrency and resource rules

- Collection and heavy analysis are mutually exclusive by phase.
- Collection concurrency remains bounded by venue/API limits and current serialization requirements.
- Analysis stages advance only when the prior stage has durable terminal evidence.
- A failed stage does not silently advance.
- GitHub-hosted runners only.
- No self-hosted labels.
- No workflow may wake or depend on the user's PC.
- Real execution environment flags remain disabled in every worker.

## Failure and recovery

The orchestrator is resumable and idempotent.

If a runner dies:

- already-published immutable data remains valid;
- an expired lease may be retried only if its phase/epoch is still current;
- stale-epoch work is ignored;
- the controller can resume the current analysis stage from durable manifests.

If GitHub scheduling is delayed, the next watchdog run continues from the phase file and durable stage state without creating duplicate proof evidence.

## User interaction contract

The intended user commands are deliberately simple:

- "Lance la collecte" -> switch to `COLLECT`.
- "Arrête la collecte et analyse" -> switch to `ANALYZE`, drain current units, then run the ordered analysis pipeline.
- "Mets Alina au repos" -> switch to `IDLE`.

ChatGPT may perform the GitHub phase-file edit when the connected GitHub permissions allow it.

No user command should require access to the local PC.

## Tests and acceptance criteria

Implementation is accepted only when tests prove all of the following:

1. invalid or missing phase state fails closed;
2. `IDLE` selects no heavy work;
3. `COLLECT` selects collection kinds only;
4. `ANALYZE` selects no new collection work;
5. a worker queued before a phase transition refuses a stale new claim;
6. an already-claimed collection unit may finish during `DRAIN`;
7. unclaimed old collection backlog does not block `DRAIN`;
8. campaigns from an old epoch never reactivate in a later `COLLECT` session;
9. analysis stages advance in the required order;
10. replay/backtest/PnL use the frozen SAFE evidence set bounded by the source collection epoch/cutoff;
11. failure in a stage prevents later stages from starting;
12. all execution paths remain paper/read-only;
13. no self-hosted runner is referenced by the new orchestration path;
14. Dataset V2 publication remains durable and hash-verified;
15. existing relevant campaign and collector tests continue to pass.

## Non-goals

This change does not:

- create an Oracle/VPS collector;
- run anything on the user's PC;
- enable real trading;
- guarantee a 4 USD profit;
- remove historical campaign evidence;
- replace existing native venue collectors without a demonstrated need.

Its purpose is to make the existing GitHub architecture operationally simple: collect when instructed, stop cleanly when instructed, then spend compute on evidence generation instead of competing workloads.
