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

## Collector V4 Extreme Replay-Grade

The `COLLECT` phase is not a generic data downloader. It is a capture, recovery, certification, and provenance pipeline whose output must be good enough to reconstruct market state without silently inventing missing information.

The primary invariant is:

> maximize replay-grade evidence, detect every detectable loss, repair every loss that an authoritative public source can repair, and quarantine every interval whose integrity cannot be proven.

The architecture does **not** claim that GitHub-hosted runners can guarantee physical zero-loss networking. GitHub runners are ephemeral and bounded. Instead, the system must guarantee **zero silent gaps**: an unrecoverable gap may exist, but it must be explicitly delimited and forbidden to replay engines that require continuity.

### Module-complete collection contracts

Collector quality is evaluated against the needs of **all three active strategy families**, not against a generic market-data checklist.

The existing minimal dependency declaration (`userFills/allMids/BBO/L2`) is not sufficient for economic proof. Collection V4 therefore defines a richer evidence contract for each family.

#### Copy-Vault collection contract

Copy-Vault must preserve enough evidence to reconstruct the leader decision and a realistic follower execution without confusing deposits, funding, NAV changes, or stale state with trading edge.

Required evidence includes:

- complete qualifying public vault universe and freeze timestamp;
- vault identity/leader metadata and `vaultDetails` snapshots for priority candidates;
- account/NAV/portfolio context used for relative sizing;
- cheap broad `clearinghouseState` sweeps across the frozen universe;
- open-position snapshots with account value, margin, notional, leverage and liquidation-relevant fields;
- forward `userFills` for the bounded live-priority set;
- exact `userFillsByTime` reconciliation for intervals where activity is detected;
- user funding evidence for live-priority leaders when relevant;
- non-funding ledger/deposit/withdrawal evidence when required to distinguish capital flows from PnL;
- pre/post position snapshots and explicit leader exit/reduce detection;
- allMids/BBO and execution-quality L2 for every coin actually traded by a tracked leader;
- mark/index/oracle/funding context during copied holding intervals;
- follower-side entry/exit capacity, spread, slippage and latency evidence;
- post-fill markout checkpoints (100/250/500 ms, 1 s, 5 s or the current execution model horizons);
- immutable selection reason, score inputs and causal timestamps.

The broad vault universe must **not** be implemented as thousands of permanent user-specific WebSocket subscriptions.

Instead, use a two-speed design:

1. a rate-budgeted broad REST state sweep over the complete universe;
2. detect position/account-state changes between snapshots;
3. enqueue targeted `userFillsByTime` reconciliation only for changed/active vaults;
4. reserve scarce user-specific WebSocket slots for the highest-priority causally selected leaders;
5. rotate those priority slots based only on information already known at the rotation time.

This converts Hyperliquid's user-specific WebSocket limit from a universe cap into a low-latency priority layer.

#### Lead-Lag collection contract

Lead-Lag needs evidence capable of distinguishing a genuine market lead from exchange-clock error, network-path asymmetry, stale quotes, or a single runner's routing artifact.

Required evidence includes:

- real-time BBO from every supported venue;
- public trades with aggressor side/event identity when available;
- high-frequency L2 for Tier-A candidates;
- exchange matching-engine/event timestamps;
- local receive wall-clock and monotonic timestamps;
- server clock probes with offset, RTT and uncertainty estimates;
- mark/index/reference price, funding, OI, liquidations and volume context where public;
- instrument/listing/trading-state changes;
- shock-triggered causal L2 checkpoints;
- pre/post-shock microstructure windows;
- quote age and source freshness;
- same-host cross-venue receive ordering;
- independent shadow-runner confirmation for the most important lead/lag candidates when capacity permits.

For latency-sensitive comparisons, a measured lag is not admissible merely because one exchange timestamp is numerically earlier. The observed lag must exceed the recorded timing uncertainty or be corroborated by same-runner receive ordering.

#### Cross-Venue Dislocation collection contract

Cross-Venue must capture all evidence required for a simultaneous two-leg executable decision rather than a midpoint difference.

Required evidence includes:

- synchronized BBO across all supported venue intersections;
- L2 depth on both candidate legs;
- complete depth curves sufficient to calculate VWAP at multiple notionals;
- quote age/freshness on each leg;
- same-runner receive ordering for compared venues;
- trades and recent volatility/order-flow context;
- mark/index/reference price;
- funding and funding schedule when holding to convergence can cross a funding interval;
- instrument tick/lot/min-notional/contract-multiplier/listing rules;
- venue/trading/system status;
- explicit versioned maker/taker cost assumptions and provenance;
- entry and exit capacity for both legs;
- latency/markout evidence after detection;
- convergence/timeout exit context;
- dynamic candidate pairs across Hyperliquid, Binance, Bybit, OKX, Gate and Bitget rather than a permanently hard-coded HL/Binance-only data universe.

The collector must generate direct depth/VWAP evidence for the notionals actually tested by the economic engine. A top-level quantity or midpoint cannot stand in for full executable capacity.

### Same-runner cross-venue clock domain

For Lead-Lag and Cross-Venue, primary market shards are organized **by coin group across venues**, not as isolated one-venue jobs whenever runner capacity permits.

A single GitHub-hosted VM should connect to Hyperliquid, Binance, Bybit, OKX, Gate and Bitget for the same Tier-A coin group. This provides a shared local monotonic clock for receive ordering across venues and removes cross-VM wall-clock skew from the primary comparison.

Rules:

- every raw frame is timestamped immediately on receipt before expensive parsing;
- all per-venue processes on the same runner use the host monotonic clock;
- exchange timestamps remain separately preserved;
- the collector records the venue-specific transport/clock uncertainty;
- shadow runners may repeat the same coin group on an independent network path;
- a lead/lag effect that appears only on one runner/network path is flagged for investigation rather than treated as proven market causality.

### Autonomous COLLECT relay

Once the phase is `COLLECT`, collection continues automatically without further user commands.

The intended behavior is:

1. a collection generation starts;
2. it continuously seals/publishes durable checkpoints;
3. well before its GitHub-hosted job deadline, it dispatches its successor via explicit same-repository `workflow_dispatch`;
4. the successor starts while the predecessor is still collecting;
5. the two generations overlap and produce a handoff receipt;
6. the predecessor seals and exits;
7. the successor repeats the process indefinitely while the same collection epoch remains active.

The repository `GITHUB_TOKEN` may be used for same-repository `workflow_dispatch`, because explicit `workflow_dispatch`/ `repository_dispatch` events are permitted to create workflow runs.

The relay must never depend on a push event created by `GITHUB_TOKEN` to trigger its successor.

A scheduled controller every few minutes is a **watchdog only**. It checks whether every required active collection shard has a current or queued generation and dispatches a missing successor if the handoff failed.

Each dispatch carries at least:

- phase epoch;
- generation number;
- shard/coin-group identity;
- universe digest;
- predecessor run ID;
- requested handoff time.

Every successor independently reloads the current phase before opening market subscriptions. If the phase is no longer `COLLECT`, it exits without starting new capture.

Active collectors also re-check phase at checkpoint boundaries. A transition to `ANALYZE` disables successor dispatch immediately and asks current collectors to seal their current segment and stop cleanly rather than running to the full job deadline.

Cron/schedule timing is never relied on for continuity.

### Handoff timing and overlap target

Because standard GitHub-hosted jobs have a finite execution ceiling, V4 targets a substantially earlier handoff than the hard deadline.

The exact timings are configurable and measured, but the default design target is:

- bounded collection generation substantially below six hours;
- successor dispatch with tens of minutes of safety margin;
- minimum healthy overlap long enough to prove all required subscriptions are receiving data;
- predecessor does not voluntarily exit until successor readiness is observed or a bounded handoff timeout expires.

If successor startup is delayed by GitHub, the predecessor continues collecting until its own safe shutdown margin. Any real uncovered interval remains explicit and is handed to the repair pipeline.

### Tier-A dual-resolution market capture

For the most important markets, one depth stream is not always optimal. V4 may collect a fast shallow/medium book and a slower deep/full book simultaneously when the venue supports it.

Examples of intended use:

- Bybit: very fast BBO/L50 for timing plus full-depth/large snapshot path for capacity;
- Bitget: SBE real-time BBO + 50-level full snapshots at high frequency + SBE trades;
- Gate: real-time book ticker plus fast bounded depth and deeper lower-frequency depth;
- Binance: real-time BBO plus diff-depth and raw/aggregate trades;
- OKX: BBO plus incremental deep book with current `seqId/prevSeqId` validation;
- Hyperliquid: BBO plus self-contained L2 snapshots for active/Tier-A coins.

The faster stream proves decision-time executable top-of-book timing; the deeper stream proves capacity/slippage.

### Burst capture around economically interesting events

A continuously collected low/medium-cost layer may promote a market into temporary burst mode when a causal event is observed, for example:

- a Copy-Vault leader fill or position change;
- a cross-venue dislocation crossing a predeclared collection threshold;
- a Lead-Lag shock;
- a liquidation burst;
- abnormal spread/volume/OI change.

Burst mode can temporarily increase:

- depth;
- snapshot/checkpoint frequency;
- contextual feeds;
- post-event markout capture;
- shadow coverage.

Burst mode cannot repair missing **pre-event** evidence and must never be used to introduce lookahead. It enriches current/future evidence only.

### Official historical repair matrix

The repair engine keeps a per-venue capability matrix and uses official free archives before rejecting an interval when those archives can deterministically reconstruct it.

Current design assumptions to verify continuously against official documentation:

- OKX: official high-resolution historical L2 downloads are available and can provide a strong repair/verification layer;
- Gate: official futures market-depth/order-book archives and snapshots are downloadable;
- Bitget: official futures depth and transaction-history downloads are available;
- Bybit: official contract order-book historical downloads are available;
- Binance USD-M: public trades/aggTrades and coarse depth context are useful for repair, but current free public data must not be assumed to reconstruct every missing high-frequency L2 transition;
- Hyperliquid: live reconnect snapshots restore current state, but the official historical L2 archive is requester-pays and therefore is not a zero-cost continuity dependency.

The zero-cost architecture must therefore invest the strongest live redundancy in evidence families/venues whose exact historical L2 transitions cannot be repaired for free.

A later authoritative archive may upgrade an interval from quarantined to repaired only after deterministic identity/timestamp/sequence checks pass.

### Venue-status evidence

Collection quality reports distinguish collector failure from a documented venue incident whenever a public status signal exists.

Capture or poll, where available:

- exchange/system status and maintenance;
- contract/instrument trading state;
- listing/delisting changes;
- API liveness/server time;
- explicit reset/service-restart messages.

Documented venue downtime does not make missing market data replay-safe, but it explains the gap and prevents misdiagnosing the collector.


### Mandatory closure of current collector gaps

Implementation must explicitly remove the following limitations observed in the current repository/workflows. These are not optional optimizations.

#### Cloud universe and campaign creation

The normal `COLLECT` path must stop creating the fixed market campaign:

`BTC,ETH,SOL,XRP,DOGE,BNB,AVAX,LINK,SUI,ADA,TRX,TON,WIF,ARB,OP,APT`

as if that were the complete collection universe.

Instead:

- run native venue discovery at the start of every collection epoch;
- persist the complete discovered universe and all venue-native symbols;
- retain markets seen on only one venue as Tier-C discovery evidence when useful;
- build every cross-venue intersection, not only HL/Binance pairs;
- shard dynamically from measured throughput;
- preserve majors/high-value active candidates in Tier A while rotating broad coverage;
- fail visibly if one venue discovery fails rather than silently treating the smaller universe as complete.

Any `max_coins` option remains a bounded diagnostic/testing control, not the production definition of the universe.

#### Copy-Vault scheduler redesign

The current pattern of creating hundreds of one-vault-lane campaigns and serializing them is not the normal production design.

The implementation must:

- remove the mismatch where a Copy-Vault campaign requests a long collection duration but the worker silently caps a unit to 300 seconds;
- separate **broad REST observation** from **scarce user-specific WebSocket observation**;
- perform rate-budgeted broad state sweeps over the complete frozen vault universe;
- compare current versus prior `clearinghouseState`/position fingerprints;
- schedule expensive `userFillsByTime` only for changed/active candidates or explicitly sampled audit candidates;
- use the priority WebSocket pool for the best causally selected leaders;
- keep explicit fairness/coverage debt so low-priority vaults are periodically revisited;
- record the last successful observation time per vault and expose vault-staleness distribution;
- maintain leader-exit/reduce evidence for selected leaders;
- never let old lane backlog from a previous epoch consume current collection capacity.

The goal is not to subscribe to all vaults. The goal is to observe the complete universe efficiently and devote low-latency resources where they create the most economic information.

#### Binance hardening

Production Binance USD-M collection must include, according to module/tier need:

- dedicated current public WebSocket endpoints rather than legacy/deprecated URLs;
- real-time BBO/book-ticker;
- diff-depth at the fastest sustainable public cadence for Tier A;
- correct snapshot bridge using `lastUpdateId`, `U`, `u`, and `pu`;
- raw trades/aggTrades with buyer-maker/aggressor information;
- mark/index/premium/funding context;
- open interest;
- liquidation stream;
- contract/instrument metadata and rule changes;
- server-time/clock evidence;
- planned WebSocket rotation before exchange-side lifetime termination;
- official public trade/archive reconciliation.

A Binance snapshot after a gap restores current state but must not certify the missing historical depth interval.

#### Bybit hardening

Tier-A Bybit collection should use **two complementary depth paths** when measured capacity permits:

1. fast orderbook/BBO (for detection and receive-time ordering);
2. full order book initialized from the official full REST snapshot and maintained with full-depth deltas (for capacity/slippage).

Requirements:

- buffer deltas during initialization;
- use `u` as the consecutive update identifier for the full-book protocol;
- do **not** require `seq` to be consecutive, because it is a cross-sequence/version field;
- `u=1`, service restart, tick/lot configuration change, symbol state transition, or detected update loss forces a fresh synchronization;
- preserve `cts` matching-engine time separately from service `ts`;
- capture public trades, ticker/BBO, liquidations, mark/index, funding, OI, funding interval/cap, volume and instrument rules;
- collect the public system-status stream to annotate venue incidents;
- use official historical order-book/trade downloads as a repair/verification source when the exact interval/product is available.

The existing generic integrity helper is not sufficient unless configured with Bybit-specific `u` semantics.

#### OKX hardening

OKX must preserve and validate:

- BBO plus deep incremental books;
- `seqId` / `prevSeqId` continuity using current documented reset semantics;
- explicit snapshots/resets;
- trades;
- funding;
- open interest;
- mark price;
- index price;
- liquidation/context feeds where public and useful;
- instruments stream including tick/lot/min-size/status changes;
- public time and system-status evidence.

Do not use historical JSON-book checksum behavior as the primary current integrity rule.

Official OKX high-resolution historical L2 data is a preferred repair/verification layer when available for the affected instrument/time interval.

#### Gate hardening

The current lightweight Gate collector must be expanded beyond a small depth-only stream.

Production requirements include:

- correct `U`/`u` update-window semantics;
- authoritative base/full snapshot synchronization;
- zero-size deletion semantics;
- real-time BBO/book-ticker where available;
- fast bounded L2 plus deeper capacity evidence for Tier A;
- public trades with IDs/side fields where available;
- ticker/mark/index;
- funding and funding schedule;
- open interest;
- liquidations where public;
- contract metadata/status/precision;
- clock/liveness evidence;
- deterministic reconnect/resync.

Gate's official downloadable futures `orderbooks`, `orderbooks_slice`, trades, mark prices and funding history should be used to repair or verify eligible gaps.

A simple test such as `u > previous_u + 1` is not an adequate substitute for the venue's documented update-window relationship.

#### Bitget hardening

The current JSON adapter is a fallback/coverage path, not the desired Tier-A implementation.

Tier-A Bitget should consume the official SBE public feeds where GitHub runner capacity allows:

- BestBidAsk;
- Depth50 full snapshots at the documented high-frequency cadence;
- public trades.

Requirements:

- preserve every original binary frame before decoding;
- validate SBE schema/template/version;
- preserve matching-engine `ts`, service-push `sts`, local receive wall time and local monotonic time;
- use `seq` to detect loss/out-of-order messages;
- handle sequence reset/version/precision changes explicitly;
- maintain full-snapshot replacement semantics for Depth50;
- collect JSON/REST context for funding, OI, mark/index, instrument metadata/status and broader Tier-B/C coverage;
- in JSON incremental books, a size of zero removes the price level rather than leaving a zero-sized level resident in local state;
- use official Bitget depth/transaction history downloads for repair/verification where applicable.

#### Hyperliquid market-data hardening

Hyperliquid collection must keep separate evidence families for:

- BBO;
- self-contained L2 snapshots;
- trades;
- all mids;
- asset contexts/oracle/mark/funding/OI-equivalent context exposed by the public API;
- metadata/instrument state;
- liquidation/event evidence relevant to active research;
- Copy-Vault user state/fills/funding.

Because a new Hyperliquid L2 snapshot restores current state but not every missed historical transition, live Tier-A redundancy and short durable checkpoint cadence are mandatory where free exact historical repair is unavailable.

Requester-pays historical S3 data may be supported as an optional external evidence source but can never be required for the zero-cost normal path.

### Module data-readiness authority

The code-level strategy dependency authority must be upgraded from source-name presence to **evidence-family readiness**.

For each active strategy family, readiness must identify the actual data required for:

- signal observation;
- causal replay;
- executable entry;
- executable exit;
- costs;
- capacity;
- latency/timing;
- funding/holding context;
- markout/adverse selection;
- economic certification.

A module cannot become economically ready merely because strings such as `bbo-collector` and `carnet-collector` exist in an available-source set.

At minimum:

**Copy-Vault economic readiness** requires causally selected leader evidence, reconciled fills/position state, entry and leader-exit evidence, market BBO/L2 around those events, sizing/NAV context, fees, latency/slippage/capacity, and holding/funding context where applicable.

**Lead-Lag economic readiness** requires synchronized lead and lag feeds, timing uncertainty, BBO/L2, trades/order flow, entry/exit capacity, fees/slippage/latency, and forward markouts.

**Cross-Venue economic readiness** requires simultaneous two-leg BBO/L2, same-clock receive evidence, complete executable depth on all four required sides across entry/exit, venue/instrument rules, fees, latency, funding if relevant, and convergence/timeout exit evidence.

Missing one execution-critical evidence family yields `UNMEASURABLE`, not a default value.

### Executable depth curves and capacity tapes

For Tier-A instruments, the collector derives (without discarding raw L2) a compact capacity tape at predeclared notionals, for example:

`10 / 25 / 50 / 100 / 250 / 500 / 1000 USD`

and larger sizes when supported by liquidity.

For each side and timestamp record:

- executable VWAP;
- worst consumed price;
- filled notional;
- fill ratio;
- spread cost relative to contemporaneous reference/mid;
- incremental depth slippage;
- cumulative depth;
- book age;
- source book sequence/snapshot ID.

Cross-Venue additionally records the minimum simultaneous capacity across both legs for entry and exit.

These derived tapes reduce replay compute and make capacity regressions auditable, but raw L2 remains the source of truth.

### Fee and instrument-rule provenance

Economic evidence requires versioned costs and trading rules, not hard-coded eternal constants.

The collector/control plane must preserve, where publicly obtainable or explicitly configured:

- maker/taker fee schedule and effective source;
- any account-tier assumption used by paper simulation;
- funding interval, funding cap and realized funding;
- tick size;
- quantity/lot step;
- minimum order size/notional;
- contract multiplier;
- leverage/margin constraints relevant to capacity;
- instrument listing, delisting, pre-market and trading-state transitions.

A fee/rule value with no provenance or effective interval may not silently qualify an economic proof.

### Quality-driven adaptive promotion

Tier assignment is not only based on volume or symbol popularity. The planner uses collection health and economic information gain.

Promote a market/stream when it exhibits:

- Copy-Vault leader activity;
- repeated causal Lead-Lag shocks;
- recurring executable cross-venue spread;
- unusual OI/funding/liquidation/order-flow changes;
- insufficient depth certainty for an otherwise promising candidate.

Demote or split a shard when:

- writer queue pressure grows;
- parser/processing lag grows;
- rate-limit headroom becomes unsafe;
- drop/gap rate rises;
- publication throughput cannot keep up.

The collector may reduce Tier-C breadth temporarily to protect Tier-A integrity, but it must preserve a documented coverage debt and later rotate neglected markets back into observation.

### Collection liveness SLOs

The autonomous collection system publishes liveness objectives and actual measurements per shard.

At minimum track:

- time from predecessor dispatch to successor queued;
- time from queued to runner start;
- time from runner start to all required subscriptions live;
- proven overlap duration;
- durable checkpoint age;
- time since last valid event per required stream;
- time since last successful universe refresh;
- time since last successful Copy-Vault broad sweep;
- watchdog recovery count;
- consecutive failed generations.

A shard whose durable checkpoint age or required-stream silence exceeds policy is unhealthy even if the workflow process itself is still running.

The watchdog reacts to **data liveness**, not merely GitHub workflow status.

### Automatic continuation is the default

After the user switches Alina to `COLLECT`, no further "continue", "restart", or "launch the collectors again" instruction is required.

The system remains in autonomous collection across arbitrarily many bounded GitHub-hosted jobs until one of these events occurs:

- the user switches to `ANALYZE`;
- the user switches to `IDLE`;
- a fail-closed safety condition makes continued collection invalid.

Temporary API failures, runner failures, GitHub queue delays, individual venue outages, parser crashes, or publication retries do **not** change user intent. The watchdog and successor relay continue attempting bounded recovery while the phase remains `COLLECT`.

A safety stop records a terminal reason and does not silently resume potentially invalid capture until the condition is demonstrably cleared.


### Raw-first capture: WAL before normalization

Every WebSocket or public REST market-data response used for replay must enter an append-only raw write-ahead log before normalized/derived rows are considered durable.

For every raw frame preserve:

- venue and endpoint/channel;
- exact received payload bytes or lossless textual representation;
- receive wall-clock timestamp;
- local monotonic timestamp;
- connection ID;
- subscription/shard ID;
- collector code SHA;
- phase epoch;
- runner/run ID;
- parsing status and parser schema version.

Binary feeds, including any SBE feed, must preserve the original binary frame.

Normalization is a derived view. A parser or normalizer defect must never destroy the original evidence required to rebuild the dataset later.

Raw WAL segments are immutable after sealing.

### Durable segment checkpoints

A runner must not hold an entire multi-hour collection window only on ephemeral disk.

During a collection unit it periodically seals bounded raw/normalized segments, compresses them, computes hashes, writes a segment manifest, and publishes them durably to Dataset V2 release storage.

Each segment manifest records at least:

- segment ID;
- collection epoch;
- runner/run/attempt ID;
- venue/shard;
- first and last receive timestamps;
- first and last exchange timestamps when available;
- first and last sequence/update IDs when available;
- raw event/frame count;
- normalized event count;
- byte count before/after compression;
- queue-drop count;
- reconnect/reset count;
- parser failures;
- SHA-256 of every asset;
- previous sealed segment hash for that logical stream.

The previous-segment reference forms a per-stream hash chain so missing, reordered, or replaced segments are detectable.

Publication cadence must be short enough that abrupt runner death cannot silently erase a large multi-hour interval. Tier-A streams use more frequent checkpoints than lower-priority context streams.

### GitHub-hosted hot handoff

GitHub-hosted collection jobs remain bounded well below the platform job-duration limit.

Continuity must not rely on cron launching the next job exactly on time. For an active `COLLECT` phase:

1. runner N collects normally;
2. before its collection deadline, it requests/dispatches successor runner N+1;
3. N and N+1 overlap for a bounded handoff interval;
4. N+1 proves that its required subscriptions/snapshots are live;
5. both runners publish immutable handoff evidence;
6. overlap is deterministically deduplicated using venue IDs/sequences and receive provenance;
7. N exits only after sealing its final durable checkpoint, unless failure prevents it.

The scheduled controller remains a recovery watchdog if self-handoff fails or GitHub delays a dispatch.

If no overlap actually occurs, the boundary is recorded as a potential gap and repaired from authoritative sources where possible. It may not be declared continuous merely because timestamps are close.

### Failure-domain redundancy for critical streams

Tier-A execution-critical streams should use an independent shadow capture when venue limits and GitHub concurrency allow it.

The shadow lane:

- uses an independent WebSocket connection and preferably an independent GitHub-hosted job for the highest-value streams;
- preserves independent receive timestamps and connection IDs;
- is compared against the primary stream by sequence/event identity;
- can supply missing raw events when the primary lane demonstrably missed them;
- does not create duplicate replay volume because merge/deduplication is deterministic.

If both primary and shadow miss an interval, the normal repair/quarantine rules apply.

Redundancy must never be used to conceal disagreement: conflicts between primary and shadow are quality incidents that require reconciliation or quarantine.

### Adaptive universe tiers

At the start of every collection epoch, discover and persist the current public perpetual universe from all supported native venues.

The universe is not a permanently hard-coded shortlist.

Every market is assigned causally to one of three capture tiers using only information available at the assignment time.

**Tier A — execution-critical**

Highest-value markets for current Copy-Vault, Lead-Lag, and Cross-Venue evidence. Capture the richest practical microstructure:

- real-time BBO;
- deepest practical public L2;
- trades;
- mark/index/oracle/reference prices;
- funding and realized funding evidence;
- open interest;
- liquidation feed when public;
- replay-critical instrument metadata;
- high-frequency clock evidence;
- shadow capture where feasible.

**Tier B — cross-venue candidate universe**

Capture enough information to discover/promote opportunities without overwhelming the runner:

- BBO;
- trades;
- moderate-depth or snapshot L2 where practical;
- ticker/mark/index;
- funding/OI/context;
- instrument metadata.

**Tier C — broad discovery universe**

Maintain low-cost observation/rotation so new markets cannot remain permanently invisible:

- discovery metadata;
- lower-frequency market context;
- price/BBO or equivalent lightweight evidence where practical;
- liquidity/volume/funding/OI context sufficient to decide promotion.

Tier assignment is versioned in the epoch universe manifest. Promotion/demotion may occur at explicit checkpoints using causal observations; the effective time and reason must be recorded.

If CPU, memory, bandwidth, API rate limits, writer latency, or GitHub concurrency become constrained, the system sheds lower-priority context before sacrificing Tier-A raw BBO/L2/trade integrity.

### Measured capacity, not guessed capacity

Each collector shard must expose live health including:

- inbound messages/second;
- raw bytes/second;
- normalized rows/second;
- writer throughput;
- queue occupancy and high-water mark;
- event-loop or processing lag;
- CPU/memory/disk usage where available;
- publish duration;
- API rate-limit headroom.

The planner must size symbol/channel shards from observed throughput and venue limits rather than assuming a fixed symbol count is always safe.

A shard that experiences queue loss, persistent processing lag, or rate-limit pressure is automatically reduced/split for the next unit.

Queue overflow is a quality incident. Any stream with unaccounted collector-side drops cannot be certified continuous.

### Replay-grade timestamps and clock discipline

Every event preserves all source-provided temporal information and independent local receipt information.

Where available, preserve:

- exchange matching-engine timestamp;
- exchange gateway/event timestamp;
- local wall-clock receive timestamp;
- local monotonic receive timestamp;
- upstream service-push timestamp;
- clock-probe server timestamp;
- clock offset estimate;
- clock-probe RTT;
- age of the latest clock sample.

Clock probes are refreshed periodically throughout the window and around reconnect/handoff boundaries.

Clock samples are themselves immutable evidence.

No collector may fabricate an exchange timestamp for a source that does not provide one.

Lead-Lag and cross-venue replay may only use streams whose timing quality satisfies the analysis policy. A stale/missing/unstable clock estimate must downgrade or exclude the affected interval from latency-sensitive proof.

### Stateful book certification

A local order book is a certified state machine, not merely a parsed message stream.

Common rules:

- acquire a valid authoritative initial snapshot or venue-provided full snapshot;
- buffer deltas while initialization is in progress when required by the venue protocol;
- apply only deltas proven to follow the accepted snapshot;
- verify update/sequence continuity according to the exact venue semantics;
- reject crossed or structurally invalid books;
- mark stale books when update freshness exceeds the venue/channel policy;
- on reconnect, reset state unless the venue protocol proves continuity;
- after any detected loss/desync, immediately invalidate the affected book state;
- resynchronize from a fresh snapshot/full-book message;
- open a new SAFE interval only after synchronization is proven.

A resync repairs the future state. It does **not** magically repair the historical L2 events missed between the last certified update and the new snapshot. That interval remains non-continuous unless an authoritative historical source can reconstruct it exactly.

### Venue-specific depth protocols

Implementation must follow current official venue semantics instead of forcing all exchanges through one generic rule.

**Binance USD-M Futures**

For diff-depth collection, preserve and validate the official update identifiers and snapshot bridge semantics. Local book initialization must buffer depth updates, obtain the REST snapshot, align the snapshot/update IDs, and reject/resync on an update-ID discontinuity. BBO/book-ticker may be captured independently as lightweight execution evidence. Planned WebSocket rotation must occur before exchange-side connection lifetime termination rather than waiting for a forced disconnect.

**Bybit**

For Tier-A markets, prefer the richest public order-book protocol practical on GitHub-hosted runners. Where full-depth snapshot + delta is used, initialize from the official REST full-book snapshot, buffer deltas, match `seq`/`u`, and treat a non-consecutive `u` or service reset as a mandatory resync. Preserve matching-engine `cts` separately from gateway `ts`. Standard public order-book snapshots/deltas remain valid for lower tiers when resource use requires them.

**OKX**

For incremental books, continuity is validated with current `seqId`/`prevSeqId` semantics. The design must not rely on the historical JSON-book checksum as an integrity requirement because that checksum was deprecated for the relevant channels in 2026. Snapshot/full-reset behavior, sequence resets, trades sequence evidence, and instrument changes must be handled explicitly.

**Gate**

Use the current native futures order-book update protocol with `U`/`u` and an authoritative REST base book (or the venue's full-depth reset semantics where used). If the next update does not cover/follow the current base ID according to Gate's protocol, invalidate the local book and reconstruct it. For high-value markets, use the deepest/faster public level that measured GitHub runner capacity can sustain safely.

**Bitget**

Upgrade high-value Bitget collection beyond the current lightweight JSON adapter where practical. Tier-A may use the current public SBE feeds that provide full-depth snapshots/trades with matching-engine timestamps and sequence numbers. Raw binary frames must be preserved before decoding. Sequence reset/restart is an explicit state transition. JSON feeds remain an acceptable fallback/lower-tier path but must carry the same provenance and quality reporting.

**Hyperliquid**

Preserve public BBO, L2, trades, active asset context, funding/context, and instrument metadata required by the strategies. Reconnects are expected and must be handled explicitly. Reacquired snapshots reopen a new certified book interval; exact missed L2 transitions are not invented.

Hyperliquid's official per-IP user-specific WebSocket limits remain binding for Copy-Vault. Public market subscriptions and user-specific subscriptions must be budgeted separately in the collection plan.

### Trades: exactness and repair

Trade evidence is certified independently from book evidence.

Where stable venue trade IDs exist, use them for:

- deterministic deduplication;
- overlap merge;
- missing-range detection when semantics allow;
- REST/archive reconciliation.

Existing Hyperliquid, Binance, Bybit, and OKX reconciliation mechanisms remain mandatory and should be strengthened where needed.

Gate and Bitget receive equivalent official REST/archive reconciliation when the public API provides a deterministic historical comparison.

A disconnect can be repaired for trades if an authoritative public endpoint/archive can return the exact missing interval and event identity. Repaired trades carry provenance that distinguishes live capture from backfill.

If exact recovery cannot be demonstrated, the affected trade interval is not certified exact.

### BBO/L2 versus historical repair

The system must distinguish data families that are historically repairable from those that are not.

- trades/fills/funding and some reference data are often recoverable from official REST/archive APIs;
- current snapshots can restore the **state after a gap**;
- snapshots generally cannot reproduce every missed historical L2 transition.

Therefore, L2 gaps are never papered over with interpolation, candles, or a later snapshot. Replays that require microstructure continuity must exclude the unresolved interval.

A lower-resolution replay may use a different certified evidence family only if the strategy's replay contract explicitly permits it.

### Copy-Vault two-layer collector

Copy-Vault keeps two intentionally different layers.

**Layer 1 — broad universe**

Discover and retain the complete qualifying public vault universe without an arbitrary global pre-score cap. Collect/scaffold public REST evidence sufficient to score/triage the broad universe under Hyperliquid rate limits.

**Layer 2 — live forward evidence**

Use user-specific WebSocket observation only within the official per-IP unique-user ceiling. Live lanes are causal, frozen, and bounded.

For every live vault preserve:

- frozen selection timestamp and reason;
- selection/universe digest;
- pre-window public position snapshot;
- forward `userFills` snapshot/stream evidence;
- exact `userFillsByTime` reconciliation for the forward interval;
- post-window position snapshot;
- L2/BBO evidence for leader-traded instruments where required for execution simulation;
- reconnect, timeout, queue, and reconciliation receipts.

Rotation must avoid permanent starvation of the broad vault universe, but historical data must never leak into forward selection/proof.

The system must not assume that separate GitHub jobs always receive unique public IPs. Each user-specific lane remains compliant with the official per-IP ceiling on its own, and cross-job parallelism is increased only when rate-limit evidence proves it safe.

### Multi-stage event quality

Quality is certified per logical stream and interval, not merely per release bundle.

A stream interval can have independent dimensions such as:

- `RAW_DURABLE`;
- `CLOCK_VALID`;
- `SEQUENCE_CONTINUOUS`;
- `BOOK_STATE_VALID`;
- `TRADES_EXACT`;
- `RECONCILED`;
- `METADATA_VALID`;
- `EXECUTION_REPLAY_SAFE`.

This allows, for example, trades to remain replay-safe while L2 from the same wall-clock interval is quarantined.

The existing high-level states `SAFE`, `PARTIAL`, `REJECT`, and `UNMEASURABLE` remain available as derived summaries, but they must not hide which specific evidence family failed.

### Coverage ledger

Every collection epoch produces a machine-readable ledger at:

`venue × instrument × channel × certified interval`

At minimum record:

- expected/attempted/observed status;
- first/last receive and exchange timestamps;
- raw and normalized counts;
- exact IDs/sequences where available;
- gap intervals and reason;
- reconnect/reset/resync counts;
- overlap/handoff evidence;
- backfill/repair evidence;
- reconciliation counts/mismatches;
- queue drops;
- parser failures;
- stale intervals;
- clock offset/RTT statistics;
- metadata version/effective interval;
- quality dimensions;
- durable asset hashes.

The ledger is the authoritative input to the `QUALITY` stage.

### Replay firewall

Replay never discovers quality problems opportunistically while simulating. It receives a pre-certified evidence map.

Before replay starts, the `QUALITY` stage freezes:

- the exact Dataset V2 asset hashes;
- stream/channel quality states;
- allowed time intervals;
- excluded gap intervals;
- source collection epoch;
- collector and parser versions;
- required execution-cost/context evidence.

A replay adapter requesting execution-critical evidence outside a certified interval must fail closed.

No interpolation, forward fill, candle substitution, or synthetic book event may silently bridge an unresolved BBO/L2 gap.

If a strategy can legitimately operate on lower-resolution evidence, that alternative evidence contract must be explicit and independently validated.

### Collection quality scoreboard

The collection phase must publish a compact scoreboard for every epoch, including at least:

- durable raw coverage duration;
- certified replay-safe duration;
- coverage percentage by venue/channel/tier;
- unresolved gap count and total gap duration;
- repaired gap count and repair source;
- queue-drop count;
- parser-failure count;
- reconnect/resync count;
- handoff-overlap success rate;
- trade reconciliation mismatch rate;
- clock offset p50/p95/p99 and probe RTT p50/p95/p99;
- receive latency p50/p95/p99 where exchange timestamps allow it;
- writer/processing lag p95/p99;
- instruments attempted vs certified;
- SAFE/PARTIAL/REJECT/UNMEASURABLE totals and reasons.

Economic replay/backtest metrics must never obscure poor collection quality.

### Resource policy for GitHub Actions

The collector is designed around ephemeral standard GitHub-hosted runners.

Requirements:

- each worker stays safely below the GitHub-hosted job execution ceiling;
- long sessions are composed from bounded overlapping units;
- no correctness property depends on cron firing at an exact wall-clock instant;
- matrices remain below GitHub workflow limits;
- concurrency is bounded and dynamically planned rather than maximized blindly;
- asset sizes are bounded and rotated before platform/file limits;
- heavy raw assets are stored as immutable release assets, while Git tracks manifests, catalogs, hashes, phase state, and small reports;
- collection and heavy analysis do not compete because phase control remains authoritative.

A GitHub delay/outage may create a real collection gap. Such a gap is detected from the coverage ledger and repaired where possible; otherwise it is quarantined. The system never relabels GitHub scheduling delay as continuous market data.

### Data-volume priority

When resources are constrained, protect data in this order:

1. raw execution-critical BBO/L2/trades for Tier A;
2. timing, sequence, and provenance evidence required to certify those streams;
3. execution context: fees, instrument rules, mark/index, funding, OI, liquidations;
4. Tier-B cross-venue candidate evidence;
5. broad Tier-C discovery/context.

The objective is maximum **usable** information, not maximum compressed bytes.

A larger dataset with unknown holes is inferior to a smaller dataset whose certified intervals and limitations are explicit.

## Copy-Vault behavior

The current complete public vault universe remains discoverable and auditable, but the phase orchestrator must not attempt to make thousands of user-specific WebSocket subscriptions simultaneously.

The current Hyperliquid per-IP user-specific subscription guard remains authoritative. Copy-Vault work stays sharded into bounded lanes and uses broad REST discovery/scoring plus bounded forward WebSocket evidence.

The collection epoch is attached to each frozen selection and campaign so stale lanes from a previous session cannot be mistaken for current forward evidence.

REST reconciliation and frozen-selection rules remain causal. No pre-selection future information may be admitted as forward proof.


## Strategy / PnL Acceleration VNext

The collection architecture is necessary but not sufficient. The three active research families must also be redesigned to maximize **provable after-cost daily net PnL** rather than waiting passively for rare legacy signals.

The first economic milestone is standardized across all three modules:

> **at least +4 USD net per UTC day per module**, measured after fees, spread, slippage, latency, capacity, funding where applicable, and realistic fill assumptions.

This is a research target, not a guarantee. Promotion remains fail-closed. If the evidence does not support the target, the result is negative or `UNMEASURABLE`; thresholds, costs, or validation rules may not be weakened merely to obtain a positive number.

After the +4 USD/day milestone, optimization targets the highest scalable daily net PnL compatible with the approved paper-capital, drawdown, capacity, causality, OOS and forward constraints.

### Speed-to-proof principle

Reducing time-to-proof must come from:

- more independent executable opportunities per day;
- better information extraction from the same raw data;
- better venue/order-type routing;
- better sizing of high-confidence/high-capacity opportunities;
- broader markets and leaders;
- faster causal observation;
- eliminating artificial hard-coded bottlenecks.

It must **not** come from:

- reducing the number of independent days required for validation;
- using future information;
- ignoring fees/slippage/latency;
- counting unfilled maker orders as fills;
- double-counting overlapping signals;
- increasing notional beyond verified capacity;
- relaxing OOS/forward separation.

### Confidence-aware adaptive paper sizing

Fixed tiny notionals are no longer the default production research policy.

The current code contains fixed values such as approximately 15 USD for legacy Cross-Venue, 25 USD for some Lead-Lag timing experiments, and 150 USD for Copy-Vault. These values are useful diagnostics but can make the time required to reach a dollar-denominated objective artificially long.

VNext evaluates a predeclared sizing ladder, bounded by the existing paper-capital contract and executable capacity.

For every candidate, define a conservative expected net edge after all measured costs and a confidence/shrinkage factor derived only from information available at decision time or frozen TRAIN parameters.

Paper notional is bounded by:

- remaining approved paper capital;
- entry and exit executable L2 capacity;
- per-module/per-coin/per-venue concentration limits;
- correlated-signal exposure;
- uncertainty-adjusted expected edge;
- drawdown/risk budget;
- verified fill probability for passive execution.

Raw estimated edge is never used as an unrestricted Kelly bet.

If Kelly-like sizing is explored, it must be fractional/shrunk for parameter uncertainty and capped by the stricter capacity/risk limits. An opportunity with weak or unstable evidence receives less size even if its point estimate is high.

All sizing variants remain paper/read-only.

### Common efficient price and venue residual layer

Lead-Lag and Cross-Venue share a causal multi-venue price-discovery layer.

For each coin and timestamp construct, using only currently observable data:

- a robust multi-venue efficient/reference price;
- venue-specific residual from that reference;
- venue quote age;
- venue reliability/clock quality;
- spread/depth/liquidity state;
- recent signed trade flow;
- L2 imbalance/microprice state.

The reference must not be a naive unweighted mean.

Candidate methods include frozen/train-only weights from:

- liquidity/depth;
- price-discovery/information-share estimates;
- recent causal cross-impact quality;
- robust median/trimmed consensus;
- combinations proven incrementally useful OOS.

A venue whose quote is stale, desynchronized, or outside certified timing quality is excluded/downweighted before residual calculation.

Raw pairwise spread remains available, but Cross-Venue may not assume that every pairwise deviation is an arbitrage. Stablecoin quote basis, funding expectations, contract specification differences, persistent venue premia and market state must be represented when relevant.

### Additional high-information regime layers

The strategy layer may add the following causal context families as separate hypotheses. They are not assumed profitable merely because external research reports structure.

#### Liquidation / forced-flow regime

Liquidation bursts are treated primarily as a market-state and liquidity-risk signal.

Capture and derive, where available:

- forced buy/sell direction;
- liquidation notional/intensity;
- liquidation concentration by coin/venue;
- concurrent OI change;
- impact-price / spread expansion;
- depth withdrawal;
- cross-asset coupling.

Candidate mechanisms are kept separate:

- continuation during forced-flow acceleration;
- exhaustion/reversal after forced-flow climax;
- no-trade during extreme liquidity impairment.

The system must not assume that every liquidation cascade predicts reversal. Promotion requires Alina-specific OOS evidence.

#### Cross-asset spillover graph

Lead-Lag may model causal information flow not only across venues for the same coin, but also across economically related coins.

Examples include:

- BTC -> major alts;
- ETH -> ecosystem/high-beta alts;
- market-wide common factor -> idiosyncratic lagger residual.

Cross-asset hypotheses require:

- frozen lead/lag relationship on TRAIN;
- explicit beta/common-factor neutralization where appropriate;
- separate transaction-cost/capacity proof for the lagging instrument;
- no same-event double counting with same-coin venue signals.

#### Clock-phase and scheduled-microstructure context

Time-of-hour, funding boundaries and recurrent market microstructure phases may be used as context features or regime gates when frozen on TRAIN.

They may alter:

- expected volatility;
- expected spread/depth;
- execution mode;
- threshold scaling;
- maker toxicity expectations.

Clock phase alone is not sufficient to create a trade unless it demonstrates independent held-out economic value.

#### Toxicity and markout layer

All three modules may use signed markout curves as an execution/information-quality diagnostic.

Examples:

- Copy-Vault leader fill markouts;
- maker-order post-fill markouts;
- route-specific Cross-Venue hedge markouts;
- Lead-Lag entry markouts.

Track multiple causal horizons and separate:

- raw markout;
- market-adjusted markout;
- venue-residual markout;
- post-cost markout.

A signal with positive gross prediction but persistently toxic execution may be rejected or routed differently.

### Quote-currency and contract normalization

Cross-Venue and Lead-Lag comparisons must normalize economically different contracts before treating prices as directly comparable.

At minimum account for, where relevant:

- USDT versus USDC/USD quote basis;
- contract multiplier;
- inverse versus linear specification;
- mark/index construction;
- funding schedule;
- persistent venue premium;
- listing/pre-market state.

A raw price difference caused by quote-currency basis or contract specification is not automatically an arbitrage signal.

### Incremental certification instead of all-or-nothing universe gates

A profitable route/coin/leader cohort may be independently certified once its own evidence contract is complete.

The system must not require:

- every predeclared coin to have perfect coverage before Cross-Venue can certify one strong route;
- every venue pair to be available before Lead-Lag can certify one leader-lagger edge;
- the entire Copy-Vault universe to have identical freshness before one independently validated leader cohort can be evaluated.

Global coverage remains a collection objective, but economic certification is granular at the smallest defensible unit:

- Copy-Vault: leader/cohort × coin/regime;
- Lead-Lag: leader venue × lagger venue × coin × regime/horizon;
- Cross-Venue: execution route × coin × order-type policy.

This reduces time-to-proof without lowering per-unit evidence quality.

### Candidate-subset portfolio

Within each module, multiple independently frozen profitable mechanisms may coexist.

Examples:

- Copy-Vault anticipatory leaders plus continuation leaders;
- Lead-Lag continuation plus reversal plus cross-asset spillover;
- Cross-Venue immediate residual reversion plus persistence-confirmed routes.

The module-level PnL is the chronological sum of non-overlapping, capital-feasible admitted trades from its frozen candidate subset.

Overlapping variants triggered by the same event are resolved by the module allocator rather than counted multiple times.

### Analysis wall-clock acceleration

When phase changes to `ANALYZE`, research jobs may fan out across GitHub-hosted runners by independent certified partition:

- module;
- coin;
- leader cohort;
- venue pair;
- route family;
- frozen strategy variant.

Parallel analysis reduces elapsed wall-clock time but cannot change chronological evidence or duplicate observations.

Aggregation occurs only after every partition publishes deterministic hashes and terminal quality status.

### Research-derived feature tapes during COLLECT

The `COLLECT` phase may compute lightweight deterministic derived features as part of ingestion, provided it does **not** evaluate strategy PnL or tune strategy parameters.

Examples:

- OFI;
- microprice;
- L2 shape summaries;
- efficient-price residual;
- liquidation intensity;
- OI/funding deltas;
- leader position deltas;
- capacity/VWAP ladders;
- markout-ready event indices.

These feature tapes are immutable derived data linked to raw hashes.

They reduce later replay cost and analysis startup time without violating the rule that heavy replay/backtest/PnL work waits for `ANALYZE`.


### Copy-Vault V10+: anticipatory-leader engine

Copy-Vault is upgraded from a simple delayed copier into a causal leader-information engine.

#### Observation-latency classes

Copy delay is evidence-dependent.

- priority leaders observed through live user-specific WebSocket use measured observation-to-decision latency;
- broad REST-discovered leaders use their actual slower polling/reconciliation latency;
- legacy fixed 60-second delay remains only as a stress/compatibility scenario, not the universal production assumption.

Every replay records the actual latency class.

#### Leader information score

Leader quality uses more than historical vault PnL.

Causal features may include:

- market-adjusted forward markouts after the leader fill;
- persistence of those markouts across chronological splits;
- whether the wallet tends to lead or follow the multi-venue efficient price;
- post-trade residual movement on Binance/OKX/Bybit/other leaders;
- entry efficiency versus contemporaneous L2;
- consistency across coins and regimes;
- position-change conviction relative to account/NAV;
- realised versus unrealised contribution;
- concentration and drawdown;
- leader-exit quality;
- frequency and independence of opportunities.

A profitable wallet that merely reacts after the dominant venue already moved may be a poor copy candidate.

An anticipatory wallet whose flow repeatedly precedes subsequent market movement may receive a higher priority, subject to held-out persistence.

Wallet scores use shrinkage/minimum-history rules so a tiny lucky sample cannot dominate ranking.

#### Metaorder lifecycle

Copy-Vault must reconstruct and evaluate the full causal lifecycle:

- first observable OPEN;
- ADD/pyramiding;
- REDUCE;
- CLOSE;
- direction flip;
- inactivity/time-stop.

Do not require multiple leader fills before every possible entry by default.

VNext explicitly compares:

- first-fill entry;
- second-confirmation entry;
- continuation/metaorder entry;
- position-delta-triggered entry.

A single-fill entry is admissible only when its decision-time leader-quality and execution evidence meet the frozen policy.

#### Proportional replication

A leader REDUCE is not automatically a full follower CLOSE.

Evaluate causal proportional policies based on:

- leader position delta;
- leader NAV/account value;
- follower current position;
- paper capital and capacity.

Candidate policies include:

- proportional ADD;
- proportional REDUCE;
- full CLOSE only on leader CLOSE;
- protective close when leader-quality or execution edge collapses.

The current full-follower-exit-on-first-REDUCE behavior remains a benchmark rather than the only allowed mechanism.

#### Decay-aware copy gate

For each leader cohort estimate on TRAIN how rapidly informational value decays after the observed leader event.

At decision time, skip the copy when measured observation latency plus expected execution delay is beyond the frozen profitable decay window.

This prevents copying a genuinely good trader after the useful information has already been incorporated by the market.

#### Multi-leader consensus

When multiple independently selected high-quality leaders align on the same coin/direction within a causal window, evaluate a consensus confidence boost.

Conflicting leaders reduce size or produce no trade.

A consensus signal must not count correlated duplicate vaults/related child vaults as independent votes.

#### Dynamic risk budget

Replace blanket one-entry-per-coin/day and one/two-entry-per-vault/day rules with a causal risk budget based on:

- current paper exposure;
- leader independence;
- coin correlation;
- recent opportunity count;
- available L2 capacity;
- expected net edge confidence.

Legacy daily caps remain conservative benchmark variants.

### Lead-Lag V8+: multi-venue cross-impact engine

Lead-Lag is no longer defined as one fixed shock threshold from one leader venue to Hyperliquid.

#### Directed venue graph

For every eligible coin build a causal directed graph over:

- Hyperliquid;
- Binance;
- Bybit;
- OKX;
- Gate;
- Bitget.

Edges represent frozen/train-estimated predictive cross-impact from venue A to venue B under a specific market state.

The graph can change by:

- coin;
- volatility regime;
- liquidity regime;
- time horizon;
- event type.

No venue is permanently assumed to be the leader.

#### Multi-feature microstructure signal

Candidate decision-time features include:

- multi-venue returns;
- order-flow imbalance;
- trade-flow imbalance;
- top-of-book imbalance;
- multi-level L2 shape;
- microprice;
- queue depletion/refill;
- spread changes;
- quote age;
- aggressive trade bursts;
- liquidation bursts;
- funding/OI changes;
- venue residual from the efficient-price layer;
- cross-asset leader movement.

Start with transparent linear/sparse models and feature families. A nonlinear layer is promoted only if it adds robust incremental OOS value above the simpler baseline.

#### State-dependent thresholds and horizons

Fixed `8/12/20 bps` shock thresholds and only `1s/5s` horizons are retained as benchmark grids, not universal rules.

VNext predeclares broader but bounded candidate horizons such as sub-second, 1s, several seconds and longer short-horizon windows when the certified tape supports them.

Thresholds are normalized by current:

- spread;
- volatility;
- L2 depth/liquidity state;
- expected costs;
- timing uncertainty.

The trade gate is expected **net** edge after costs, not raw shock size.

#### Continuation versus reversal

The same shock may imply continuation in one book state and reversal in another.

VNext keeps distinct mechanisms for:

- continuation;
- residual reversion;
- extreme-shock reversal;
- cross-asset continuation;
- no-trade.

A state classifier chooses only among mechanisms frozen on TRAIN and independently tested OOS.

#### Execution-mode router

For an admitted Lead-Lag signal, compare:

- taker entry / taker exit;
- queue-proven maker entry / taker exit;
- marketable-limit variants;
- no trade.

Maker is selected only when queue position, fill probability and adverse-selection markout remain positive after costs.

A nominal maker rebate is never sufficient proof of profitability.

### Cross-Venue V7+: smart dislocation router

Cross-Venue is redesigned around all supported venue intersections rather than a mostly HL/Binance legacy pair.

#### Full route universe

For six venues, enumerate all eligible pairwise venue combinations and both directional long/short legs.

For every route evaluate independently:

- executable entry;
- executable exit;
- depth/capacity;
- quote freshness;
- timing;
- fees;
- funding if the hold may cross settlement;
- instrument/quote-currency normalization;
- venue state.

No route is preferred because it is historical.

#### Smart order routing

Each leg may use the best certified liquidity path rather than a single fixed venue if the strategy definition and paper-capital constraints permit it.

A unified order-book view may split a paper order across compatible venues to reduce implicit cost, while preserving venue-level fill provenance.

Cross-Venue must distinguish:

- signal venue pair;
- actual execution route;
- hedge route;
- exit route.

All legs must remain auditable.

#### Order-type combinations

Evaluate, with realistic fill models:

- taker/taker;
- maker/taker;
- taker/maker;
- maker/maker only when both queue fills are independently defensible.

For passive legs include:

- queue position;
- queue ahead;
- cancellations;
- observed trade consumption;
- fill probability;
- adverse-selection markout;
- expiration/cancel policy.

An unfilled passive leg creates no fictitious PnL.

#### Non-atomic execution penalty

Cross-Venue cannot assume both legs fill simultaneously.

Every candidate route models:

- first-leg fill;
- hedge delay;
- second-leg failure probability;
- temporary directional exposure;
- emergency/marketable hedge cost;
- cancel/replace behavior;
- one-leg adverse move.

Expected route value includes this non-atomic risk penalty.

#### Residual dislocation instead of raw basis only

A cross-venue trade is generated from a deviation relative to the common efficient price/equilibrium, not merely a raw midpoint difference.

Candidate residual mechanisms include:

- one venue stale/lagging relative to consensus;
- temporary liquidity shock;
- order-flow-induced overshoot;
- venue-specific residual mean reversion;
- funding/basis-adjusted deviation.

This avoids treating persistent structural premia as arbitrage.

#### Adaptive confirmation

The current persistence requirement of multiple observations within roughly one/two seconds remains a benchmark.

VNext compares causal confirmation policies based on:

- residual magnitude;
- residual decay rate;
- quote freshness;
- book imbalance;
- multi-venue confirmation;
- expected net after waiting.

A very high-quality short-lived dislocation may justify immediate entry; a noisy marginal dislocation may require persistence.

The waiting cost itself is measured.

#### Dynamic sizing and route splitting

For each route evaluate a capacity ladder and choose conservative size from:

- simultaneous entry capacity;
- expected exit capacity;
- uncertainty-adjusted net edge;
- hedge risk;
- capital availability.

Do not keep a universal 15 USD production notional.

### Cross-module opportunity allocator

The three families remain independently provable, but the paper system also evaluates a portfolio allocator to avoid wasting capital on low-edge opportunities while high-edge opportunities are available.

At every decision point, eligible paper opportunities are ranked by a conservative score such as:

`expected_net_usd_lcb / capital_at_risk / expected_holding_time`

subject to:

- module minimum exposure/fairness for independent proof;
- capital cap;
- correlated coin exposure;
- venue concentration;
- drawdown budget;
- capacity;
- no double counting of the same underlying event.

A Cross-Venue and Lead-Lag signal arising from the same market shock may be economically correlated; the allocator must not pretend they are independent diversification.

Module scoreboards continue to report standalone results separately.

### Hypothesis factory without p-hacking

Increasing strategy breadth creates multiple-testing risk.

Every VNext research batch therefore freezes before held-out evaluation:

- feature families;
- mechanisms;
- parameter grid/ranges;
- sizing policies;
- route families;
- regime definitions;
- trial count/correction method;
- TRAIN/validation/OOS/forward boundaries.

The system may search broadly on TRAIN, but only frozen candidates reach held-out data.

Failed variants remain in the experiment ledger; they are not silently deleted.

Sequential research iterations may use previous held-out results only to define a **new future experiment**, never to re-label the already-seen holdout as fresh.

### Daily-PnL proof contract

For every module publish:

- gross PnL/day;
- fees/day;
- spread/slippage/day;
- latency/adverse-selection cost/day;
- funding/day where applicable;
- net PnL/day;
- number of executable opportunities/day;
- filled trades/day;
- average net USD/trade;
- median net USD/trade;
- profit factor;
- hit rate;
- drawdown;
- expected shortfall;
- capital utilization;
- capacity utilization;
- distinct coins/leaders/routes;
- concentration;
- OOS/forward status.

The canonical +4 USD/day milestone requires positive after-cost daily performance under the frozen proof policy; it cannot be inferred from one exceptional trade or a single profitable day.

The scoreboard separately reports:

- mean daily net;
- median daily net;
- lower-confidence-bound daily net;
- percentage of positive days.

Optimization prioritizes robust scalable daily net rather than raw cumulative PnL.

### Required stress tests before promotion

Any candidate that appears highly profitable is re-run under adverse but plausible paper stresses:

- higher fees;
- extra latency;
- older book;
- worse queue position;
- lower maker fill;
- extra slippage;
- reduced L2 capacity;
- delayed leader observation;
- missing one venue;
- quote-staleness shock.

A candidate whose edge vanishes under tiny perturbations is not treated as "mega PnL" quality.

### Edge Research Program V2 — maximum defensible edge search

Alina must not assume that one legacy mechanism contains enough alpha by itself. The research program deliberately searches for **multiple economically distinct edge families per module**, then combines only those that survive independent causal, execution, and held-out tests.

The goal is not to manufacture a positive backtest. The goal is to maximize the chance of discovering a real, scalable, after-cost edge while preserving a complete audit trail of failed hypotheses.

#### Edge decomposition

For every module, decompose expected daily paper PnL into explicit levers:

`daily_net ~= opportunities_per_day × fill_probability × notional × net_edge_per_dollar`

with:

`net_edge = gross_signal_edge - fees - spread - slippage - market_impact - latency_decay - funding/holding_cost - hedge/legging_risk - adverse_selection`

This decomposition is reported for every candidate.

A module that misses +4 USD/day must therefore identify **which lever is insufficient**:

- too few valid opportunities;
- weak gross edge;
- poor fill probability;
- costs too high;
- latency destroys the signal;
- insufficient capacity;
- over-conservative sizing;
- excessive correlation/double counting;
- instability across regimes.

Research work should target the actual bottleneck rather than blindly loosening thresholds.

#### Alpha-family registry

Every strategy family maintains an append-only hypothesis registry with a unique hypothesis ID, economic mechanism, required evidence, TRAIN search space, expected failure mode, and held-out status.

Hypotheses are grouped into:

1. **informational edge** — one observable event predicts future price movement;
2. **relative-value edge** — a temporary residual from a common/equilibrium price is expected to converge;
3. **behavioral edge** — a subset of agents/wallets repeatedly carries useful information;
4. **liquidity edge** — book state, resilience, queue dynamics or forced flow produces predictable execution/reversion behavior;
5. **execution edge** — route/order type reduces implicit/explicit cost without increasing adverse selection more than the savings;
6. **selection edge** — choosing the right coin/leader/venue/regime creates a better opportunity set;
7. **allocation edge** — better confidence/capacity-aware sizing turns the same validated signal into more net dollars without violating paper-risk limits.

A candidate can combine several edge types, but attribution must remain separable.

### Research methodology ladder

Every new edge family begins with the simplest defensible model and earns complexity only through incremental held-out value.

Preferred progression:

1. deterministic/mechanical rule;
2. normalized threshold or residual;
3. linear/logistic model;
4. sparse/ridge/LASSO model;
5. state-space/VECM/Hawkes model when structurally justified;
6. shallow nonlinear model;
7. deeper ML only if it beats the simpler frozen baseline after costs and multiple-testing correction.

Complexity that only improves in-sample fit is rejected.

Stationary/normalized microstructure features are preferred over raw price levels.

### Event time, asynchronous data and causal clocks

Lead-Lag and Cross-Venue research must not rely only on fixed wall-clock resampling.

The research layer may use:

- event time;
- price-change time;
- volume/trade-count time;
- asynchronous covariance/lead-lag estimators;
- same-runner monotonic receive time;
- exchange event/matching-engine time.

For asynchronous multi-venue data, candidate estimators include Hayashi–Yoshida-style covariance/lead-lag methods or equivalent methods that avoid stale-grid interpolation artifacts.

Any measured lead shorter than timing uncertainty is treated as unresolved.

### Efficient-price model library

Lead-Lag and Cross-Venue may compare several causally frozen estimators of the common efficient price:

- robust median/trimmed mid;
- liquidity/depth-weighted reference;
- VECM/common stochastic trend;
- Hasbrouck-style information-share weighting;
- permanent-transitory decomposition;
- state-space/Kalman common-price model;
- sparse cross-impact model.

The winner is selected only on TRAIN/validation and frozen before OOS.

Persistent structural basis is represented separately from transient residual.

### Copy-Vault edge library

Copy-Vault research must test a broad set of leader-skill hypotheses instead of ranking primarily by historic PnL.

#### 1. Anticipatory-wallet edge

Measure whether a leader's signed fill precedes positive market-adjusted forward markout after the actual observable delay.

Test across multiple horizons and chronological splits.

A wallet that is profitable but systematically **follows** the efficient price is not automatically copyable.

#### 2. Metaorder / order-splitting edge

Persistent child fills from the same leader may indicate a larger latent metaorder.

Test whether:

- first child fill;
- early sequence of same-direction fills;
- position-delta acceleration;
- Hawkes/self-excitation intensity

predicts continued leader flow or forward price movement after costs.

This can create earlier entries than waiting for the full position to become obvious.

#### 3. Leader specialization edge

A leader may be skilled only in:

- specific coins;
- long versus short direction;
- volatility/liquidity regimes;
- holding horizons;
- event types.

Estimate skill hierarchically at wallet × coin × direction × regime, with shrinkage toward broader priors when samples are small.

Do not assume one global leader score is optimal.

#### 4. Bayesian/shrinkage skill edge

Small-sample leaderboard winners are highly vulnerable to winner's curse.

Leader ranking should compare:

- raw markout;
- shrinkage-adjusted markout;
- posterior/probability-of-positive-edge;
- lower-confidence-bound markout;
- persistence across chronological splits.

Selection priority is driven by conservative skill estimates, not raw maximum ROI.

#### 5. Skill-decay / change-point edge

A historically good leader can stop being useful.

Maintain causal skill-decay indicators and change-point/regime-break tests.

A leader whose recent forward markout degrades below the frozen continuation threshold is demoted from scarce live-WS priority even if long-run PnL remains high.

#### 6. Crowding/copyability edge

Publicly popular leaders may become harder to copy because follower flow worsens entry price or shortens residual alpha lifetime.

Measure copyability using:

- leader-fill-to-observable-delay markout decay;
- post-leader spread/depth deterioration;
- short-horizon impact after publicly visible leader activity;
- opportunity capacity relative to likely copied notional;
- popularity/crowding proxies when causally observable.

Leaderboard rank/popularity cannot be used as a positive skill prior by itself.

#### 7. Execution-skill versus signal-skill separation

A leader may earn PnL because of superior execution rather than superior direction.

Separate:

- decision/information markout;
- leader execution improvement versus contemporaneous book;
- follower-reproducible markout after observed delay.

Only the reproducible component counts as Copy-Vault alpha.

#### 8. Multi-leader conditional consensus

Consensus can increase confidence only when leaders are demonstrably independent.

Cluster leaders by behavioral similarity, overlapping fills, shared timing and common position paths.

Highly correlated leaders count as one effective vote for consensus/risk allocation.

#### 9. Exit-skill edge

Measure whether leaders are informative not only at entry but at:

- ADD;
- REDUCE;
- CLOSE;
- direction flip.

Some leaders may have strong entry skill but poor exits or vice versa.

Entry and exit scores may therefore be distinct.

### Lead-Lag edge library

Lead-Lag research must search beyond one-venue price jumps.

#### 1. Multi-level OFI edge

Compute order-flow imbalance across multiple L2 levels.

Compare:

- level-1 OFI;
- multi-level OFI;
- PCA/integrated OFI;
- sparse cross-venue OFI.

Deeper-book order flow is admitted only if it improves held-out net PnL or forecast quality after cost.

#### 2. Microprice / queue-pressure edge

Build causal microprice and queue-depletion features from:

- bid/ask imbalance;
- depth shape;
- queue refill/cancel dynamics;
- spread state.

Use them as state variables and incremental predictors, not standalone guaranteed alpha.

#### 3. Cross-impact edge

Estimate whether order flow on venue/coin A predicts future return on venue/coin B after controlling for:

- common market factor;
- contemporaneous price movement;
- own-market OFI;
- timing uncertainty.

Sparse cross-impact is preferred to dense unrestricted models.

#### 4. Hawkes / event-intensity edge

Model self- and cross-excitation of:

- market orders;
- limit orders;
- cancellations;
- price changes;
- liquidations.

Candidate Hawkes/intensity features may estimate the probability of continued flow versus exhaustion.

They must compete against simpler OFI/return baselines.

#### 5. Price-discovery regime edge

Estimate which venue is currently leading via frozen rolling/segmented measures such as:

- information share;
- lead-lag contrast;
- cross-impact strength;
- receive-time precedence;
- residual correction speed.

A venue can switch from leader to follower by coin/regime.

#### 6. Event-time horizon edge

Replace fixed 1s/5s-only thinking with horizons expressed in:

- milliseconds/seconds;
- average number of price changes;
- trade-count/event-count units.

The effective forecast horizon may scale with current activity/liquidity.

#### 7. Liquidity-state edge

Segment book state into causal regimes based on spread, depth, imbalance, resiliency and volatility.

A feature is allowed to matter in one regime and be ignored in another.

Pooled weakness does not automatically reject a strong regime-specific effect, but each regime claim must survive its own held-out correction.

#### 8. Continuation/reversal edge

For the same observed shock, explicitly estimate the probability of:

- continuation;
- reversal;
- no meaningful move.

Candidate reversal states may include extreme queue depletion, failed continuation, liquidity refill and post-forced-flow exhaustion.

#### 9. Cross-asset leader edge

Test BTC/ETH/common-market flow as predictors for lagging altcoins with explicit factor neutralization.

No cross-asset edge is admitted if it is merely contemporaneous beta exposure.

#### 10. Clock-phase / periodic-flow edge

Funding windows, quarter-hour/hour boundaries and recurring algorithmic activity may alter predictability/execution.

Treat phase as a regime/context feature, not an unconditional trade signal.

### Cross-Venue edge library

Cross-Venue research must search for both **signal edge** and **execution edge**.

#### 1. Common-price residual edge

Trade transient venue residuals relative to an efficient-price model instead of raw midpoint spread alone.

Candidate residual models include robust consensus, VECM, dynamic state-space/Kalman and information-share-weighted reference.

#### 2. Dynamic equilibrium / half-life edge

Estimate residual mean-reversion speed causally.

Entry threshold and maximum hold may adapt to frozen residual half-life/regime.

A residual with a half-life longer than the economic holding/cost window is not an arbitrage candidate.

#### 3. Liquidity-resilience edge

After a sweep/shock, measure how quickly depth replenishes and spread normalizes on each venue.

Test whether temporary dislocations are best exploited:

- immediately;
- after a short wait for one side to refill;
- not at all.

This directly connects optimal execution to order-book resilience rather than treating the visible book as static.

#### 4. Transient-impact edge

Separate temporary from persistent impact.

A venue whose price moved mainly because of a short-lived local liquidity shock may be more likely to revert than a venue incorporating permanent information.

Impact-decay parameters are estimated only from TRAIN and frozen.

#### 5. Unified-book smart routing edge

Construct a unified executable book across compatible venues.

For a required paper notional, compare:

- single-venue execution;
- split execution;
- venue priority by all-in cost;
- marketable-limit caps;
- taker versus queue-proven maker components.

Routing gains are measured relative to the same signal, so signal alpha and execution alpha stay separable.

#### 6. Non-atomic hedge-control edge

Model legging risk explicitly.

Candidate policies include:

- fill more liquid hedge leg first;
- fill alpha leg first only when expected residual decay justifies it;
- simultaneous marketable limits;
- immediate emergency hedge after timeout;
- cancel if counterpart quote deteriorates.

The best policy is route/regime dependent.

#### 7. Queue-value edge

For passive routing estimate expected value:

`P(fill) × post_fill_net_value - P(no_fill) × opportunity_cost - adverse_selection_cost`

Queue position, queue ahead, cancellations, taker consumption and signal half-life enter the estimate.

Maker is chosen only when this expected value exceeds taker/no-trade.

#### 8. Quote-basis edge

Normalize USDT/USDC/USD and contract-specific persistent basis before residual calculation.

Separately test whether **changes** in quote basis themselves contain predictive information, without confusing them with same-asset arbitrage.

#### 9. Venue-reliability edge

Route preference may include empirical:

- stale-quote rate;
- disconnect rate;
- fill/reconciliation reliability;
- book-resync frequency;
- timing quality.

A nominally cheaper venue can be economically worse if execution uncertainty is high.

#### 10. Volatility/liquidation dislocation edge

During stress, cross-venue impact and liquidity may diverge dramatically.

Maintain separate policies for:

- normal conditions;
- forced-flow/cascade;
- recovery/refill.

Stress-regime edges must include larger uncertainty/slippage reserves, not smaller ones.

### Cross-module structural edges

#### Regime switching

Each module may maintain a small set of frozen regime policies rather than one universal policy.

Regime changes can be detected from market-state features or change-point methods, but a new regime model must improve held-out economics rather than only statistical fit.

#### Opportunity-density optimization

Track rejected candidates and classify the reject reason.

If most candidates fail for the same reason, research targets that bottleneck.

Examples:

- fees -> search maker/route improvement;
- latency -> prioritize faster leaders/venues;
- capacity -> increase universe/route splitting;
- no signal -> add information features;
- timing uncertainty -> improve same-runner/event-time measurement.

This turns "why are we not at +4/day?" into a measurable optimization loop.

#### Capital-efficiency edge

Compare opportunities by conservative expected net dollars per:

- dollar of capital;
- second of holding time;
- unit of drawdown budget;
- unit of venue concentration.

A smaller but fast-recycling edge can outperform a larger edge that ties capital for too long.

### Anti-overfitting / false-discovery firewall

Because the edge library is intentionally large, multiple-testing control is mandatory.

Research batches must retain enough information to compute or approximate, where appropriate:

- White-style Reality Check or equivalent benchmark-comparison test;
- Hansen SPA-style superior predictive ability test;
- Deflated/Probabilistic Sharpe metrics;
- Probability of Backtest Overfitting (PBO);
- block/event-cluster bootstrap;
- trial-count-adjusted family thresholds.

Purging/embargo or equivalent chronological separation is required wherever label/holding-period overlap could leak information between folds.

Every trial — including failed ones — remains in the registry so the effective search count is auditable.

No candidate is promoted solely because it is the best of hundreds of trials.

### Holdout-burn policy

Once a holdout has influenced a design decision, it is considered burned for that hypothesis lineage.

Further tuning requires:

- a new future time window;
- or a clearly different pre-registered hypothesis family evaluated prospectively.

This prevents iterative hidden overfitting.

### Edge promotion scoreboard

For each edge hypothesis publish:

- hypothesis ID and mechanism;
- module;
- signal family;
- execution family;
- regime;
- opportunity count/day;
- fill rate;
- gross edge bps;
- explicit cost bps;
- latency/adverse-selection bps;
- net edge bps;
- average/median net USD per trade;
- daily net mean/median/LCB;
- profit factor;
- drawdown/ES;
- capacity;
- edge half-life;
- parameter sensitivity;
- positive-day fraction;
- OOS/forward status;
- trial-count/multiple-testing status;
- stress-test survival.

A candidate with spectacular raw PnL but weak lower-confidence-bound, fragile parameters or poor stress survival is not a top-priority production hypothesis.

### Source curriculum incorporated into V2 research

The research program explicitly incorporates ideas from high-signal teaching/research sources, while treating them as hypothesis generators rather than proof:

- **Princeton ORF 445 — High Frequency Markets: Models and Data Analysis (Robert Almgren):** market making, price formation, empirical microstructure and data-driven trading strategies.
- **University of Oxford — Market Microstructure and Algorithmic Trading:** optimal routing, Almgren–Chriss, predictive signals, transient impact, limit-order execution and market making.
- **Columbia Business School B9330 — Market Microstructure: How Trading Works:** order/quote mechanics, theoretical microstructure and empirical implications.
- **MIT-hosted optimal-trading research/lectures:** dynamic supply/demand, LOB resilience and intertemporal execution.
- **Cartea–Jaimungal–Penalva:** algorithmic/HFT control, alpha signals, order flow, execution and market making.
- **Hasbrouck / O'Hara / Harris:** empirical/theoretical market microstructure, informed trading, price discovery and practitioner market mechanics.
- **Almgren–Chriss / Gatheral:** market impact, optimal execution and no-dynamic-arbitrage constraints.
- **Bacry–Muzy / Hawkes literature:** self/cross-exciting order flow and event-time market-impact dynamics.
- **Thorp / MacLean / Ziemba:** Kelly/fractional-Kelly growth, drawdown and estimation uncertainty.
- **Bailey / López de Prado and related multiple-testing literature:** PBO/Deflated Sharpe and selection-bias control.
- **Jane Street public market-making material:** fair value, bid/ask, size/risk and expected-value intuition; useful for execution reasoning, not treated as a source of proprietary alpha.

External curriculum never overrides Alina's own OOS/forward results.


## Module Optimization Architecture V3 — edge portfolios, challengers, and faster proof

The three active modules are not implemented as single monolithic strategies.

Each module is an **edge portfolio** containing multiple independently testable mechanisms that share certified evidence and execution infrastructure but retain separate attribution, validation, lifecycle, and failure scope.

The objective is to maximize robust after-cost daily paper PnL by increasing:

- true independent opportunity breadth;
- information quality per opportunity;
- execution quality;
- capacity utilization;
- capital recycling;
- speed of rejecting weak hypotheses;
- speed of detecting edge decay.

Optional sophistication defaults to G4 `BLOCK_PROMOTION` or `MEASURE_ONLY`. It must not become G0 merely because it is desirable.

### Shared quantitative services

All three modules should reuse common deterministic services rather than implementing inconsistent private versions.

Shared services include:

1. **certified evidence/feature tape service** — immutable raw-linked OFI, microprice, depth/capacity, residual, liquidation/OI/funding and event indices;
2. **efficient-price service** — robust causal multi-venue reference and venue residuals;
3. **cost/TCA service** — fees, spread, delay, market impact, slippage, funding, hedge/legging and missed-opportunity cost;
4. **execution simulator** — taker, marketable-limit and queue-aware maker fills from certified L2;
5. **regime/change service** — volatility/liquidity state and causal change-point indicators;
6. **edge registry/experiment ledger** — hypothesis lineage, trial count, holdout state and promotion status;
7. **allocation service** — independent-edge correlation, capital/capacity constraints and module-level opportunity selection.

A shared service failure propagates only to strategy paths that actually depend on it.

### Edge lifecycle

Every edge candidate has a durable lifecycle:

`DISCOVERED -> BASELINE -> TRAIN_CANDIDATE -> CHALLENGER -> SHADOW -> OOS_CANDIDATE -> PROMOTED -> DECAYING -> RETIRED`

Rules:

- `DISCOVERED` ideas cannot affect economic proof.
- `BASELINE` defines the simplest economically interpretable comparator.
- `TRAIN_CANDIDATE` may be searched/tuned only inside TRAIN/validation.
- `CHALLENGER` has frozen parameters and competes against the current champion.
- `SHADOW` generates paper decisions without replacing the champion.
- `OOS_CANDIDATE` consumes untouched chronological evidence.
- `PROMOTED` becomes eligible for the module edge portfolio.
- `DECAYING` remains auditable but receives reduced/no new capital while revalidation occurs.
- `RETIRED` remains in the ledger and cannot silently return as a fresh hypothesis.

Promotion and demotion are scoped to the edge. A bad challenger cannot disable the module champion.

### Champion/challenger contract

Each module keeps at least one simple champion/baseline whenever one has previously passed its proof contract.

A challenger can replace or join the champion only when it demonstrates incremental value after:

- costs;
- capacity;
- latency;
- OOS/forward validation;
- multiple-testing adjustment;
- stress tests;
- parameter sensitivity;
- correlation with existing promoted edges.

If a challenger fails, the champion continues unaffected.

If a promoted edge later decays, demotion/rollback is local to that edge and does not invalidate unrelated historical proof.

### Effective breadth, not raw strategy count

The system distinguishes **raw breadth** from **effective independent breadth**.

Ten variants triggered by the same market shock and producing nearly identical PnL are not ten independent edges.

Measure dependence using combinations of:

- signal/event overlap;
- return/PnL correlation;
- leader/coin/venue overlap;
- common market-factor exposure;
- identical underlying shock cluster;
- temporal overlap/holding-period overlap.

Maintain an `effective_breadth` estimate and correlation clusters.

The module optimizer seeks more **independent information opportunities**, not merely more parameter combinations.

Grinold/Kahn-style breadth intuition may guide research, but raw asset/variant count must never be substituted for independent breadth.

### Opportunity funnel and bottleneck attribution

Every module publishes a causal opportunity funnel:

`observed events -> evidence-safe candidates -> signal candidates -> net-edge candidates -> capacity-valid -> fill-valid -> admitted paper trades -> profitable trades`

For every rejection record a normalized reason such as:

- missing/unsafe evidence;
- timing uncertainty;
- weak signal;
- structural basis;
- fees;
- spread;
- slippage;
- market impact;
- latency decay;
- insufficient capacity;
- maker no-fill risk;
- hedge/legging risk;
- exposure/correlation limit;
- regime mismatch;
- stale edge/champion health.

Research prioritization is driven by the dominant bottleneck.

If 80% of candidates die because of fees, adding more signal features is lower priority than execution/route improvement.

### Research-compute scheduler

Large candidate searches use adaptive compute **inside TRAIN/validation only**.

Permitted approaches include Successive Halving/ASHA/Hyperband-style resource allocation:

1. give every predeclared candidate a small TRAIN/validation budget;
2. eliminate clearly weak candidates early;
3. allocate more GitHub compute to survivors;
4. retain every attempted candidate/trial in the experiment ledger;
5. freeze survivors before untouched OOS evaluation.

Early elimination may use cheap fidelity levels such as:

- fewer TRAIN days;
- fewer coins;
- lower-depth derived feature tapes;
- fewer parameter combinations;
- smaller bootstrap budget.

A low-fidelity screen can reject a candidate but cannot prove economic success.

OOS/forward evidence is never used by the resource allocator to tune or resurrect candidates.

### Exploration floor

Adaptive prioritization must not permanently starve discovery.

Maintain a fixed exploration budget for:

- new coins;
- low-observation vaults;
- new venue pairs;
- under-sampled regimes;
- novel hypothesis families.

This prevents the bot from becoming trapped around yesterday's winners.

Research/collection exploration priority is separate from paper capital allocation.

### Forecast ensemble and shrinkage

When several independently validated signals predict the same economic target, compare:

- best single champion;
- equal-weight combination;
- shrinkage-to-equal combination;
- sparse/regularized combination;
- regime-conditioned combination.

Complex combination weights must beat simple equal/shrunk baselines OOS.

Signal weights are shrunk when estimation uncertainty is high.

Highly correlated variants are clustered/orthogonalized or receive reduced marginal weight.

An ensemble cannot multiply PnL by counting the same underlying event several times.

### Selective prediction / no-trade as a first-class action

Every model supports `NO_TRADE`.

Admission should depend on a conservative after-cost edge estimate such as a lower confidence bound or equivalent uncertainty-aware score.

A high raw prediction with high uncertainty may be rejected.

The system optimizes:

- PnL;
- opportunity quality;
- capital efficiency;

not prediction accuracy alone.

### Anytime-valid monitoring

Where dependence assumptions can be handled defensibly, research may use sequential/anytime-valid confidence sequences or e-value-style monitoring for a **frozen** challenger.

This permits frequent health checks without ordinary repeated-peeking inflation.

Requirements:

- the hypothesis/metric is frozen before monitoring;
- event dependence/clustering is handled conservatively;
- optional stopping validity is documented for the chosen method;
- sequential evidence does not replace causal OOS/forward separation;
- module minimum economic/readiness requirements remain in force.

If these assumptions cannot be established, use the ordinary frozen-horizon proof.

### Edge-decay and change-point monitoring

Promoted edges are monitored for causal degradation using simple diagnostics first:

- rolling markout/net-edge confidence;
- opportunity/fill-rate shift;
- cost/latency shift;
- parameter sensitivity;
- regime mix;
- CUSUM/Page-Hinkley-style alarms;
- Bayesian online change-point detection as an optional challenger.

A detected break changes only the affected edge state to `DECAYING`/revalidation.

The collection system remains active and unrelated edges continue.

### Implementation-shortfall attribution

Every filled paper decision receives transaction-cost attribution from a common arrival/decision benchmark.

Decompose at least:

- explicit fees;
- half/full spread paid/captured;
- delay cost between decision and order;
- market impact/depth slippage;
- adverse-selection markout;
- funding/holding cost;
- hedge/legging cost;
- missed-opportunity/no-fill cost for passive policies.

This separates:

- **signal alpha**;
- **execution alpha/cost**;
- **sizing/capacity effect**.

A module cannot claim the signal improved when the result actually came only from changed sizing or routing.

### Marginal-notional optimizer

Fixed notional ladders remain diagnostics, but the optimizer may derive a continuous/piecewise `net_pnl(notional)` curve from certified depth and costs.

Choose paper size where marginal expected net value remains positive, subject to:

- approved paper capital;
- simultaneous entry/exit capacity;
- concentration;
- drawdown;
- hedge risk;
- uncertainty shrinkage.

This allows a very strong liquid opportunity to use more paper capital while stopping before extra size destroys the edge.

The optimizer cannot extrapolate beyond observed certified depth.

### Risk-constrained growth allocation

At the edge-portfolio level, sizing may compare:

- conservative fixed fractions;
- volatility/edge-confidence scaling;
- fractional Kelly;
- drawdown-constrained growth optimization.

Growth-optimal methods are optional G4 hypotheses.

No optimizer may override paper-capital, capacity, concentration or drawdown limits.

Risk-constrained formulations are preferred over raw full-Kelly sizing.

### Effective sample size and event clustering

Economic proof tracks both raw trade count and **effective independent event count**.

Cluster observations caused by the same:

- metaorder;
- liquidation cascade;
- common cross-venue shock;
- repeated child fills;
- overlapping holding interval.

Bootstrap/confidence procedures should operate at an appropriate block/event-cluster level.

A cascade producing 40 fills cannot automatically become 40 independent confirmations.

### Hierarchical/partial-pooling models

When sparse per-entity samples are a bottleneck, optional hierarchical models may share statistical strength while preserving entity-specific behavior.

Candidate hierarchies:

- Copy-Vault: wallet -> coin -> direction -> regime;
- Lead-Lag: venue pair -> coin -> regime -> horizon;
- Cross-Venue: route -> coin -> order policy -> regime.

Partial pooling must be frozen on TRAIN and prove incremental OOS value.

Pooling cannot erase a known entity-specific failure or create synthetic OOS observations.

### Copy-Vault V11 optimization layer

Additional Copy-Vault edge hypotheses include:

#### Originator-versus-follower network

Build a causal wallet event graph.

Measure which wallets consistently move/position **before**:

- other high-quality wallets;
- the multi-venue efficient price;
- subsequent market order flow.

A wallet that merely imitates other public leaders is downweighted.

#### Trade-size surprise / conviction

Normalize leader position/fill change by that wallet's own historical behavior, NAV and instrument liquidity.

Test whether unusually high-conviction changes carry more follower-reproducible markout than routine fills.

#### Metaorder phase classifier

Estimate whether a leader event is:

- initiation;
- continuation;
- terminal/cleanup.

Early metaorder phases may have more residual information; terminal fills may have less.

This classification must be causal and compete against simpler first-fill/confirmation baselines.

#### Copyability frontier

For each leader/cohort estimate net copyable edge as a function of:

- observation latency;
- follower notional;
- book depth;
- spread;
- crowding/impact.

This creates a `max_profitable_delay × max_profitable_size` frontier.

Leaders can be skilled yet uncopyable; those cases are rejected for Copy-Vault.

#### Hybrid follower exit

Compare:

- exact leader exit;
- proportional leader reduce/close;
- protective market-state exit;
- time/decay stop.

A hybrid exit can be promoted only if it improves follower-reproducible OOS PnL without using future leader behavior.

### Lead-Lag V9 optimization layer

Additional Lead-Lag hypotheses include:

#### Microprice lead graph

Build leader/lagger relationships using microprice/residual changes in addition to midpoint/trade returns.

This can detect pressure before a visible mid-price move.

#### Leader-consensus / disagreement state

Measure whether several independent venues agree on direction while one lagger remains behind.

Candidate features:

- weighted leader vote;
- residual dispersion;
- consensus confidence;
- venue disagreement entropy.

High consensus plus one stale/lagging executable quote is a distinct hypothesis from a single-venue shock.

#### Time-to-impact / hazard model

Estimate the conditional distribution of lagger response time after a leader event.

Use it to choose:

- immediate taker;
- maker attempt;
- no-trade;
- maximum holding time.

The horizon becomes an economic decision variable rather than a fixed constant.

#### Signal half-life versus execution latency

Every candidate records expected alpha half-life.

If:

`observation_latency + decision_latency + expected_fill_latency >= alpha_half_life`

the candidate is automatically rejected or routed to a faster execution mode.

### Cross-Venue V8 optimization layer

Additional Cross-Venue hypotheses include:

#### Route auction

For every certified dislocation, all eligible venue/order-type routes compete on the same event.

Each route submits expected:

- entry cost;
- hedge cost;
- exit cost;
- fill probability;
- non-atomic risk;
- capacity;
- residual convergence value.

The paper engine chooses at most one capital-consistent winning route for that opportunity unless explicit split-routing is part of the frozen policy.

#### Marginal route splitting

Use the unified book to allocate notional incrementally to the next venue/price level only while marginal net edge remains positive.

This is superior to treating the full order as one venue/one average price when multiple venues provide economically compatible liquidity.

#### Staleness-versus-information classifier

A venue residual can arise because:

- the quote is stale;
- local liquidity was swept;
- the venue incorporated unique information;
- structural basis changed.

Classify these mechanisms causally using quote age, trade flow, consensus movement and book refill behavior.

Only residual classes with held-out convergence edge are tradable.

#### Resilience-aware entry timing

Estimate spread/depth replenishment after local shocks.

Compare immediate entry versus short causal wait.

Waiting is chosen only when expected improvement in execution exceeds lost residual alpha.

### Three independent resource allocators

Do not conflate three different optimization problems:

1. **collection allocator** — what data deserves high-frequency resources;
2. **research-compute allocator** — what hypotheses deserve more GitHub analysis budget;
3. **paper-capital allocator** — what already-promoted edges deserve simulated capital.

A promising TRAIN hypothesis may receive more research compute without receiving any OOS capital.

A profitable edge may receive paper capital without causing the collector to stop exploring alternatives.

### Fast/slow control loops

Use separate causal cadences:

**Fast loop**
- feed health;
- BBO/L2 state;
- signal/execution admission;
- capacity/latency;
- paper decision.

**Medium loop**
- leader/route priority;
- regime classification;
- edge health;
- exploration allocation.

**Slow loop**
- model/hypothesis promotion;
- hyperparameter search;
- multiple-testing review;
- retirement/rearchitecture.

Slow-loop research must never be able to rewrite fast-loop historical decisions.

### Optimization dashboard

For each module show at least:

- champion and challengers;
- promoted edge sleeves;
- effective breadth;
- edge correlation clusters;
- opportunity funnel;
- top rejection reasons;
- net edge bps by sleeve;
- net USD/day by sleeve;
- capital/time efficiency;
- alpha half-life;
- copyability/capacity frontier where relevant;
- change-point/decay state;
- research compute consumed;
- trials attempted;
- holdout status.

The dashboard should answer:

> what exact edge is making money, what is limiting it, and what research action has the highest expected value next?

### Additional research basis for Optimization V3

The optimization architecture incorporates further high-signal findings:

- **Grinold & Kahn / Fundamental Law of Active Management:** genuine independent breadth can increase opportunity quality, while correlated bets do not provide raw-count breadth.
- **Forecast-combination literature:** simple/equal or shrinkage combinations are difficult baselines to beat because complex estimated weights add error.
- **Stoikov, Micro-Price:** order-book imbalance-adjusted microprice can improve short-horizon fair-price estimation relative to plain midpoint.
- **Gould & Bonart:** queue imbalance has measurable short-horizon predictive content, with strength dependent on market microstructure.
- **Huang, Lehalle & Rosenbaum, Queue-Reactive Model:** current queue state is useful for realistic book simulation, execution probability and transaction-cost analysis.
- **Adams & MacKay, Bayesian Online Changepoint Detection:** causal run-length/change-point inference provides a principled optional detector for edge/regime breaks.
- **Jamieson & Talwalkar / Hyperband:** successive resource allocation can reduce compute spent on poor candidates; Alina restricts it to TRAIN/validation.
- **Anytime-valid confidence-sequence literature (Howard/Ramdas and related work):** frozen sequential hypotheses can sometimes be monitored repeatedly without ordinary optional-stopping inflation when assumptions are satisfied.
- **Implementation-shortfall / optimal-execution literature:** decision alpha and execution loss must be decomposed rather than reported as one opaque PnL number.
- **Risk-Constrained Kelly (Stanford/Boyd collaborators):** growth optimization can explicitly incorporate drawdown constraints rather than relying on unrestricted Kelly leverage.

These sources generate architecture and hypotheses. They do not certify an Alina edge.


## Opportunity Expansion Architecture V4 — broad funnel, strict proof

Acceptance quality and opportunity density are dual requirements.

The system must **not** respond to stricter gates by producing almost no trades. It must instead create a much larger pre-gate opportunity universe, then let scoped data/execution/economic gates reject the weak subset.

Normative principle:

> increase the funnel before the gates; never weaken the gates because the funnel is too small.

### Opportunity accounting

Every module publishes four distinct counts:

1. `raw_candidates` — every mechanically generated candidate event;
2. `unique_events` — candidates deduplicated into one underlying economic event;
3. `independent_opportunities` — unique events adjusted for event/coin/venue/leader correlation;
4. `executable_admitted` — opportunities that survive evidence, execution, capacity and economic gates.

Only `independent_opportunities` can be used to discuss effective breadth.

Execution alternatives for the same underlying event do not create new independent opportunities.

Example:

- one BTC dislocation;
- 4 order-type combinations;
- 6 notional ladders;

still begins as **one economic event**, not 24 independent alphas.

### Opportunity-density scoreboard

For every module report per UTC day:

- raw candidates/day;
- unique events/day;
- independent opportunities/day;
- executable candidates/day;
- admitted paper trades/day;
- opportunity acceptance rate;
- median time between independent opportunities;
- top rejection reasons;
- opportunity count by coin;
- opportunity count by venue/route;
- opportunity count by regime;
- opportunity count by edge family.

This scoreboard is separate from PnL.

A module with excellent acceptance quality but very low independent opportunity density is flagged `OPPORTUNITY_CONSTRAINED`.

### Opportunity-deficit response

When a module is `OPPORTUNITY_CONSTRAINED`, the system must **not** loosen evidence or economic criteria.

It expands breadth in this order:

1. broaden eligible coins/instruments;
2. broaden eligible leaders/cohorts;
3. broaden venue pairs/directions;
4. add causally distinct event families;
5. add validated horizons/regimes;
6. add cross-asset relationships;
7. add new execution routes for already-valid events;
8. increase paper size only when capacity/edge support it.

The exact expansion order can be adapted by measured bottleneck, but quality gates remain unchanged.

### Event-driven opportunity generation

Fixed clock intervals are insufficient as the sole source of candidates.

Collectors/feature tapes should emit deterministic causal event indices for economically informative changes such as:

- CUSUM/price displacement;
- OFI threshold crossing;
- microprice displacement;
- queue depletion/refill;
- spread/depth shock;
- aggressive trade burst;
- liquidation burst;
- OI/funding/context shock;
- multi-venue residual divergence;
- vault position/fill change;
- leader-consensus formation;
- leader disagreement;
- quote staleness;
- book-resilience/recovery event.

Event-driven sampling can increase information density without manufacturing more observations from quiet periods.

Time-grid snapshots remain available for context and validation.

### Multi-scale opportunity generation

The same raw market may contain distinct opportunities at several causal horizons.

Candidate horizon families can include, where supported by certified timing/data:

- sub-second;
- approximately 1 second;
- several seconds;
- tens of seconds;
- short holding windows appropriate to the module.

Horizons are separate hypotheses, not duplicated labels.

Highly overlapping horizons generated by the same shock are clustered for effective-breadth accounting.

### Dynamic universe expansion

Production opportunity generation uses the complete discovered perpetual universe supported by the native venue adapters.

For every epoch:

- refresh full venue universes;
- derive all compatible same-coin venue intersections;
- retain venue-specific instruments for discovery/context;
- maintain liquidity/capacity eligibility;
- promote newly active markets into higher collection tiers;
- demote markets whose capacity/data quality no longer supports economic use.

The opportunity engine cannot define production breadth from a static manually maintained coin list.

### Copy-Vault Opportunity Engine

Copy-Vault opportunity generation expands from "a few permanently watched leaders" to event mining across the complete qualifying public vault universe.

Candidate events include:

- first OPEN;
- ADD;
- REDUCE;
- CLOSE;
- direction flip;
- unusually large position delta;
- unusually high conviction relative to wallet history/NAV;
- onset of a probable metaorder;
- multi-leader directional consensus;
- high-quality leader entering before multi-venue price adjustment;
- leader exit before adverse movement;
- skill/regime reactivation after a dormant period.

Broad REST sweeps provide event discovery.

Priority user-specific WebSocket slots provide low-latency execution candidates.

A vault does not need permanent WebSocket coverage to contribute opportunities.

#### Copy-Vault cohort expansion

Leader discovery is diversified by:

- coin specialization;
- direction specialization;
- holding horizon;
- volatility/liquidity regime;
- account size/NAV cohort;
- anticipatory-versus-reactive classification;
- entry-skill versus exit-skill.

This creates more genuine behavioral opportunity sleeves than one global leaderboard.

Correlated/related wallets are clustered so they do not inflate independent opportunity counts.

### Lead-Lag Opportunity Engine

With six venues, same-coin lead-lag produces up to:

- 15 undirected venue pairs;
- 30 directed leader->lagger venue relationships

per compatible coin before considering regime/horizon.

The production engine evaluates all data-ready directed relationships instead of assuming Binance->Hyperliquid.

Candidate event families include:

- leader price shock;
- microprice shock;
- OFI shock;
- aggressive trade-flow burst;
- L2 queue depletion;
- residual divergence from efficient price;
- liquidation/forced-flow event;
- OI/funding-state shock;
- venue-consensus move with one lagger;
- failed continuation/reversal state;
- cross-asset leader move.

#### Cross-asset breadth

Lead-Lag may add causally validated relationships such as:

- BTC -> alt;
- ETH -> ecosystem/high-beta alt;
- market common factor -> idiosyncratic lagger residual;
- major-perp venue -> smaller-perp venue/coin response.

Cross-asset events must control for common beta/factor exposure and are counted as independent only after clustering/correlation adjustment.

#### Venue-consensus opportunities

Instead of waiting for one designated venue to lead, the engine can generate candidates when:

- several independent high-quality venues move in agreement;
- one data-ready lagger remains behind;
- the lag exceeds timing uncertainty;
- executable edge survives costs.

This can greatly increase robustness and candidate frequency compared with a single leader rule.

### Cross-Venue Opportunity Engine

With six venues, each compatible coin has up to 15 venue pairs and 30 directional long/short route directions before order-type/routing alternatives.

Generate candidates from:

- raw executable bid/ask dislocation;
- common-price residual;
- stale quote;
- local liquidity sweep;
- temporary venue overshoot;
- quote-basis-adjusted deviation;
- post-liquidation fragmentation;
- venue-specific refill/recovery;
- asymmetric funding/basis-adjusted short hold when compatible with the Cross-Venue mandate;
- temporary divergence during listing/status/liquidity changes when data quality remains valid.

Every candidate is evaluated across all eligible execution routes.

Order-type combinations and split-routing increase **execution choice**, not independent signal breadth.

### Residual scanner instead of threshold-only scanner

For every coin, maintain continuous venue residuals against the certified efficient-price layer.

The scanner can rank the full cross-section by:

- residual magnitude;
- residual z-score/state normalization;
- residual velocity;
- quote freshness;
- predicted half-life;
- executable capacity;
- expected net after costs.

The opportunity engine evaluates the most economically promising residuals rather than only waiting for one fixed bps threshold.

### Opportunity frontier

Maintain an adaptive frontier of candidates that are close to becoming executable.

Examples:

- enough edge but insufficient current capacity;
- enough edge but timing uncertainty too high;
- enough signal but fees too large on current route;
- candidate becomes attractive at smaller/larger size;
- candidate becomes attractive under maker fill;
- leader skill positive but observation latency currently too slow.

The frontier tells research/collection which improvement would unlock the most additional opportunities.

### Near-miss mining

Rejected candidates are not discarded without analysis.

For each rejection reason track near-misses:

- edge shortfall in bps;
- latency shortfall;
- capacity shortfall;
- fee shortfall;
- confidence shortfall;
- data-quality shortfall.

If many candidates miss by the same small margin, that becomes a high-value research target.

Near-miss analysis may guide new hypotheses but cannot retroactively turn rejected events into accepted trades.

### Opportunity discovery during COLLECT

COLLECT may compute deterministic event indices and opportunity metadata, without evaluating strategy PnL or tuning thresholds on future outcomes.

Allowed outputs include:

- event timestamps;
- involved venues/coins/leaders;
- feature snapshots;
- residual magnitude;
- depth/capacity state;
- timing quality;
- cluster/event ID.

This gives ANALYZE a pre-indexed opportunity catalog and dramatically reduces scan time.

### Opportunity catalog

Dataset V2 maintains a hash-linked catalog, proposed path:

`catalog/opportunities/<collection_epoch>/...`

Each row/event contains:

- immutable opportunity ID;
- module candidate family;
- event cluster ID;
- coin/instrument;
- venues/leaders involved;
- causal event time;
- evidence asset hashes;
- feature-tape references;
- timing-quality state;
- initial mechanical trigger;
- no PnL label during COLLECT.

The catalog is append-only for the epoch.

### Opportunity clustering

Before economic counting, cluster candidates by shared cause.

Candidate clustering dimensions include:

- same coin shock;
- same liquidation cascade;
- same leader/metaorder;
- same venue outage/staleness event;
- same cross-venue residual episode;
- overlapping holding window;
- strongly correlated feature trajectory.

This prevents the bot from claiming massive breadth by slicing one event into many parameter/horizon variants.

### Opportunity SLOs are diagnostic, not acceptance blockers

Opportunity density is measured continuously, but minimum opportunity counts are initially `MEASURE_ONLY`/optimization targets, not G0/G2 correctness gates.

Reason:

- too few opportunities means the module needs broader research;
- it does not mean existing accepted evidence is invalid.

A module may be marked `OPPORTUNITY_CONSTRAINED` without invalidating its certified trades.

After enough data exists, module-specific opportunity-density targets may be introduced as research/productivity objectives, not evidence-integrity waivers.

### Breadth versus skill

Research should improve both:

- **skill** — net predictive/execution edge per independent opportunity;
- **effective breadth** — number of sufficiently independent opportunities.

Increasing raw event count while reducing average net edge is not automatically beneficial.

The optimizer tracks the frontier:

`daily net ~= effective independent opportunities/day × expected net USD/opportunity`

subject to fill/capacity/capital constraints.

### Breadth expansion must remain economically causal

The system must not create "opportunities" by:

- lowering quality thresholds after seeing PnL;
- duplicating the same event across grids;
- treating execution routes as independent alpha;
- counting child fills as independent leader signals;
- counting highly correlated wallets as separate leaders;
- counting adjacent horizons as independent without clustering;
- reusing the same capital simultaneously in incompatible paper trades.

## Ultra-Scale Intelligence Architecture V5 — immense universe, bounded compute

Alina must be able to observe an immense universe while preserving low latency and replay-grade evidence on the small subset that currently deserves expensive attention.

The core design principle is:

> **scan broadly, update incrementally, promote selectively, evaluate exactly.**

The system must never apply the most expensive L2/model/execution computation uniformly to the entire universe.

### Hot / Warm / Cold universe

Every entity belongs to a dynamic computational tier independent from the data-quality Tier A/B/C labels.

#### COLD

Purpose: universal cheap awareness.

Applies to:

- newly discovered coins;
- low-priority venue pairs;
- low-priority vaults;
- dormant leaders;
- under-sampled regimes.

Maintain only low-cost state such as:

- identity/metadata;
- latest coarse price/context;
- volume/liquidity/OI/funding summaries;
- vault/account fingerprint;
- freshness;
- lightweight anomaly score;
- last promotion/demotion time.

COLD must be cheap enough to cover the broad universe continuously or by fair rotation.

#### WARM

Purpose: event and opportunity detection.

Maintain incremental features such as:

- BBO;
- trades;
- OFI/microprice summaries;
- residual versus efficient price;
- rolling volatility/liquidity;
- liquidation/OI/funding deltas;
- vault position changes;
- leader-quality freshness;
- route-capacity approximations.

WARM is the default state for entities with measurable activity or opportunity potential.

#### HOT

Purpose: exact execution-grade evaluation.

HOT may enable:

- deep/full L2;
- dual-resolution books;
- shadow capture;
- richer clock probes;
- queue state;
- full capacity curves;
- exact route evaluation;
- burst capture;
- expensive model features.

Only a bounded subset may remain HOT simultaneously.

Promotion to HOT is causal and driven by current evidence, not future PnL.

### Coarse-to-fine opportunity cascade

Every large-universe module uses a cascade.

#### Stage 0 — eligibility

Very cheap deterministic filters:

- instrument/trading status;
- data freshness;
- minimum liquidity;
- required venue availability;
- basic vault qualification;
- gross feasibility bounds.

No candidate failing a mathematically necessary condition proceeds.

#### Stage 1 — lightweight streaming score

Use O(1)-update features and inexpensive models to rank large candidate sets.

Examples:

- residual magnitude;
- quote staleness;
- OFI/microprice displacement;
- vault state change;
- liquidation intensity;
- rough gross spread;
- leader freshness/skill prior.

Stage 1 optimizes **recall**, not final precision.

#### Stage 2 — event qualification

Run richer causal features only for candidates crossing predeclared event thresholds or top-K priority boundaries.

Examples:

- multi-venue consensus;
- multi-level L2 imbalance;
- route-specific context;
- leader/metaorder classification;
- regime state;
- timing uncertainty.

#### Stage 3 — exact execution evaluator

Only a small survivor set receives:

- exact L2/VWAP;
- all-in fee/slippage;
- queue/fill simulation;
- non-atomic hedge risk;
- capacity;
- latency-decay;
- funding/holding effects.

Final trade admission is always exact enough for the path's proof contract.

#### Stage 4 — research/challenger models

Advanced G4 models such as Hawkes, Kalman/VECM variants or nonlinear challengers run only where earlier stages indicate sufficient information value.

An advanced model cannot be required merely to decide that an obviously uneconomic candidate should be rejected.

### Approximation boundary

Approximate/sketch/top-K algorithms may be used only for:

- prioritization;
- candidate discovery;
- compute scheduling;
- anomaly/heavy-hitter detection.

They may never:

- certify PnL;
- certify exact L2 continuity;
- replace exact fee/capacity calculation;
- create final economic evidence.

Any candidate promoted by an approximate structure is re-evaluated from exact certified evidence before admission.

Exploration quotas protect against false negatives from approximate prioritizers.

### Incremental keyed state

The fast path maintains state per logical key, rather than rescanning historical files.

Canonical keys may include:

- `venue × coin`;
- `coin × venue_pair`;
- `vault`;
- `leader × coin`;
- `edge_id × regime`.

For each incoming event, update only affected state.

Use incremental formulas for:

- rolling means/variances/EWMA;
- OFI;
- microprice inputs;
- residual;
- volatility/liquidity summaries;
- event intensity;
- capacity summary;
- freshness.

A normal event must not trigger a full-universe recomputation.

### Dirty-set execution

Each event produces a minimal `dirty_set` of keys whose state changed.

Only dirty keys are reconsidered by downstream opportunity stages.

Examples:

- Binance BTC trade updates BTC-related venue relations, not every coin;
- one vault position change reevaluates that vault and traded coin, not 3,000 vaults;
- one OKX SOL L2 update refreshes SOL routes involving OKX, not all 15 route families for all markets.

This is a hard scalability invariant.

### Shared feature computation

A raw event is parsed and transformed once whenever possible.

Shared deterministic features are published to consumers rather than recomputed independently by Copy-Vault, Lead-Lag and Cross-Venue.

Examples:

- BBO state;
- L2 capacity curve;
- OFI;
- microprice;
- efficient-price residual;
- clock quality;
- funding/OI delta;
- liquidation intensity.

Module-specific logic consumes these shared features.

This reduces CPU, memory and inconsistent definitions.

### Same-coin route graph, not full Cartesian explosion

The universe planner must avoid unnecessary quadratic work.

For Cross-Venue and same-coin Lead-Lag:

- build only venue relationships for instruments representing the same normalized underlying;
- materialize only routes where both venues are data-ready and economically compatible;
- skip nonexistent/untradeable intersections.

Cross-asset Lead-Lag relationships are a separate sparse graph selected from frozen research hypotheses, not an all-coins × all-coins Cartesian product.

### Streaming top-K priority queues

Maintain bounded top-K sets for expensive resources, for example:

- most active Copy-Vault leaders;
- largest executable cross-venue residuals;
- strongest Lead-Lag event scores;
- highest near-miss opportunity frontier;
- most stale/high-risk streams needing repair.

Top-K maintenance should be incremental.

Exact heaps are preferred when affordable.

Approximate heavy-hitter/sketch structures are allowed for very large discovery spaces, but only under the approximation boundary above.

### Value-of-information scheduler

Scarce resources are allocated using a transparent expected-value priority.

Candidate priority can combine:

- probability of generating an executable opportunity;
- estimated economic information gain;
- staleness/coverage debt;
- uncertainty reduction;
- current opportunity frontier distance;
- data quality;
- compute/API/network cost.

Conceptually:

`priority ~= expected_information_or_opportunity_value / marginal_resource_cost`

This score schedules:

- HOT promotions;
- deep-L2 subscriptions;
- Copy-Vault priority WS slots;
- archive repair jobs;
- research compute;
- shadow feeds.

The score is a scheduler heuristic, not economic proof.

### Promotion hysteresis

Avoid computational thrashing.

Promotion/demotion policies use:

- minimum HOT dwell time;
- cooldown;
- separate promote/demote thresholds;
- emergency demotion for bad data/overload.

A symbol oscillating around one threshold must not repeatedly open/close expensive subscriptions every few seconds.

### Dynamic shard sizing

Each GitHub runner measures:

- messages/sec;
- bytes/sec;
- parse time;
- feature-update time;
- queue depth;
- event-loop lag;
- checkpoint/publish throughput;
- CPU/memory.

Shard size is adapted from measured headroom.

If a shard approaches latency/backpressure limits:

1. split the shard;
2. move low-priority WARM/COLD work elsewhere/later;
3. reduce optional derived work;
4. protect HOT raw evidence.

Do not wait for queue drops before resizing.

### Backpressure and overload policy

All queues are bounded and observable.

Overload handling priority:

1. never silently lose HOT raw execution-critical data;
2. preserve WAL/timestamps/continuity evidence;
3. shed/reduce optional derived computations;
4. degrade WARM frequency;
5. defer COLD scans;
6. split/rebalance the runner.

If execution-critical raw data is lost despite safeguards, the affected interval is quarantined according to G2.

Load shedding may reduce opportunity breadth temporarily; it may never fabricate continuity.

### Fast path versus batch path

Separate two execution modes.

#### Fast path

Event-by-event or very small micro-batches:

- timestamp;
- WAL;
- sequence/book update;
- incremental feature state;
- event detection;
- top-K/prioritization.

Optimize for predictable latency.

#### Batch/vector path

Larger immutable batches:

- broad feature scans;
- cross-sectional ranking;
- historical summaries;
- ANALYZE;
- research matrices;
- report aggregation.

Optimize for throughput.

Do not force row-by-row Python-style processing on analytical workloads where vectorized columnar execution is materially faster.

### Columnar derived tapes

Raw evidence remains source-of-truth in the existing durable format.

Derived analytical tapes may use Arrow/Parquet-compatible columnar batches when benchmarks show clear benefit.

Desired properties:

- contiguous typed columns;
- vectorization/SIMD friendliness;
- predicate/column pruning;
- efficient compression;
- zero/low-copy interchange where practical;
- deterministic schema/versioning.

DuckDB/Arrow/Polars or equivalent tooling may be used for batch analytics only if benchmarked against the current implementation.

No dependency is promoted solely because it is fashionable.

### Micro-batching

High-volume derived writes should use bounded micro-batches instead of one filesystem/network operation per market event.

Batch size is constrained by:

- maximum acceptable durability latency;
- memory;
- event-rate;
- checkpoint cadence.

Raw receive timestamps remain event-level even when persistence is batched.

### Snapshot + delta state persistence

Long-lived keyed feature state is checkpointed as:

- compact state snapshot;
- last consumed event/sequence identifiers;
- universe/schema digest;
- incremental delta/WAL after snapshot.

A successor runner restores the latest valid snapshot then applies remaining deltas.

This avoids rebuilding hours of feature history at every GitHub handoff.

State snapshots are derived artifacts; raw immutable evidence remains the recovery authority.

### Cache hierarchy

Use explicit caches for expensive stable data:

- instrument metadata;
- symbol normalization;
- fee/rule version;
- venue capability matrix;
- universe intersections;
- vault static metadata;
- archive availability.

Caches include source/effective timestamps and invalidate on change.

Do not repeatedly fetch or recompute static data on each event.

### Performance budgets

Every fast-path component has measured latency/throughput budgets.

Track at minimum:

- socket receive -> WAL timestamp;
- WAL -> normalized event;
- normalized event -> keyed-state update;
- state update -> candidate event;
- candidate -> HOT promotion decision;
- exact evaluator latency;
- checkpoint age.

Report p50/p95/p99.

Performance targets begin as `MEASURE_ONLY`; after baseline measurement, scoped thresholds may be promoted where a consumer genuinely depends on them.

### Opportunity recall audit

A cascade can be fast but useless if Stage 1 discards future winners.

Therefore periodically evaluate Stage-1/Stage-2 recall on TRAIN/validation:

- fraction of later high-net candidates that survived cheap filters;
- false-negative reasons;
- compute saved;
- latency saved.

The cheap cascade is optimized for high recall of economically promising candidates, not maximum classification accuracy.

Untouched OOS remains unavailable for cascade tuning.

### Resource-efficiency scoreboard

Per collection epoch report:

- universe size;
- COLD/WARM/HOT counts;
- events/sec;
- raw MB/sec;
- CPU/event;
- memory/key;
- HOT promotions/hour;
- promotion precision;
- opportunity recall estimate on eligible TRAIN/validation audits;
- exact-evaluator calls/day;
- compute saved by cascade;
- queue high-water marks;
- shard splits/rebalances;
- checkpoint restore time;
- analysis rows/sec.

This makes scalability measurable rather than anecdotal.

### Ultra-scale module behavior

#### Copy-Vault

- COLD: all qualifying public vault identities/low-cost state fingerprints;
- WARM: vaults with recent changes, nontrivial positions or rising leader-quality;
- HOT: scarce priority leaders with live WS + associated traded-coin deep market data.

Only changed vaults enter targeted reconciliation.

#### Lead-Lag

- COLD: all normalized compatible coin/venue metadata;
- WARM: broad BBO/trade/residual/OFI state;
- HOT: current shocks, high-score directed edges, consensus/lagger events requiring deeper L2.

Directed-edge state updates only for affected coin/venues.

#### Cross-Venue

- COLD: all same-coin compatible venue intersections;
- WARM: continuous BBO/residual/coarse capacity;
- HOT: top executable residuals/near-misses requiring exact multi-leg L2 and route auction.

The exact route evaluator runs only on HOT survivors.

### Ultra-scale computational invariants

To keep an immense universe fast on standard GitHub-hosted runners, the fast path obeys explicit complexity budgets.

#### Stage complexity

The normal event path should be dominated by local keyed/incremental operations.

Targets:

- Stage 0 raw ingest/WAL timestamping: O(1) per event aside from bounded serialization;
- Stage 1 keyed state/features: O(1) or bounded-small work per affected key;
- Stage 2 candidate ranking: bounded top-K / sparse-neighbor updates, never a full-universe sort per event;
- Stage 3 exact economic evaluator: expensive work only for HOT survivors;
- historical/vector analysis: batch/vectorized, never row-by-row Python loops over the whole raw tape when an equivalent vectorized path exists.

These are design targets rather than universal asymptotic proofs. Any deviation must be benchmarked and justified.

#### No accidental Cartesian explosions

The engine precomputes compact compatibility graphs for:

- coin -> available venues;
- venue pair -> compatible normalized contract;
- wallet -> currently held/traded coins;
- coin -> sparse cross-asset hypotheses;
- module path -> required evidence families.

It must not materialize all-vault × all-coin, all-coin × all-coin, or all-venue × all-symbol products when most edges are invalid.

Cross-asset Lead-Lag remains sparse and hypothesis-driven.

#### Incremental state, TTL and compaction

Per-key derived state has explicit lifetime/compaction policy.

Keep only the minimum rolling state required for live decisions, for example:

- last certified BBO/L2 state;
- rolling OFI/microprice windows;
- current residual/volatility/liquidity estimates;
- current leader/vault fingerprints;
- small rolling event summaries;
- current opportunity/frontier state.

Older raw evidence is sealed durably and removed from live memory after checkpoint/verification.

No runner should retain an entire multi-hour raw epoch in RAM to compute a feature that can be maintained incrementally.

#### Shared computation graph

Common transforms are computed once per event/key and fan out to consumers.

Examples:

`raw book -> normalized book -> BBO/depth curve -> microprice/OFI/capacity -> {Lead-Lag, Cross-Venue}`

`vault state -> position delta -> activity event -> {Copy-Vault discovery, priority scheduler}`

A module cannot duplicate the same expensive deterministic L2 reconstruction merely because its strategy code lives in a different package.

#### Fast-path allocation budget

Each HOT/WARM/COLD stage has explicit CPU/memory/API/network budgets.

When measured utilization approaches the configured headroom:

1. stop promoting optional new HOT work;
2. split or shrink overloaded WARM shards;
3. defer low-value derived computations;
4. reduce COLD refresh frequency within freshness policy;
5. preserve required raw Tier-A/HOT capture and WAL durability.

The scheduler reacts before bounded queues overflow.

#### Promotion recall protection

The cheap cascade is allowed to be approximate only for **prioritization**.

On TRAIN/validation, continuously estimate:

- recall of eventually profitable/executable events at each stage;
- false-negative reasons;
- time from raw event to HOT promotion;
- compute saved per retained profitable candidate.

If a coarse stage saves compute but systematically drops profitable candidate classes, widen that stage or create a separate specialist lane.

#### Specialist lanes

A single universal coarse score is not required.

Maintain small specialist promotion lanes when distinct opportunity families have different signatures, for example:

- Copy-Vault leader activity;
- same-coin multi-venue dislocation;
- venue-consensus/lagger shock;
- liquidation/forced-flow event;
- native TWAP / scheduled-flow event;
- medium-horizon trend/breakout event;
- cross-instrument relative-value/basis event;
- cross-asset spillover;
- stale-quote/resilience event.

Each lane has its own high-recall cheap trigger and feeds the same bounded HOT exact evaluator.

This avoids forcing rare but valuable edge families through a score trained for common events.

#### Deterministic replay of derived state

Every incremental state transition needed by an economic decision must be reproducible from immutable raw evidence plus versioned code/config.

Compact state snapshots accelerate recovery but are never opaque authority.

For any admitted decision, the system can reconstruct:

- raw source events;
- state before decision;
- feature values;
- promotion path;
- exact evaluator inputs;
- gate decisions.

Speed cannot come at the cost of auditability.

### Consolidated architecture coverage

This specification intentionally preserves all previously validated design layers. Implementation planning must treat the following as one coherent system, not replace a newer layer by deleting an older one:

- **Manual Phase Orchestrator:** `IDLE / COLLECT / ANALYZE`;
- **Autonomous COLLECT relay:** automatic successor jobs until the user changes phase;
- **Collector V4 Extreme Replay-Grade:** raw WAL, handoff overlap, L2 certification, repair/quarantine, module-complete evidence;
- **Strategy / PnL Acceleration VNext:** +4 USD net/day/module first milestone and scalable after-cost PnL;
- **Edge Research Program V2:** broad defensible edge library with anti-overfitting controls;
- **Acceptance Architecture V2:** scoped G0-G5 gates, dependency DAG and graceful degradation;
- **Module Optimization V3:** edge portfolios, champion/challenger, decay monitoring and compute prioritization;
- **Opportunity Expansion V4:** massive pre-gate candidate funnel and independent-opportunity accounting;
- **Ultra-Scale V5:** COLD/WARM/HOT universe, cascade promotion, incremental state, sparse graphs, value-of-information scheduling and vectorized analysis;
- **Profitability Convergence V6:** friction-first module expansion, execution alpha, forced/scheduled flow, slow trend/relative-value research and an explicit economic-distance-to-+4-USD/day scheduler.

No implementation task may simplify one layer by silently violating another.

The preferred resolution to conflict is:

1. preserve paper/safety/causality;
2. preserve raw data/provenance;
3. preserve exact final economic evaluation;
4. reduce optional breadth/complexity before weakening quality;
5. use narrower scopes/tiers/cascades rather than global blocking.



### Profitability Convergence V6 — friction-first path to +4 USD net/day

The next architecture layer treats the first economic milestone — **+4 USD net/day proven under Alina's paper/replay evidence contract** — as a research-allocation target, not as a promise and not as a reason to weaken gates.

The core diagnosis from existing Alina evidence is that many simple ideas have shown **small gross predictability but insufficient economic amplitude after friction**. Therefore the system must stop treating every statistically interesting signal as an equally valuable research direction.

The V6 rule is:

> **prefer mechanisms capable of producing sufficiently large, sufficiently frequent, sufficiently capacitated after-cost opportunities; use micro-signals mainly to improve execution or timing unless they independently clear the full economic proof.**

The target remains paper-only and evidence-driven. No module may be activated merely because external literature reports an effect.

#### Economic-distance-to-target accounting

For every promoted module, edge sleeve and serious challenger, estimate conservatively:

```text
gross_edge_bps
- explicit_fees_bps
- spread_cost_bps
- expected_slippage_bps
- delay_cost_bps
- adverse_selection_bps
- hedge_or_legging_cost_bps
- funding_or_holding_cost_bps
= expected_net_edge_bps
```

Then translate the edge into an economic throughput estimate:

```text
conservative_net_usd_day
= independent_opportunities_per_day
  * admitted_fraction
  * expected_fill_probability
  * expected_net_usd_per_filled_opportunity
  * capacity_scaling
```

All terms must come from certified data or explicitly conservative assumptions.

Track:

- `target_gap_usd_day = max(0, 4.0 - conservative_net_usd_day)`;
- net USD/day lower confidence bound;
- independent opportunity count/day, not raw signal count;
- capacity-limited and capital-limited USD/day;
- turnover and cost drag/day;
- capital-time efficiency;
- compute/data cost of the research lane;
- dominant bottleneck: `EDGE / FREQUENCY / FILL / CAPACITY / COST / DATA / EVIDENCE`.

No point estimate can mark the target as proven. The proof scoreboard uses frozen OOS/forward evidence and conservative uncertainty bounds.

#### Research-value scheduler

The research-compute allocator should prioritize work by expected reduction in the target gap, for example:

```text
research_value
≈ probability_of_clearing_next_gate
  * plausible_incremental_net_usd_day
  * independence_value
  / (compute_cost + data_cost + implementation_cost)
```

This is a scheduling heuristic, not a profitability estimator.

Requirements:

- untouched OOS/forward data never influences the probability estimate used to tune a candidate;
- a cheap but structurally dead idea stays dead;
- a high-upside mechanism with missing data may receive collection priority without receiving paper capital;
- a near-miss that fails only because of execution cost may receive execution research priority;
- a candidate with tiny gross amplitude cannot outrank a larger structural edge merely because its backtest has many observations;
- exploration budget remains mandatory so the scheduler cannot lock permanently onto today's leaders.

### Shared Execution Alpha Core

Execution becomes a first-class shared optimizer across all modules, not a fixed cost subtraction and not a standalone source of imaginary alpha.

For every economically eligible opportunity, compare causally and on the same decision timestamp:

- immediate taker;
- passive maker;
- maker with bounded timeout then taker;
- short causal wait;
- alternate venue;
- split routing across certified depth;
- `NO_TRADE`.

The route evaluator estimates:

- queue/fill probability where measurable;
- expected spread paid or captured;
- fee/rebate;
- depth slippage;
- latency;
- adverse-selection markout;
- cancellation/timeout risk;
- missed-opportunity cost;
- hedge/legging risk for multi-leg positions;
- remaining alpha half-life.

Rules:

- fee savings alone can never justify maker execution;
- maker improvement is credited only after fill probability and adverse selection;
- if `observation_latency + decision_latency + expected_fill_latency >= alpha_half_life`, reject or select a faster route;
- microprice/OFI/order-book imbalance remain execution features unless they independently clear full after-cost strategy proof;
- every module reports `signal_alpha` separately from `execution_alpha_or_cost`;
- route policy must beat simple taker and simple maker baselines OOS before promotion.

This layer is allowed to rescue a genuine gross edge from excessive friction; it is not allowed to manufacture edge by optimistic fills.

### Candidate Module 4 — Forced-Flow / Liquidation V2

Liquidation research becomes a first-class candidate module rather than an incidental signal.

The module maintains a broad **high-leverage universe** distinct from the smart-wallet universe.

Per wallet/position where observable, maintain causal state such as:

- current notional;
- leverage/margin state;
- liquidation-distance proxy;
- coin;
- side;
- position concentration;
- recent size change;
- freshness/confidence.

Aggregate into a **liquidation-threshold density map** by coin and price bucket.

The exact economic evaluator must combine, where available:

- vulnerable notional near current price;
- executable depth to the vulnerable zone;
- expected forced-notional/depth ratio;
- open-interest change;
- taker-flow asymmetry;
- book depletion/resilience;
- realized liquidation fills/events;
- cross-venue price impact;
- cross-asset propagation.

Model a causal state machine such as:

`BUILDUP -> NUCLEATION -> CASCADE -> ABSORPTION -> RECOVERY`

but do not assume every cascade has a universal precursor.

Independent edge sleeves to test include:

- forced-flow continuation while liquidity is withdrawing;
- overshoot/reversal after forced flow exhausts;
- absorption/backstop response;
- cross-asset propagation after a large forced event;
- venue-to-venue transmission;
- post-deleveraging recovery conditional on OI clearing.

Requirements:

- no generic "large liquidation = buy/sell" rule;
- no claim of predicting exogenous shock cascades;
- event clustering prevents one liquidation cascade from becoming hundreds of independent samples;
- promotion requires executable post-cost markout at horizons Alina can actually reach;
- the old low-leverage smart-wallet population cannot be reused as the only liquidation universe.

### Candidate Module 5 — Scheduled Flow / Native TWAP & Metaorder

Hyperliquid native TWAP activity receives its own specialist lane because protocol-native TWAP programs can expose parent-order information while active and TWAP child fills are identifiable.

Where the read-only/public data path provides the evidence, maintain:

- TWAP/program identifier;
- wallet;
- coin;
- side;
- total announced size;
- configured duration;
- activation time;
- executed size/notional;
- estimated remaining size;
- progress fraction;
- slice cadence;
- participation versus market volume;
- same-side active TWAP dominance;
- opposite-side TWAP netting;
- book tilt/depth response;
- post-completion markout.

Use `userTwapSliceFills` / time-bounded TWAP slice history and public on-chain/indexed TWAP state only where provenance is explicit and replayable.

Test separate hypotheses rather than one universal direction:

- continuation during a sufficiently large remaining program;
- liquidity absorption/book-tilt during visible execution;
- cost/impact differential between visible TWAP and latent metaorder flow;
- interaction between a hidden same-direction metaorder and already-visible TWAP flow;
- completion-time impact decay/reversal;
- execution avoidance: do not cross into a known adverse scheduled flow when waiting has higher expected value.

Requirements:

- do not infer unobserved parent size as fact;
- if active parent-order parameters are unavailable from the current source, label them `UNMEASURABLE` and use only proven slice history;
- visible TWAP flow is not automatically informed flow;
- front-running is not assumed profitable;
- exact direction, horizon and execution policy must be validated OOS after costs.

### Scheduled/clock-time specialist lane

Scheduled-flow research may test recurring deterministic market-clock effects, including:

- quarter-hour boundaries;
- funding settlement windows;
- known TWAP slice cadence;
- venue maintenance/restart windows where applicable;
- session transitions.

Every periodic hypothesis must be preregistered, compared with non-boundary placebos, and tested after costs.

Clock-time structure may improve event generation or execution timing even if it never becomes a standalone module.

### Candidate Module 6 — Medium-Horizon Trend / Breakout

Create a separate medium-horizon trend family rather than resurrecting killed residual-momentum experiments.

Candidate causal horizons may include:

- 15 minutes;
- 1 hour;
- 4 hours;
- 12 hours;
- 24 hours;

with holding periods chosen to keep expected move amplitude materially larger than round-trip friction.

Candidate features may include:

- own-asset time-series trend;
- breakout/range expansion;
- volatility expansion;
- volume/trade-intensity confirmation;
- open-interest confirmation;
- multi-venue confirmation;
- market/beta residualization;
- cross-sectional dispersion/regime state;
- CTREND-style multi-horizon price/volume ensembles as challengers.

Rules:

- residual momentum variants already killed by Alina remain killed unless the mechanism/data/horizon materially changes;
- cross-sectional momentum is not assumed superior to time-series trend;
- high turnover is penalized explicitly;
- long/short baskets must include borrow/funding/hedge economics where relevant;
- dynamic universe construction must avoid survivorship bias;
- no trend candidate is promoted unless net edge survives realistic fees/slippage and regime splits.

### Candidate Module 7 — Cross-Instrument Relative Value

Extend beyond same-instrument venue dislocation into certified cross-instrument relationships.

Eligible research pairs/routes include, only when contract equivalence and hedge economics are explicit:

- spot vs perpetual;
- perpetual vs perpetual across venues;
- perpetual vs dated future where a supported venue/data path exists;
- mark vs oracle/index/spot-composite residual;
- funding-adjusted cross-venue residual;
- basis/term-structure convergence;
- delta-neutral funding/basis structures with **real modeled legs**, never a fictional hedge fee.

The module may use rolling stationarity/cointegration/OU-style residual models as challengers, but statistical mean reversion alone never proves executability.

Requirements:

- both/all legs are priced from executable quotes;
- entry and exit capacity are measured on every leg;
- funding/borrow/collateral/margin and legging risk are explicit;
- no naked one-leg "carry arbitrage";
- funding normalization is tested against raw-spread baselines;
- route admission requires positive after-cost EV with uncertainty margin;
- basis trades remain exposed to margin/liquidation risk and cannot be called risk-free.

### Options / Volatility Intelligence Layer

Options information is initially a **shared research/context layer**, not an options trading module.

Where Deribit or another certified options source is available, derive point-in-time features such as:

- ATM implied volatility;
- 25-delta and 10-delta risk reversal;
- butterfly;
- term-structure slope/curvature;
- IV minus realized volatility;
- skew shock;
- call/put wing demand;
- jump-risk-premium proxies where defensibly measurable.

Use them as candidate conditioning inputs for:

- Forced-Flow;
- Trend;
- Lead-Lag;
- Cross-Venue / Relative Value;
- execution/risk regime selection.

Rules:

- no options execution is required;
- no source becomes a hard global dependency;
- post-2024 signal decay documented in external research is treated as a warning, so every options-derived feature requires recent rolling/OOS validation;
- feature value is incremental only if it improves a simpler baseline after costs and multiple-testing controls.

### Kill-resurrection firewall

Previously measured failures cannot silently re-enter the candidate pool under a new name.

Unless the new experiment changes the economic mechanism, data resolution, execution regime or horizon enough to create a genuinely new hypothesis, keep the prior verdict for:

- naive short-horizon mean reversion;
- standalone OFI/microprice/order-book imbalance at the previously measured cadence;
- killed residual-momentum variants;
- unhedged funding/carry;
- naive market making credited only by maker fees;
- mid-price-only cross-venue dislocation;
- any copy variant whose signal amplitude remains below realistic follower friction.

A new feature may still be reused as:

- execution timing;
- regime conditioning;
- rejection filter;
- candidate-priority feature;

without pretending the killed standalone strategy became profitable.

### Module portfolio after V6

V6 does **not** instantly activate seven production modules.

The economic architecture becomes:

**Current core modules**
- Copy-Vault;
- Lead-Lag;
- Cross-Venue.

**First-class candidate modules / sleeves**
- Forced-Flow / Liquidation V2;
- Scheduled Flow / Native TWAP & Metaorder;
- Medium-Horizon Trend / Breakout;
- Cross-Instrument Relative Value.

**Shared intelligence/execution layers**
- Execution Alpha Core;
- Options / Volatility Intelligence;
- Ultra-Scale opportunity scheduler;
- periodic/clock-time specialist lane.

Each candidate starts at scoped research gates (`G3/G4`, `MEASURE_ONLY` or equivalent) and cannot become a global blocker.

Promotion requires:

1. explicit evidence contract;
2. certified data coverage;
3. causal TRAIN/validation;
4. frozen untouched OOS;
5. forward/shadow confirmation where required;
6. positive net after all realistic costs;
7. sufficient effective independent events;
8. capacity sufficient to matter toward the +4 USD/day target;
9. conservative target-gap improvement;
10. no conflict with safety/paper-only invariants.

### Research basis for Profitability Convergence V6

High-signal external research reviewed on 2026-09-25 motivates these hypotheses, while **Alina's own certified evidence remains the authority for promotion**:

- **Barone & Lillo, _Trading in the Sunshine or in the Shade: Market Impact and Adverse Selection on Hyperliquid_ (2026 preprint):** reconstructs millions of Hyperliquid metaorders and hundreds of thousands of native TWAPs; visible TWAP programs have distinct impact/execution behavior and observable program/slice structure, motivating a scheduled-flow lane rather than post-fill copy alone.
- **Hyperliquid official read-only info/WebSocket documentation:** exposes user TWAP slice fills/history and identifies TWAP slices by parent TWAP IDs; these data are research inputs, while trading endpoints remain outside the paper/read-only path.
- **_Where does the criticality live?_ (2026 preprint) and related liquidation-cascade work:** liquidation precursors are heterogeneous across events, but leverage/open-interest/order-flow/liquidity state carries mechanistic information; V6 therefore models buildup/cascade/absorption states rather than assuming one universal crash predictor.
- **Studies on leverage/systemic risk in crypto perpetuals (2026):** changes in open interest and liquidation transmission provide a basis for testing forced-flow propagation, not for claiming deterministic crash prediction.
- **_A Trend Factor for the Cross Section of Cryptocurrency Returns_ (2026):** multi-horizon price/volume trend information remains a candidate source of return predictability including large/liquid coins and motivates a CTREND-style challenger under Alina's stricter cost/OOS rules.
- **realistic-assumption crypto momentum studies:** time-series momentum appears more robust than many cross-sectional variants after accounting for real-world constraints; this motivates a medium-horizon own-asset trend family, not resurrection of killed residual momentum.
- **Chi et al., _An empirical investigation on risk factors in cryptocurrency futures_ (2023):** basis is a strong cross-sectional futures factor and motivates basis/relative-value research, while Alina must model current execution/margin/funding costs rather than import historical returns.
- **Neo, _Bitcoin options risk-reversal predictability_ (2026 dissertation):** option risk-reversal/butterfly information has documented predictive content but weakens after 2024; V6 therefore uses options primarily as a decaying contextual feature requiring recent OOS validation.
- **Albers et al., _To Make, or to Take, That Is the Question_ and related order-book execution work:** maker fill probability and adverse selection are inseparable, supporting the shared Execution Alpha Core and forbidding fee-only maker optimism.
- **_The Quarter-Hour Effect: Periodic Algorithmic Trading and Return Predictability in Cryptocurrency Futures_ (2026 preprint):** motivates a tightly scoped periodic-flow lane with placebo testing rather than an assumed universal clock-time edge.
- **recent matched-market short-horizon mean-reversion evidence:** statistically detectable reversal can remain smaller than round-trip cost, reinforcing V6's rule that small standalone micro-signals should not outrank larger structural mechanisms.

External research creates hypotheses only. It cannot mark an Alina module `PROMOTED`, cannot prove +4 USD/day, and cannot override an Alina `KILL` verdict without a materially new preregistered experiment.


### Research basis for Ultra-Scale V5

This architecture is informed by:

- **Apache Flink stateful-stream principles:** keyed state keeps per-key updates local and checkpointing provides bounded recovery; backpressure must be explicitly managed.
- **streaming top-K/heavy-hitter research:** huge streams can maintain a small high-priority candidate set with bounded memory; Alina restricts approximation to prioritization.
- **coarse-to-fine/cascade ranking systems:** inexpensive high-recall stages reduce candidate sets before expensive re-ranking/evaluation.
- **load-shedding research:** under overload, preserving high-importance events yields better system quality than uncontrolled queue growth; Alina applies this only to lower-priority/derived work, never by silently discarding required execution evidence.
- **Apache Arrow:** columnar contiguous layouts enable vectorization and zero-copy interchange.
- **DuckDB/vectorized execution:** batch/vector execution reduces per-row analytical overhead for OLAP-style scans.
- **adaptive/value-of-information scheduling:** limited measurement/compute resources should concentrate where marginal information/opportunity value is highest, while exploration prevents starvation.

These sources guide compute architecture. Exact economic decisions still use certified Alina evidence.


### Research basis for Opportunity Expansion V4

This architecture is informed by:

- **Grinold/Kahn breadth literature:** value can improve with more independent information opportunities, but raw asset/forecast count overstates breadth when signals are correlated.
- **Effective-breadth literature:** independent dimensionality can be substantially below the number of nominal bets.
- **Information-driven/event sampling research:** event/CUSUM/volume/dollar-style sampling can concentrate modeling on informative market changes rather than arbitrary clock intervals.
- **High-frequency cross-asset lead-lag literature:** multi-asset price formation supports testing information spillovers beyond same-asset venue pairs.
- **Crypto fragmentation literature:** fragmented liquidity across venues creates a much larger route/opportunity universe, but costs and capacity determine executability.
- **Metaorder/market-impact literature:** many child trades belong to one underlying parent event, motivating event clustering and effective-sample accounting.

These sources motivate broad opportunity generation. They do not justify relaxing Alina's proof gates.


### Research basis

The VNext design is informed by external research reviewed on 2026-09-25, while repository data remains the authority for promotion decisions.

High-signal sources include:

- Albers, Cucuringu, Howison, Shestopaloff, *Fragmentation, Price Formation, and Cross-Impact in Bitcoin Markets* (Oxford / peer-reviewed version DOI 10.1080/1350486X.2022.2080083): multi-venue order-book/trade features, leader-lagger networks, mean divergence, transaction-cost sensitivity and maker/taker distinctions.
- Albers et al., *To Make, or to Take, That Is the Question* (2026 preprint/live experiment): maker fill probability is entangled with adverse selection and queue position; passive execution cannot be credited from fee savings alone.
- Henker et al., *Athena: Smart order routing on centralized crypto exchanges using a unified order book* (2024, DOI 10.1002/nem.2266): unified multi-exchange books and order splitting can reduce implicit execution cost.
- Baker & McHale, *Optimal Betting Under Parameter Uncertainty: Improving the Kelly Criterion* (Decision Analysis, DOI 10.1287/deca.2013.0271): sizing should shrink when edge estimates are uncertain.
- *Binance Leads, but Some Wallets Anticipate* (2026 Research Square preprint): aggregate Hyperliquid flow follows Binance, but a persistent minority of wallets exhibits out-of-sample anticipatory behavior; this motivates wallet-level anticipation scoring rather than copying broad leaderboards.
- *When Does Order Flow Matter? State-Dependent L2 Liquidity-State Transitions in Crypto Futures* (2026 preprint): L2 state/shape and incremental order-flow value are asset/regime dependent, supporting state-specific Lead-Lag policies.

These sources motivate hypotheses. They do not themselves prove profitability in Alina.


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

The first standardized target is a separately proven net result of at least 4 USD per UTC day per module under the frozen proof contract. PnL may not be combined across modules to rescue a failing module. After that milestone, the objective is the highest robust scalable daily net PnL supported by OOS/forward evidence.

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

## Acceptance Architecture V2 — scoped gates, not one giant blocker

The acceptance catalog is intentionally large because it documents safety, data quality, module readiness, research promotion, and economic-proof requirements. **It is not a single global AND-condition.**

A criterion must block only the smallest scope whose correctness actually depends on that criterion.

Normative rule:

> fail closed inside the affected scope; degrade gracefully outside it.

A failed OKX/SOL/L2 interval may invalidate that exact stream interval and any strategy path that requires it. It must not automatically stop unrelated Binance/ETH collection, a healthy Copy-Vault leader cohort, or a Cross-Venue route that does not depend on OKX/SOL.

### Gate classes

Every acceptance criterion belongs to exactly one enforcement class.

#### G0 — GLOBAL_FATAL

Use only for invariants whose violation makes **all** relevant execution scientifically or operationally invalid.

Examples:

- real-order/paper-only safety flags are violated;
- self-hosted/local-PC execution is introduced without explicit authorization;
- phase-control state is invalid/ambiguous in a way that prevents safe intent resolution;
- epoch isolation is broken such that stale work can be mistaken for current evidence;
- the system cannot establish provenance for newly created evidence globally;
- a control-plane defect can cause work to execute in the wrong phase.

A G0 failure stops new heavy work globally until resolved.

G0 must remain deliberately small. New criteria default to a narrower class unless a written dependency argument proves that global blocking is necessary.

#### G1 — CONTROL_PLANE_BLOCKER

Blocks one orchestration domain or phase, not unrelated stored evidence.

Examples:

- successor relay for the active collection epoch cannot safely determine ownership;
- current-epoch campaign creation is inconsistent;
- ANALYZE stage ordering is broken;
- durable publication authority for new outputs is unavailable.

Previously published immutable evidence remains usable if its own provenance/integrity gates are still valid.

#### G2 — SCOPE_DATA_BLOCKER

Blocks only the smallest affected data scope.

Canonical scope:

`venue × instrument × channel × certified interval × collection epoch`

Examples:

- L2 sequence gap;
- broken book synchronization;
- stale clock evidence;
- queue drop;
- failed reconciliation;
- parser corruption;
- missing instrument metadata required by that channel's consumer.

Result:

- affected stream/interval -> `REJECT` or `PARTIAL`;
- repair pipeline is triggered when possible;
- unrelated streams continue;
- downstream dependencies referencing that stream are marked `BLOCKED_DEPENDENCY`.

No G2 failure is allowed to become a global stop merely for convenience.

#### G3 — MODULE_PATH_READINESS

Blocks one economic evidence path, not the whole module and not other modules.

The smallest defensible proof path is:

- Copy-Vault: `leader/cohort × coin × latency class × entry/exit policy`;
- Lead-Lag: `leader venue -> lagger venue × coin × regime × horizon × execution mode`;
- Cross-Venue: `coin × venue pair/route × direction × entry/exit execution policy`.

A module may continue analyzing and certifying other paths while one path is unavailable.

A module is considered **research-ready** when at least one path has a complete evidence dependency closure.

A module is considered **economically certifiable** only for the exact paths whose complete dependency closure is PASS.

#### G4 — HYPOTHESIS_PROMOTION_GATE

Applies to a strategy/research variant.

Examples:

- Hawkes model;
- Kalman/VECM efficient price;
- SBE-specific feature;
- leader-consensus variant;
- maker queue model;
- liquidation regime;
- cross-asset spillover.

Failure means:

- that hypothesis is not promoted;
- simpler/frozen baselines remain available;
- collection and unrelated research continue.

A non-implemented or failed optional advanced hypothesis must never block a working simpler baseline.

#### G5 — MODULE_ECONOMIC_PROOF_GATE

Blocks only the claim that a module has achieved a specified economic milestone.

It does **not** block further collection or research.

For the +4 USD net/day milestone, G5 requires the frozen proof contract for that module/path set, including after-cost PnL, causal/OOS/forward validity, capacity, fill realism, and stress survival.

Copy-Vault failing G5 does not prevent Lead-Lag or Cross-Venue from proving their own milestones.

### Criterion metadata registry

The numbered criteria in this specification remain the human-readable normative catalog.

Implementation must additionally create a machine-readable registry, proposed path:

`config/acceptance_criteria.yaml`

Every criterion entry must contain:

```yaml
id: 28
title: unresolved queue/sequence loss cannot be replay-safe
gate_class: G2
scope_type: stream_interval
phases: [COLLECT, QUALITY, REPLAY]
enforcement: BLOCK_SCOPE
dependencies: []
evidence:
  - coverage_ledger
  - continuity_receipt
on_fail:
  state: REJECT
  action: quarantine_and_repair
waiver_allowed: false
```

Required metadata fields:

- stable criterion ID;
- short title;
- gate class;
- scope type;
- applicable phase(s);
- enforcement action;
- dependency IDs/capabilities;
- evidence artifact(s);
- failure state;
- recovery/remediation action;
- whether a waiver is allowed;
- optional SLI/SLO binding.

No criterion without explicit scope/enforcement metadata may be used as a blocking gate.

### Enforcement actions

Allowed enforcement values are deliberately limited:

- `BLOCK_GLOBAL`;
- `BLOCK_PHASE`;
- `BLOCK_SCOPE`;
- `BLOCK_PROMOTION`;
- `BLOCK_ECONOMIC_CLAIM`;
- `DOWNGRADE_SCOPE`;
- `WARN_ONLY`;
- `MEASURE_ONLY`.

There is no generic `FAIL_EVERYTHING` action.

### Status model

Criteria and capabilities are not reduced to one red/green percentage.

Allowed statuses include:

- `PASS`;
- `FAIL`;
- `BLOCKED_DEPENDENCY`;
- `DEGRADED`;
- `REPAIRING`;
- `NOT_APPLICABLE`;
- `NOT_EVALUATED`.

A numerical “158/160 passed” score is informative only as coverage. It can never override a critical failed dependency, and one optional failed research criterion cannot invalidate 159 healthy unrelated capabilities.

### Dependency DAG

The orchestrator builds a dependency graph from required capabilities.

Example:

`CrossVenue:BTC:HL-Binance:taker-taker`

may depend on:

- certified HL BTC BBO/L2 interval;
- certified Binance BTC BBO/L2 interval;
- same-clock timing evidence;
- instrument rules;
- fee provenance;
- entry/exit capacity;
- route execution model.

If Bitget BTC L2 fails, this path is unaffected because Bitget is outside its dependency closure.

Conversely, a `LeadLag:OKX->HL:SOL` path is automatically `BLOCKED_DEPENDENCY` if its required OKX/SOL timing/L2 evidence fails.

Dependency propagation must be deterministic and machine-readable.

### Locality and monotonicity invariants

The gate engine must preserve these properties:

1. **Locality:** failure blocks the smallest safe scope.
2. **Dependency-only propagation:** a failure can block only downstream consumers that depend on it.
3. **Monotonic capability:** adding a new venue, coin, optional model or research feature cannot invalidate a previously certified unrelated path.
4. **Fail-closed evidence:** missing execution-critical evidence cannot be guessed/defaulted inside the affected path.
5. **Graceful degradation:** lower-priority breadth may degrade before Tier-A integrity is sacrificed.
6. **Independent certification:** one healthy route/cohort can finish proof without waiting for unrelated universe-wide perfection.

### Replay-safe intervals versus collection SLOs

Do not confuse **service reliability** with **evidence correctness**.

GitHub-hosted collection cannot realistically have a literal 100% availability SLO.

However, an interval labeled `EXECUTION_REPLAY_SAFE` must have **zero unresolved execution-critical gaps by definition**.

Therefore:

- collector availability/coverage may be <100%;
- gaps may exist globally;
- certified replay-safe intervals exclude unresolved gaps;
- within a certified interval, continuity requirements are exact for the evidence family that requires them.

This preserves scientific strictness without making 100% infrastructure availability a prerequisite.

### Small SLO set

Following SRE principles, the system uses a small number of end-to-end operational SLO families rather than turning all 160 criteria into SLOs.

Core collection SLO families:

1. **liveness/freshness** — required streams and checkpoints arrive within policy;
2. **durability** — sealed segments become durably published within policy;
3. **coverage/completeness** — expected high-priority evidence is observed/certified;
4. **correctness/integrity** — reconciliation, sequence/book and parser validity;
5. **handoff/recovery** — successor overlap/recovery remains within policy.

Tier A receives tighter targets than Tier B/C.

These SLOs guide resource allocation and reliability work. They do not replace per-interval data certification.

### Scoped error budgets

Where an SLO is appropriate, error budgets are scoped to the service/data domain they measure.

Examples:

- Binance BTC Tier-A L2 handoff budget;
- Copy-Vault broad-sweep freshness budget;
- Dataset V2 durable-publication latency budget.

Budget exhaustion triggers the narrowest useful response:

- reduce/split the affected shard;
- promote shadow capture;
- increase checkpoint cadence;
- repair/quarantine affected intervals;
- temporarily reduce Tier-C breadth;
- prioritize reliability work for that scope.

Only a genuine G0/control-plane safety failure causes a global collection stop.

### Aspirational versus blocking targets

Some V4/VNext improvements are aspirational reliability or research targets.

They can be tracked as `MEASURE_ONLY` until enough baseline data exists to set a defensible threshold.

Examples:

- ideal shadow-feed overlap;
- aggressive latency percentile target;
- new experimental SBE path;
- advanced model incremental-value target.

An aspirational SLO becoming temporarily unmet does not invalidate a simpler safe baseline.

Promotion from aspirational to blocking requires:

1. sufficient measurement history;
2. a written threshold;
3. a clear consumer dependency;
4. a defined remediation path.

### Priority-aware graceful degradation

When GitHub runner capacity or API limits are stressed, degrade in this order:

1. preserve G0 safety/control invariants;
2. preserve Tier-A raw capture and timing;
3. preserve evidence required by already-promising module paths;
4. preserve repair/checkpoint durability;
5. reduce Tier-B breadth;
6. reduce Tier-C breadth;
7. defer optional research features.

The system must not protect an optional advanced model by dropping raw evidence required by a simpler profitable baseline.

### Minimal proof paths

Time-to-proof is optimized by certifying the smallest complete economic unit.

Examples:

- Copy-Vault can prove one strong leader cohort without waiting for every public vault to reach identical freshness;
- Lead-Lag can prove Binance->HL BTC in one regime without waiting for all 30 venue-direction combinations;
- Cross-Venue can prove an HL/OKX SOL route without waiting for Gate/Bitget coverage.

Global breadth remains desirable for discovering more edge, but breadth is never a prerequisite for a complete local proof unless the strategy itself mathematically requires that breadth.

### Waiver policy

There are no silent waivers.

- G0 safety criteria: waiver prohibited.
- G2 execution-critical evidence criteria: waiver prohibited for `EXECUTION_REPLAY_SAFE`.
- G3/G5 proof-critical dependencies: waiver prohibited for economic certification.
- optional/advisory criteria may be explicitly marked `NOT_APPLICABLE` or deferred with a recorded reason.

Any allowed temporary waiver must be machine-readable, time-bounded, scoped, and auditable.

### Acceptance dashboard

The dashboard must present gates by scope, not only a giant checklist.

Top-level view:

- global/control health;
- collector SLO health;
- number/duration of replay-safe intervals;
- Copy-Vault ready/provable paths;
- Lead-Lag ready/provable paths;
- Cross-Venue ready/provable paths;
- hypotheses promoted/rejected/pending;
- economic-proof status by module.

Drill-down reveals the exact blocking dependency and remediation action.

### Research basis for gate organization

This architecture is informed by:

- Google SRE guidance to keep a small set of meaningful SLOs, avoid unrealistic 100% service targets, use error budgets for prioritization, and engineer graceful degradation;
- Google SRE data-pipeline guidance on freshness/correctness/completeness, priority tiers, checkpointing and end-to-end pipeline readiness;
- Google SRE cascading-failure guidance to shed lower-priority work and contain failure instead of spreading it;
- continuous-delivery guidance that deployment/readiness gates should be automated and produce explicit evidence;
- NASA-style requirements classification/tailoring and verification traceability, which motivates explicit criticality/scope rather than treating every requirement identically.

These sources guide gate architecture. Alina's own data/economic contracts remain the authority for trading-research certification.


## Tests and acceptance criteria

The following numbered items form the normative acceptance catalog. Each item is enforced according to Acceptance Architecture V2. They do **not** form one global AND-condition unless their gate metadata explicitly says so:

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
15. raw frames are durably representable independent of normalized rows;
16. sealed raw segments are immutable, hashed, and linked to stream/epoch provenance;
17. a runner handoff with overlap deduplicates deterministically without dropping unique events;
18. a runner handoff without proven overlap creates an explicit gap until repaired;
19. a detected L2 sequence discontinuity invalidates book state immediately;
20. a fresh snapshot/resync reopens a new certified interval without retroactively certifying the missing L2 interval;
21. Binance depth synchronization follows snapshot/update-ID bridge rules;
22. Bybit reset/update discontinuity triggers resynchronization and preserves separate matching-engine/gateway timestamps where available;
23. OKX continuity validation uses current sequence semantics rather than relying on deprecated JSON checksum behavior;
24. Gate depth synchronization uses its update IDs and authoritative base/full snapshot semantics;
25. Bitget binary/SBE capture, when enabled, preserves raw binary frames and detects sequence reset/gaps;
26. Hyperliquid reconnects and public snapshots cannot silently bridge missing historical L2 transitions;
27. trade overlap/backfill is deduplicated by authoritative event identity where available;
28. a queue drop, parser loss, or unresolved sequence gap prevents the affected execution-critical interval from becoming `EXECUTION_REPLAY_SAFE`;
29. clock probe freshness/offset/RTT evidence is persisted and timing-sensitive replay rejects intervals that fail timing policy;
30. primary/shadow disagreement is visible and cannot silently pick a winner;
31. Copy-Vault user-specific lanes remain within the official per-IP unique-user ceiling and do not assume every GitHub job has a unique public IP;
32. the broad Copy-Vault universe is not arbitrarily capped before scoring;
33. coverage ledgers identify every attempted venue/instrument/channel and its certified intervals;
34. the replay firewall refuses requests outside certified evidence intervals;
35. Dataset V2 reports unresolved gaps rather than synthesizing BBO/L2 continuity;
36. collection quality scoreboard metrics are generated for each epoch;
37. adaptive sharding reacts to measured queue/processing pressure without silently sacrificing Tier-A evidence;
38. all collection jobs stay bounded for GitHub-hosted execution and can continue through successor units;
39. scheduled triggers are recovery mechanisms, not a correctness dependency;
40. module-specific evidence contracts exist for Copy-Vault, Lead-Lag and Cross-Venue;
41. broad Copy-Vault state sweeps can cover the full frozen universe without requiring one user-specific WebSocket per vault;
42. targeted fill reconciliation is triggered by observed vault activity and remains causal;
43. Lead-Lag/Cross-Venue primary shards preserve same-runner cross-venue monotonic receive ordering;
44. timing-sensitive evidence carries an explicit clock/transport uncertainty bound;
45. Tier-A dual-resolution capture preserves both high-frequency top-of-book timing and deeper capacity where supported;
46. burst capture is causal and cannot backfill pre-trigger microstructure by assumption;
47. official archive repair never upgrades an interval without deterministic validation;
48. zero-cost operation does not depend on requester-pays Hyperliquid historical archives;
49. a COLLECT generation dispatches a successor automatically before its deadline;
50. the successor independently refuses to collect after the phase changes away from COLLECT;
51. the watchdog restores a missing collector generation without requiring user intervention;
52. a COLLECT -> ANALYZE transition disables further relay and causes active collectors to seal and stop cleanly;
53. no current normal COLLECT path creates replay/backtest/PnL campaigns in parallel;
54. the production market universe is not defined by the current fixed 16-coin campaign list;
55. production discovery does not silently truncate the universe through a diagnostic `max_coins` default;
56. the Copy-Vault worker no longer silently converts an intended long unit into an unrelated 300-second sweep;
57. broad Copy-Vault observation and priority user-specific WebSocket observation are independently scheduled;
58. vault freshness/coverage debt is measurable across the complete frozen universe;
59. Binance depth certification validates the official `U/u/pu` bridge and resynchronizes after failure;
60. Bybit full-book certification enforces consecutive `u` while allowing non-consecutive cross-`seq`;
61. Bybit captures separate matching-engine and service timestamps and system-status evidence;
62. OKX certification validates current `seqId/prevSeqId` semantics and does not require deprecated JSON checksum behavior;
63. Gate certification implements documented update-window/base-snapshot semantics rather than a naive integer-gap test;
64. Gate production collection covers execution/context channels required by active modules, not depth alone;
65. Bitget SBE raw frames can be durably captured/decoded/certified for Tier-A streams;
66. Bitget zero-size incremental updates delete levels correctly in fallback JSON book state;
67. Gate and Bitget instrument metadata/rule snapshots are available to economic replay;
68. official Bybit/OKX/Gate/Bitget archive repair paths preserve provenance and cannot silently overwrite live evidence;
69. Hyperliquid zero-cost continuity does not rely on requester-pays archives;
70. module readiness is based on evidence-family completeness rather than only collector-name presence;
71. Tier-A capacity tapes are reproducible from the referenced raw L2 and include VWAP/fill/age provenance;
72. fees and instrument rules used by economic proof have source/effective-time provenance;
73. adaptive tiering protects execution-critical data before lower-priority breadth and records coverage debt;
74. collector liveness is judged from actual data/checkpoint freshness, not only workflow process status;
75. temporary runner/API/publication failures do not require a new user command while phase remains `COLLECT`;
76. the only normal user-controlled stop conditions for autonomous collection are transition to `ANALYZE` or `IDLE`;
77. the canonical first economic milestone is +4 USD net per UTC day per module, not merely +4 USD cumulative;
78. Copy-Vault priority WebSocket leaders use measured observation latency rather than an unconditional 60-second delay;
79. Copy-Vault broad REST candidates retain their actual slower latency class;
80. Copy-Vault leader quality can include market-adjusted forward markout and cross-venue anticipation features without lookahead;
81. reactive leaderboard success alone cannot qualify a leader if copyable forward markout is non-positive after measured delay/costs;
82. Copy-Vault evaluates first-fill, confirmation and continuation entries under frozen policies;
83. Copy-Vault proportional ADD/REDUCE/CLOSE policies are evaluated against the legacy full-exit-on-first-REDUCE benchmark;
84. Copy-Vault dynamic risk budgets can replace crude daily entry caps only when exposure/correlation/capacity are enforced;
85. related/child vaults cannot be counted as independent multi-leader consensus votes;
86. Lead-Lag can build a directed multi-venue leader/lagger graph across all supported venues;
87. Lead-Lag can use a common efficient-price residual plus L2/order-flow/microprice features;
88. Lead-Lag feature layers must demonstrate incremental held-out value over simpler baselines;
89. Lead-Lag thresholds/horizons may adapt to volatility/liquidity state but must be frozen before held-out evaluation;
90. Lead-Lag continuation, reversal and no-trade mechanisms remain distinct auditable hypotheses;
91. Lead-Lag maker execution requires queue-proven fill and adverse-selection evidence;
92. Cross-Venue evaluates every eligible venue pair/direction rather than defaulting to HL/Binance;
93. Cross-Venue supports a unified multi-venue executable book and auditable smart-order-routing experiments;
94. Cross-Venue route value includes fees, spread, slippage, latency, funding where relevant and non-atomic hedge risk;
95. Cross-Venue passive legs cannot generate PnL unless their queue-aware fill is proven;
96. Cross-Venue residual/equilibrium signals distinguish structural venue premia from temporary dislocations;
97. Cross-Venue confirmation wait cost is explicitly measured and immediate-entry policies may compete fairly with persistence policies;
98. fixed 15/25/150 USD diagnostic notionals are not mandatory production sizing;
99. adaptive sizing is capped by approved paper capital, simultaneous L2 capacity, drawdown and concentration;
100. any Kelly-like sizing is fractional/shrunk for parameter uncertainty and cannot override capacity/risk caps;
101. opportunity sizing uses uncertainty-adjusted expected net edge rather than raw in-sample PnL;
102. cross-module allocation cannot double-count correlated opportunities arising from the same market event;
103. module standalone PnL remains separately reportable even when a portfolio allocator is evaluated;
104. research batches freeze hypotheses/feature families/parameter ranges/sizing/route families before held-out evaluation;
105. failed strategy variants remain in the experiment ledger and cannot be silently discarded;
106. previously seen holdout data cannot be reused as a fresh holdout for the same experiment;
107. daily-PnL proof reports gross, fees, slippage, latency/adverse-selection, funding where applicable and net;
108. daily-PnL proof reports executable opportunities/day, filled trades/day, mean/median net per trade and capital utilization;
109. +4 USD/day cannot be certified from one exceptional trade or one positive day;
110. scoreboard includes mean, median and lower-confidence-bound daily net plus positive-day fraction;
111. high-PnL candidates are stress-tested under worse fees, latency, queue position, slippage and capacity before promotion;
112. research-driven improvements may maximize PnL only while paper/read-only and real-order flags remain disabled;
113. liquidation intensity/OI/liquidity state may be evaluated as separate continuation, reversal and no-trade hypotheses;
114. liquidation data cannot be assumed directional without held-out evidence;
115. Lead-Lag may evaluate cross-asset spillovers only with explicit common-factor/beta controls;
116. clock-phase/funding-boundary context can gate or rescale a strategy but cannot create unvalidated PnL by itself;
117. signed markout curves are available for leader quality and execution-toxicity diagnostics;
118. quote-currency/contract normalization prevents USDT/USDC/USD or contract-spec differences from being mislabeled as arbitrage;
119. economic certification is granular and does not require all predeclared coins/routes/leaders to be simultaneously complete;
120. independently certified profitable subsets can contribute to module PnL without waiting for unrelated missing coverage;
121. overlapping variants from the same event cannot be double-counted;
122. ANALYZE may fan out independent frozen partitions across GitHub-hosted runners and deterministically aggregate them;
123. COLLECT may generate deterministic feature tapes but may not use them to tune PnL or inspect held-out outcomes;
124. derived feature tapes are hash-linked to immutable raw evidence;
125. every module maintains an append-only alpha-family registry with explicit economic mechanisms;
126. every candidate reports opportunity density, fill probability, notional and after-cost edge components;
127. research identifies whether time-to-target is limited by opportunity count, raw edge, costs, latency, capacity or sizing;
128. new edge families begin with simple baselines and earn added model complexity only through incremental held-out value;
129. asynchronous lead-lag research can use event-time/Hayashi-Yoshida-style methods without stale-grid interpolation;
130. efficient-price candidates may include robust consensus, VECM/information-share and state-space/Kalman methods under frozen selection;
131. Copy-Vault evaluates anticipatory-wallet, metaorder, specialization, shrinkage-skill, skill-decay, crowding/copyability, execution-skill and exit-skill hypotheses separately;
132. Copy-Vault small-sample leader scores are shrunk and cannot rank purely by raw ROI/PnL;
133. Copy-Vault can detect leader skill change points and demote stale leaders causally;
134. leader popularity/leaderboard rank is not a positive skill prior by itself;
135. Copy-Vault separates follower-reproducible information edge from leader execution edge;
136. behavioral similarity prevents highly correlated leaders from inflating consensus confidence;
137. Lead-Lag compares level-1 OFI, multi-level OFI and integrated/PCA OFI under held-out economics;
138. Lead-Lag can test microprice, queue depletion/refill and multi-level book shape as incremental predictors;
139. Lead-Lag cross-impact models control for own-market flow and common factors and prefer sparse structures;
140. Hawkes/event-intensity features may compete with simpler OFI baselines but cannot bypass held-out proof;
141. Lead-Lag may estimate venue leadership by regime and event-time horizon instead of assuming a permanent leader;
142. Lead-Lag supports continuation, reversal and no-trade probability models for the same shock family;
143. Cross-Venue supports common-price residual and dynamic equilibrium/half-life models;
144. Cross-Venue explicitly models book resilience and transient versus permanent local impact;
145. Cross-Venue unified-book smart routing keeps signal alpha and execution alpha separately attributable;
146. Cross-Venue non-atomic hedge policies include first-leg choice, timeout and emergency-hedge cost;
147. passive route selection uses expected queue value including fill, no-fill opportunity cost and adverse selection;
148. venue reliability may influence route economics when supported by measured execution-quality evidence;
149. all modules can use small frozen regime-policy sets only when regime conditioning improves held-out economics;
150. rejected-opportunity reasons are measured so research targets the real bottleneck to +4 USD/day;
151. capital-efficiency metrics include net dollars per capital, holding time and risk budget;
152. the large edge search is protected by multiple-testing controls such as Reality Check/SPA/DSR/PBO where applicable;
153. overlapping-label folds use purging/embargo or an equivalent leakage-control mechanism;
154. all failed trials remain in the experiment ledger so the effective search count is auditable;
155. a holdout that influences design is burned for that hypothesis lineage and cannot be reused as fresh evidence;
156. edge promotion reports edge half-life, parameter sensitivity and stress-test survival in addition to raw PnL;
157. spectacular in-sample or raw PnL cannot outrank a lower but robust candidate solely on point estimate;
158. external university/practitioner research is used only to generate hypotheses, never as proof that an Alina edge exists;
159. the research curriculum includes microstructure, price discovery, optimal routing, market impact, Hawkes/order flow, Kelly sizing and backtest-overfitting control;
160. every acceptance criterion has explicit gate class, scope, phase, enforcement action and evidence metadata before it can block execution;
161. G0 GLOBAL_FATAL remains a deliberately small safety/control set and cannot absorb ordinary venue/data/research failures;
162. a G2 stream failure blocks only the affected venue/instrument/channel/interval and its actual downstream dependencies;
163. a G3 module-path failure does not block other proof paths in the same module;
164. a G4 research-hypothesis failure cannot disable a simpler healthy baseline;
165. a G5 economic-proof failure blocks only the corresponding module milestone claim and not further collection/research;
166. the gate engine has no generic FAIL_EVERYTHING action outside explicit G0/control semantics;
167. dependency propagation is deterministic and based on a machine-readable capability DAG;
168. adding an optional venue/model/coin cannot invalidate an unrelated previously certified path;
169. replay-safe intervals contain zero unresolved execution-critical gaps even though overall collector availability may be below 100%;
170. operational SLOs are limited to a small end-to-end set for liveness, durability, coverage, correctness and handoff/recovery;
171. SLO/error-budget breaches trigger the narrowest scoped remediation rather than a global stop by default;
172. Tier-A evidence receives stricter operational targets than lower-priority discovery data;
173. aspirational targets remain MEASURE_ONLY until threshold, dependency and remediation policy are explicitly established;
174. resource pressure sheds optional/Tier-C work before execution-critical Tier-A raw evidence;
175. economic proof can complete for the smallest independent complete leader/route/venue-edge unit without unrelated universe-wide readiness;
176. G0 safety and execution-critical replay/proof dependencies cannot be silently waived;
177. any permitted waiver is scoped, time-bounded, machine-readable and auditable;
178. the acceptance dashboard reports exact blocking dependencies by scope instead of only a global pass percentage;
179. acceptance status supports PASS/FAIL/BLOCKED_DEPENDENCY/DEGRADED/REPAIRING/NOT_APPLICABLE/NOT_EVALUATED;
180. a raw pass percentage can never override a critical failed dependency or turn an optional failed hypothesis into a global blocker;
181. each module is represented as an edge portfolio with separately attributable sleeves rather than one monolithic strategy;
182. every edge follows the durable DISCOVERED->BASELINE->TRAIN_CANDIDATE->CHALLENGER->SHADOW->OOS_CANDIDATE->PROMOTED->DECAYING->RETIRED lifecycle;
183. a failed G4 challenger cannot disable an existing healthy champion;
184. promotion requires incremental after-cost value versus the champion/simple baseline, not only standalone positive PnL;
185. effective breadth discounts correlated/overlapping variants and reports independent opportunity breadth separately from raw strategy count;
186. the opportunity funnel records normalized rejection reasons so research can target the dominant bottleneck;
187. Successive-Halving/ASHA/Hyperband-style early elimination, if used, is confined to TRAIN/validation and cannot inspect untouched OOS;
188. low-fidelity research screens can reject candidates but cannot certify economic success;
189. an explicit exploration floor prevents adaptive research/collection priority from permanently starving new coins/leaders/routes/regimes;
190. forecast ensembles must compete against simple equal/shrunk combinations and cannot double-count correlated events;
191. NO_TRADE is a first-class model action when uncertainty-adjusted after-cost edge is insufficient;
192. anytime-valid/sequential monitoring is optional and requires documented validity under the event-dependence structure;
193. change-point/decay detection demotes only the affected edge and cannot globally stop unrelated promoted edges;
194. every paper fill has implementation-shortfall attribution separating signal alpha from execution/sizing effects;
195. adaptive paper sizing may optimize marginal net value only inside certified depth/capacity and risk limits;
196. growth-optimal/fractional-Kelly variants remain G4 and cannot override capital/drawdown/capacity constraints;
197. proof reports effective independent event count in addition to raw fill/trade count;
198. event clustering prevents one metaorder/cascade/common shock from being counted as many independent confirmations;
199. hierarchical/partial-pooling models remain optional challengers and must prove incremental OOS value over entity-specific/simple baselines;
200. Copy-Vault can evaluate wallet-originator networks, conviction surprise, metaorder phase and copyability frontiers as separate G4 hypotheses;
201. Copy-Vault economic admission rejects leaders whose skill is not reproducible after actual follower latency/capacity;
202. Lead-Lag can evaluate microprice leadership, multi-venue consensus/disagreement and response-time hazard models as separate G4 hypotheses;
203. Lead-Lag rejects a signal when expected alpha half-life is not longer than observation/decision/fill latency under the frozen policy;
204. Cross-Venue can run a route auction across eligible venue/order-type routes without double-counting the same dislocation;
205. Cross-Venue marginal split routing stops adding notional when marginal after-cost edge becomes non-positive;
206. Cross-Venue distinguishes stale-quote, local-liquidity-shock, unique-information and structural-basis residual classes before promotion;
207. Cross-Venue resilience-aware waiting competes against immediate entry and explicitly charges lost-alpha waiting cost;
208. collection, research-compute and paper-capital allocation remain three independent control problems with separate state/evidence;
209. fast/medium/slow control loops cannot rewrite historical decisions made by faster causal loops;
210. optimization dashboards expose champion/challenger state, effective breadth, bottlenecks, edge half-life, capital efficiency and next research priority;
211. new Optimization V3 capabilities default to scoped G3/G4/G5 or MEASURE_ONLY enforcement and cannot silently become G0;
212. every module reports raw candidates, unique events, independent opportunities and executable admitted opportunities separately;
213. opportunity counts used for breadth are clustered so execution variants/horizons from one underlying event do not inflate independence;
214. OPPORTUNITY_CONSTRAINED is a diagnostic state and cannot weaken data/execution/economic gates;
215. an opportunity deficit triggers breadth expansion before any consideration of relaxing acceptance criteria;
216. event-driven opportunity generation covers price, OFI, microprice, queue, trade-flow, liquidation, residual and vault-state events where supported;
217. fixed time-grid scanning remains context/validation and is not the sole candidate-generation mechanism;
218. production opportunity generation uses dynamic discovered universes rather than a fixed coin list;
219. Copy-Vault broad REST discovery can generate candidate events from the complete qualifying vault universe without permanent WebSocket coverage;
220. Copy-Vault opportunity cohorts may specialize by coin/direction/horizon/regime/NAV/anticipatory-entry-exit skill while correlated wallets are clustered;
221. Lead-Lag evaluates all data-ready directed venue relationships rather than a single permanent leader venue;
222. with six venues the engine can expose up to 30 directed same-coin venue relationships per compatible coin before regime/horizon expansion;
223. Lead-Lag cross-asset opportunities require explicit common-factor controls and independent-event clustering;
224. venue-consensus/one-lagger events are independently testable hypotheses distinct from single-venue shocks;
225. Cross-Venue opportunity generation covers every data-ready venue pair/direction for a compatible coin;
226. Cross-Venue execution modes and notional ladders do not count as independent alpha events;
227. continuous residual scanning ranks cross-venue candidates by residual, freshness, half-life, capacity and expected after-cost value;
228. near-miss mining records fee/latency/capacity/confidence/data-quality shortfalls without retroactively accepting rejected events;
229. COLLECT may create PnL-free hash-linked opportunity catalogs for later ANALYZE;
230. every opportunity catalog event preserves causal event time, cluster ID and raw/feature evidence references;
231. opportunity clustering accounts for common shock, metaorder, liquidation cascade, residual episode and overlapping holding windows;
232. opportunity-density targets begin as MEASURE_ONLY/productivity objectives rather than evidence-integrity blockers;
233. the optimizer tracks both expected net value per opportunity and effective independent opportunities per day;
234. breadth expansion cannot count duplicated parameter grids, child fills, correlated wallets or adjacent horizons as independent opportunities without evidence;
235. collection/research prioritization may target the opportunity frontier where small measurable improvements would unlock many candidates;
236. the computational universe is dynamically partitioned into COLD/WARM/HOT tiers so expensive processing is bounded;
237. COLD coverage is broad/cheap, WARM performs opportunity detection, and HOT is reserved for execution-grade evidence/evaluation;
238. every large-universe module implements a coarse-to-fine cascade with exact final economic evaluation;
239. approximate top-K/sketch methods, if used, can prioritize work but cannot certify PnL/data continuity/exact execution;
240. exploration quotas protect against permanent false-negative starvation caused by approximate prioritization;
241. fast-path state updates are incremental/keyed and ordinary events do not trigger full-universe rescans;
242. a dirty-set mechanism limits downstream recomputation to keys actually affected by an event;
243. deterministic shared features are computed once and reused across modules where definitions are identical;
244. same-coin venue graphs are materialized only for compatible/data-ready intersections, avoiding unnecessary Cartesian expansion;
245. cross-asset Lead-Lag graphs remain sparse hypothesis graphs rather than all-coins squared;
246. HOT promotions and scarce collection resources can be prioritized by transparent value-of-information/resource-cost heuristics;
247. promotion/demotion uses hysteresis/cooldown to prevent expensive subscription/computation thrashing;
248. runner shard size adapts before queue loss based on measured throughput, lag, memory and checkpoint headroom;
249. overload sheds optional derived/Tier-C work before sacrificing HOT raw execution-critical evidence;
250. any unavoidable execution-critical raw-data loss still quarantines only the affected G2 scope;
251. fast event processing and batch/vector analytical processing are separate execution paths with separate performance objectives;
252. columnar/vectorized derived tapes may be adopted only after reproducible benchmarks demonstrate benefit;
253. event-level receive timestamps/provenance remain intact even when persistence uses micro-batches;
254. successor runners can restore compact keyed-state snapshots plus deltas without replaying an entire collection epoch;
255. derived state snapshots never replace immutable raw evidence as recovery authority;
256. stable metadata/rule/universe caches carry source/effective timestamps and deterministic invalidation;
257. fast-path latency and throughput are measured at socket->WAL->normalize->state->candidate->exact-evaluator boundaries;
258. performance thresholds begin MEASURE_ONLY and become scoped blockers only when a consumer dependency justifies them;
259. cascade Stage-1/Stage-2 recall is audited on TRAIN/validation so compute savings cannot silently eliminate most profitable candidates;
260. untouched OOS cannot be used to tune cascade recall/promote thresholds;
261. resource-efficiency scoreboards report universe tiers, CPU/event, memory/key, events/sec, promotions, compute saved, queue headroom and restore speed;
262. Copy-Vault only targeted-reconciles changed/active vaults while preserving broad cheap awareness of the complete universe;
263. Lead-Lag updates directed relationships only for affected coin/venue keys and promotes shocks to HOT depth evaluation;
264. Cross-Venue runs exact route auctions only on HOT residual/near-miss survivors rather than every possible route continuously;
265. the fast path avoids full-universe rescans and is built around bounded keyed/incremental work per affected event;
266. large-universe candidate ranking uses bounded/sparse top-K style prioritization rather than sorting the complete universe on every event;
267. exact expensive economic evaluation runs only on bounded HOT survivors and remains non-approximate;
268. compatibility graphs prevent accidental all-vault×all-coin, all-coin×all-coin or invalid venue×symbol Cartesian expansion;
269. live per-key state has explicit TTL/compaction and does not retain an entire raw epoch in memory when incremental state is sufficient;
270. deterministic shared transforms are computed once and reused across modules rather than duplicated per strategy implementation;
271. utilization headroom triggers shard split/promotion throttling/deferred low-priority work before queue overflow;
272. cascade recall is measured specifically for eventually executable/profitable candidate classes on TRAIN/validation;
273. specialist high-recall promotion lanes may protect rare edge families from a generic coarse ranking score;
274. every admitted decision can reproduce its raw events, incremental state, feature values, promotion path, exact evaluator inputs and gate outcomes;
275. compact state snapshots accelerate recovery but cannot become opaque authority over immutable raw evidence;
276. implementation preserves Manual Phase Orchestrator, autonomous COLLECT, Collector V4, PnL VNext, Edge Research V2, Acceptance V2, Optimization V3, Opportunity V4, Ultra-Scale V5 and Profitability Convergence V6 as one coherent architecture;
277. optimization conflicts are resolved by preserving safety/causality/raw provenance/exact economics before optional breadth or complexity;
278. no implementation task may remove a previously validated architecture layer merely to simplify local code;
279. existing relevant campaign, dataset, reconciliation, collector and strategy tests continue to pass;
280. Profitability Convergence V6 treats +4 USD net/day as a proof target and research-allocation milestone, never as a guaranteed outcome;
281. every serious edge sleeve reports conservative net USD/day, effective independent opportunities/day, fill probability, capacity and the dominant economic bottleneck;
282. research prioritization may use expected target-gap reduction on TRAIN/validation but cannot inspect untouched OOS/forward outcomes to tune that priority;
283. the shared Execution Alpha Core evaluates taker, maker, maker-timeout, causal-wait, alternate-route, split-route and NO_TRADE policies on the same causal decision state where applicable;
284. maker execution receives no economic credit from fee savings alone; fill probability and adverse selection are mandatory;
285. signal alpha and execution alpha/cost are reported separately for every promoted module;
286. a route whose total observation/decision/fill latency exhausts the estimated alpha half-life is rejected or routed to a faster admissible policy;
287. standalone OFI/microprice/book-imbalance ideas previously killed at measured cadence cannot be silently promoted as strategy alpha and may be reused only as new preregistered execution/regime features unless they independently re-prove net edge;
288. Forced-Flow/Liquidation V2 uses a high-leverage/vulnerable-position universe distinct from the smart-wallet discovery universe;
289. liquidation-threshold density and forced-notional/depth metrics distinguish measured state from inferred state and preserve provenance/confidence;
290. liquidation research clusters one cascade into effective events and cannot count child liquidations as independent proof;
291. Forced-Flow tests continuation, absorption, exhaustion/reversal and propagation as separate hypotheses rather than hard-coding one liquidation direction;
292. Scheduled Flow/TWAP research records parent-program fields only when they are publicly/read-only observable; unavailable parent state remains UNMEASURABLE rather than inferred as fact;
293. TWAP slice fills are joined by stable TWAP identity and replayed causally with activation/progress/completion state where evidence permits;
294. visible TWAP flow is not assumed informed or front-runnable; continuation, absorption, execution-avoidance and post-completion decay compete as separate hypotheses;
295. periodic/clock-time hypotheses require preregistration, boundary-versus-placebo comparison and after-cost OOS proof;
296. Medium-Horizon Trend/Breakout is a materially different hypothesis family from previously killed residual momentum and must use explicit turnover/friction controls;
297. dynamic-universe trend research prevents survivorship bias and records the contemporaneous eligible universe;
298. Cross-Instrument Relative Value uses executable prices and explicit costs/capacity on every leg;
299. no one-leg unhedged carry can be labeled arbitrage or promoted as relative value;
300. funding-adjusted/statistical residual models must beat raw-spread/simple baselines OOS and cannot substitute stationarity for executable profitability;
301. Options/Volatility Intelligence is initially a shared conditioning layer, not a hard dependency and not an automatically tradable module;
302. options-derived predictors require recent decay monitoring and incremental OOS value because published predictability is documented as regime-dependent;
303. previously killed naive mean reversion, residual-momentum, unhedged funding, fee-only market making and mid-only cross-venue variants remain behind a kill-resurrection firewall;
304. a killed idea may return only through a materially different preregistered mechanism/data resolution/execution regime/horizon, with the prior verdict retained in the experiment ledger;
305. current core modules remain Copy-Vault, Lead-Lag and Cross-Venue until candidate modules independently clear scoped promotion gates;
306. Forced-Flow, Scheduled Flow, Medium-Horizon Trend and Cross-Instrument Relative Value enter as first-class candidate modules/sleeves without becoming global blockers;
307. candidate-module promotion requires certified evidence, causal TRAIN/validation, frozen untouched OOS, required forward/shadow confirmation, positive after-cost net edge, sufficient effective sample, meaningful capacity and target-gap improvement;
308. module comparison optimizes net edge × independent frequency × fill × capacity under drawdown/uncertainty, not win rate or signal count alone;
309. opportunity research gives preference to mechanisms whose plausible gross amplitude can clear realistic friction, while preserving an explicit exploration floor for new mechanisms;
310. external papers, third-party APIs and public market studies can generate hypotheses but cannot certify an Alina edge or override paper-only safety.

## Non-goals

This change does not:

- create an Oracle/VPS collector;
- run anything on the user's PC;
- enable real trading;
- guarantee a 4 USD profit;
- activate candidate V6 modules without scoped evidence gates;
- resurrect previously killed strategies without a materially new preregistered hypothesis;
- remove historical campaign evidence;
- replace existing native venue collectors without a demonstrated need.

Its purpose is to make the existing GitHub architecture operationally simple: collect when instructed, stop cleanly when instructed, then spend compute on evidence generation instead of competing workloads.
