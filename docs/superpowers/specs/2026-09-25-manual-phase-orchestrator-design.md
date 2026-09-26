# Manual Phase Orchestrator Design

## Objective

Replace the current mixed continuous campaign behavior with one explicit, versioned operating phase for Alina Smart Flow on GitHub:

- `IDLE`: no new heavy work starts.
- `COLLECT`: only data-collection work is created and scheduled.
- `ANALYZE`: collection drains, then quality checks, replay, backtests, module PnL proof, and scoreboard run without starting new collection windows.

The user controls phase changes manually through ChatGPT/GitHub. Autonomous runtime, collection, orchestration, and cloud analysis use GitHub-hosted runners only: no self-hosted runner and no workflow may wake, commandeer, or depend on the user's PC. Separately, when the user explicitly launches Codex or another coding agent inside a local checkout, deterministic development tests, replays, backtests, linting, static analysis, and other CPU-heavy verification should run locally as much as practical to minimize model quota and unnecessary GitHub Actions usage.

The design must preserve strict paper/read-only behavior and must never enable real orders.

## Canonical-spec governance

This file is the **single canonical specification** for the current Alina Smart Flow design.

Rules:

- research updates this file in place; it does not create a new specification file merely because new evidence was found;
- historical labels such as `V6.x` inside older sections are retained only as research-tranche/change-history markers and **must not be interpreted as separate specs**;
- do not create `V6.25`, `V6.26`, etc. sections as a default research workflow;
- new verified evidence is integrated into the relevant functional section and the canonical acceptance catalog below;
- create a genuinely new spec only if the user explicitly requests a separate design or the architecture changes incompatibly enough to require one;
- duplicated requirements are merged instead of appended under another version label;
- where first-party sources conflict, preserve the conflict and fail closed rather than spawning another spec version to paper over it.

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
- **Profitability Convergence V6:** friction-first module expansion, execution alpha, forced/scheduled flow, slow trend/relative-value research and an explicit economic-distance-to-+4-USD/day scheduler;
- **Execution Truth V6.3:** queue/latency uncertainty, partial-fill accounting, priority-fee economics, dynamic venue-cost/state, liquidation-route semantics and adversarial backtest-integrity certification;
- **Portfolio Intent & Latent Flow V6.4:** cross-module intent netting, trigger-flow coverage, replenishment/absorption intelligence and capacity-aware adaptive execution;
- **Venue Microstructure V6.5:** venue-class-aware collection/routing across visible CLOB, hidden-liquidity, RFQ and native multi-leg markets with fee-latency/account-tier economics;
- **Selective L4 & Backstop Intelligence V6.6:** event-window order-level truth, L2 queue calibration without live probing, and post-backstop inventory/unwind research;
- **Outcome Relative Value V6.7:** HIP-4 internal parity, cross-venue event equivalence and outcome↔perp/options relative-value research under settlement-semantic certification;
- **Rule & Coverage Completeness V6.8:** point-in-time venue validity, rejection semantics, history/coverage bounds and observable-state certification;
- **Protocol Mechanics V6.9:** OI-cap, exact funding, margin/liquidation, TWAP/Chase provenance and protocol-rule edge cases;
- **Options Volatility Relative Value V6.10:** direct options-volatility sleeves, transaction-cost-aware delta hedging and executable vol-surface research;
- **Event Identity & Feed Semantics V6.11:** source-native event identity, sweep de-fragmentation, idempotency, venue-specific continuity and timing uncertainty;
- **Lifecycle & Reference Integrity V6.12:** RWA calendar/corporate-action/reference-source, expiry/roll, funding-boundary and account-lineage correctness;
- **Market-Rule Edge-Case Closure V6.13:** self-trade expire-maker, TP/SL child lifecycle, native-TWAP catch-up, batch/modify/cancel semantics, throughput limits and funding/mark finality;
- **Exact Cost & Reference Semantics V6.14:** placement-charged ALO priority economics, point-in-time fee-tier state, funding/oracle notional exactness, allMids fallback provenance and final reference-price/accounting closure;
- **Exact Protocol Constants & Accounting V6.15:** versioned numeric contract constants, precise mark/oracle construction, action/open-order feasibility, Chase/TWAP frontend semantics, liquidation thresholds, Hyperp caps and fill-ledger PnL/margin closure.
- **Liquidation, Margin & Trigger Exactness V6.16:** exact backstop threshold/transfer, cross-vs-isolated margin state, TP/SL child lifecycle and funding-transfer accounting.
- **Portfolio-Margin, Delisting & Accounting Exactness V6.17:** exact account-abstraction limits, borrow/LTV/liquidation state, delisting settlement and spot/perp accounting provenance.
- **ADL Exactness V6.18:** exact auto-deleveraging trigger, ranking index, previous-mark execution and queue semantics.
- **AMM-Oracle & Formula-Index Relative Value V6.19:** Uniswap-oracle perp basis, delta-neutral LP hedging and formula/index-perp reconstruction under executable AMM costs.
- **Priority / Transport Exactness V6.20:** exact IOC/ALO/gossip priority economics, GitHub-hosted latency boundary, SDK market-order protection and transport-feasibility semantics;
- **Frontend Analytics Non-Authority V6.21:** portfolio-graph sampling and UI drawdown are reconciliation views only, never proof-ledger truth.
- **Fill / WebSocket / Reconciliation Exactness V6.22:** raw fill granularity, fee-component reconciliation, snapshot/reconnect idempotency, CLOID/OID state repair and stream-feasibility exactness;

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


### Profitability Convergence V6.1 — empirically hardened research order

A second external-research pass on 2026-09-25 refines V6 from a broad candidate set into an explicit **research order**.

This order is a scheduling policy for scarce compute/data effort. It is **not** a claim that a later item has lower eventual profitability.

Current priority:

1. **P0 — Shared Execution Alpha Core**
2. **P1A — Scheduled Flow / Native TWAP & Metaorder**
3. **P1B — Forced-Flow / Liquidation V2**
4. **P2 — Cross-Instrument Relative Value**
5. **P3 — Medium-Horizon Trend / Breakout**
6. **always-on shared context — Options / Volatility Intelligence**

Rationale:

- Execution Alpha can improve every existing and future module and directly attacks Alina's repeatedly measured friction bottleneck.
- Scheduled Flow has unusually rich Hyperliquid-native observability and high event frequency, making it fast to falsify and potentially compatible with a daily PnL objective.
- Forced-Flow offers potentially much larger amplitude but is more episodic and event-heterogeneous.
- Relative Value can produce structurally larger spreads than micro-signals, but margin, collateral fragmentation and liquidation risk can dominate nominal convergence.
- Trend can survive larger horizons and lower turnover, but must justify capital-time usage and avoid resurrecting killed short-horizon momentum variants.
- Options features are forward-looking but empirically regime-dependent; they should improve timing/regime classification before they consume standalone strategy budget.

The scheduler may change this order only from Alina evidence such as gate-clearing speed, target-gap reduction, event frequency, capacity or clear falsification.

#### P0 experiment card — Execution Alpha

Execution research must be performed as **paired counterfactual execution** on the same admitted opportunity whenever evidence permits.

For each opportunity, record the counterfactual outcome of:

- immediate taker;
- maker at touch;
- maker one tick/depth level away where valid;
- maker with timeout;
- maker -> taker fallback;
- causal wait;
- alternate venue;
- split route;
- no-trade.

Required measurements include:

- queue ahead at submission;
- estimated queue position/priority where reconstructable;
- queue evolution while resting;
- fill probability;
- conditional fill time;
- cancel/repost count;
- spread captured/paid;
- fee/rebate;
- post-fill markout at multiple horizons such as 100 ms, 1 s, 5 s, 10 s and longer where the feed resolution supports them;
- implementation shortfall versus decision mid and versus executable immediate-taker baseline;
- adverse-selection cost conditional on fill;
- missed-alpha cost conditional on non-fill;
- residual alpha half-life at fill time.

The core maker diagnostic is explicitly two-dimensional:

```text
maker_value
= fill_probability
  * expected_post_fill_value
  - non_fill_opportunity_cost
  - cancellation/repost_cost
```

A maker policy cannot be promoted from unconditional average markout alone.

The live-experiment literature shows a fundamental negative relationship between maker fill likelihood and post-fill returns. Therefore:

- high fill rate is not automatically good;
- good post-fill markout with near-zero fill rate is not automatically useful;
- queue state, side-relative imbalance and cancellation policy are first-class features;
- a maker signal may legitimately be contrarian to instantaneous book imbalance if that is what survives OOS after the fill/no-fill trade-off;
- synthetic back-of-queue simulation must be labeled pessimistic and cannot stand in for real queue-priority evidence when production claims are made.

**Execution Alpha success criterion:** statistically and economically improve conservative after-cost USD/day of at least one already-admissible edge sleeve versus both immediate-taker and naive-maker baselines on frozen OOS/forward evidence.

#### P1A experiment card — Scheduled Flow / Native TWAP & Metaorder

Research must distinguish:

- protocol-native announced TWAP;
- latent/statistically reconstructed metaorder;
- ordinary isolated flow.

For an observable native TWAP parent program, capture:

- activation timestamp;
- side;
- coin;
- total parent size;
- configured duration;
- child cadence;
- executed size/notional;
- remaining size/notional;
- completion/cancel/terminate state;
- participation rate versus concurrent market volume;
- parent size normalized by daily/rolling traded volume;
- parent size normalized by volatility;
- same-side and opposite-side active TWAP dominance;
- concurrent hidden/metaorder flow when measurable.

Study the price/book path in separate causal windows:

`PRE_ACTIVATION -> ACTIVE_EARLY -> ACTIVE_MID -> ACTIVE_LATE -> COMPLETION -> POST_COMPLETION_DECAY`.

The primary hypotheses are intentionally competing:

1. **continuation:** remaining scheduled aggressive flow predicts same-direction price pressure;
2. **absorption:** visible flow attracts enough liquidity that directionality weakens while depth grows;
3. **avoidance/execution-alpha:** a strategy with an existing trade reason improves execution by not crossing against adverse scheduled flow;
4. **completion decay:** transient TWAP impact partially reverts after completion;
5. **interaction:** hidden/metaorder flow aligned with visible TWAP dominance has different markout/adverse-selection economics.

External Hyperliquid research reports that, conditional on execution characteristics:

- visible TWAPs have about **9 bps lower temporary impact** than comparable latent metaorders;
- they leave about **5 bps less post-completion displacement**;
- hidden metaorders trading with stronger same-direction visible TWAP dominance incur additional post-execution displacement;
- displayed depth rises and the book tilts toward the absorbing side while visible TWAPs are active.

These numbers are **research priors only**, never Alina PnL inputs.

Alina must estimate its own effect sizes by coin, size bucket, participation rate, volatility regime and phase of the parent program.

**Scheduled-Flow success criterion:** demonstrate an incremental after-cost OOS improvement over the same strategy without TWAP state, either as standalone scheduled-flow alpha or as execution/timing improvement.

#### P1B experiment card — Forced-Flow / Liquidation V2

Forced-flow research prioritizes **mechanism state** over generic crash prediction.

Maintain event-level diagnostics such as:

- vulnerable-notional density around current price;
- liquidation distance distribution;
- executable depth to vulnerable levels;
- quoted/realized price-impact state versus calm baseline;
- open-interest clearing fraction;
- forced-flow share of aggressor flow where identifiable;
- market-wide correlation/dispersion shift;
- cross-venue impact disagreement;
- cross-asset propagation;
- recovery speed of spread, depth and impact.

Recent large-cascade research finds that:

- impact can rise by multiples during cascades;
- Hyperliquid open interest can clear by roughly **45–70%** in major events;
- the largest observed cascade was strongly front-loaded rather than a slow near-critical chain reaction;
- venue backstop/absorption can materially suppress order-book propagation;
- no single pre-cascade state variable is reliably event-invariant.

Therefore:

- do not optimize for a universal "predict the crash" classifier;
- split endogenous-buildup events from exogenous-shock events;
- separate pre-event vulnerability, in-event continuation, absorption and post-event recovery;
- treat backstop/forced-flow off-book absorption as a distinct mechanism when observable;
- evaluate propagation edges on a graph of coins/venues instead of assuming same-coin-only effects.

**Forced-Flow success criterion:** at least one state-conditioned sleeve shows executable after-cost OOS edge with enough independent events and capacity to contribute materially to the daily target; otherwise the module remains a regime/risk layer.

#### P2 experiment card — Cross-Instrument Relative Value

Relative Value must optimize **return on margin and capital fragmentation**, not nominal spread.

For every route, decompose PnL into:

```text
basis_or_residual_convergence
+ funding_carry
+ fee_or_rebate
- entry_execution_cost
- exit_execution_cost
- hedge_error
- rebalancing_cost
- margin/liquidation_loss_expectation
- venue/settlement_risk_haircut
- capital_fragmentation_cost
- capital_time_opportunity_cost
```

Track per-leg:

- margin model;
- cross-margin availability;
- maintenance margin;
- liquidation distance;
- mark-price definition;
- collateral asset;
- funding settlement convention;
- funding-rate history;
- borrow/spot custody requirement;
- transfer/settlement dependency;
- executable entry/exit depth.

Research on crypto carry shows why this is mandatory: apparently convergent cash-and-carry positions can be liquidated **before** convergence when the short futures leg suffers adverse mark-to-market movement and capital cannot be cross-margined.

A historical paper found the basis stronger than momentum in the cross section and robust to a small transaction-cost assumption, but Alina must not import that historical return or cost regime.

Relative Value challengers should be tested in increasing complexity:

1. executable raw basis;
2. funding-adjusted basis;
3. volatility/liquidity-normalized residual;
4. rolling stationary/cointegrated residual;
5. multi-venue route portfolio.

Complex statistical models are accepted only if they improve frozen OOS economics over simpler executable baselines.

**Relative-Value success criterion:** positive conservative after-cost return on margin after stress-testing margin expansion, funding compression, leg slippage and forced-close scenarios.

#### P3 experiment card — Medium-Horizon Trend / Breakout

Trend research begins with simple interpretable baselines before ML ensembles.

Baseline family:

- own-asset return sign/trend over multiple lookbacks;
- breakout/range expansion;
- price + volume confirmation;
- volatility expansion;
- open-interest confirmation;
- multi-venue confirmation.

Only after simple baselines are frozen may a CTREND-style ensemble aggregate broader technical features.

Candidate horizons may extend beyond the current intraday set when capital-time efficiency supports it, including 1 day, several days and multi-week challengers.

This is justified because peer-reviewed CTREND evidence reports that multi-horizon price/volume trend information survives transaction-cost tests, remains present in large/liquid coins, and can persist at longer holding periods. Those historical results are not sufficient for Alina promotion.

Required safeguards:

- contemporaneous dynamic universe;
- delisting/new-listing handling;
- no survivorship filter;
- explicit turnover penalty;
- capacity by coin;
- funding/short-leg cost where relevant;
- market-beta and common-factor attribution;
- regime/dispersion breakdown;
- capital-time efficiency versus faster modules.

**Trend success criterion:** a simple or ensemble trend sleeve produces positive after-cost frozen-OOS economics that remain useful after dividing PnL by capital-time consumed.

#### Options / Volatility Intelligence empirical contract

Options remain a shared intelligence layer unless standalone trading is separately specified later.

Prioritize features with explicit tenor/delta definitions:

- 25-delta risk reversal at 30d/60d/90d/180d where liquid;
- 10-delta tail skew where reliable;
- butterfly;
- ATM IV level;
- front/back term-structure slope;
- term-structure inversion;
- IV minus realized volatility;
- skew change/shock;
- option-implied jump/tail-risk state.

The 2026 Bitcoin risk-reversal study used 1,723 daily Deribit observations through December 2025 and found strongest return predictability in roughly the 30–180 day maturity region, concentrated mainly in the next day and persisting over several days. It also found a structural weakening after January 2024.

Therefore every options feature carries:

- rolling recent-effect estimate;
- decay/drift score;
- stale-surface flag;
- liquidity/quote-quality score;
- incremental-value test against a no-options baseline.

No historical coefficient is copied into Alina.

**Options-layer success criterion:** improve calibration, rejection, sizing, regime routing or after-cost PnL of another module on frozen OOS; otherwise remain informational only.

#### Cross-module convergence tests

Because the six priorities can overlap economically, V6.1 requires explicit attribution.

For each admitted trade/opportunity, record which layer contributed:

- raw economic edge;
- TWAP/scheduled-flow context;
- forced-flow context;
- options context;
- execution policy;
- relative-value hedge structure;
- trend/regime state.

Run ablations:

- full model;
- remove execution alpha;
- remove scheduled flow;
- remove forced flow;
- remove options context;
- remove regime/trend context.

A new layer is retained only when its incremental contribution survives OOS uncertainty and is not merely duplicating another feature family.

#### Daily-target research scoreboard

Maintain a dedicated V6.1 scoreboard:

| lane | independent events/day | gross bps | cost bps | fill rate | net USD/day LCB | capacity USD | capital-time | evidence state | target-gap contribution |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| execution alpha | | | | | | | | | |
| scheduled flow | | | | | | | | | |
| forced flow | | | | | | | | | |
| relative value | | | | | | | | | |
| trend | | | | | | | | | |
| options incremental | | | | | | | | | |

The scoreboard is allowed to say `UNMEASURABLE`, `KILL`, `SHADOW` or `PROMOTE`.

It is not allowed to fill missing data with assumptions just to compute progress toward 4 USD/day.



### Profitability Convergence V6.2 — public-bot intelligence and market-structure expansion

A third research pass on 2026-09-25 examined public crypto-perpetual bot ecosystems exposed through X/Twitter, GitHub repositories and mature open-source frameworks.

The objective is **not** to copy public bots or trust public performance claims. The objective is to use them as a systematic source of candidate mechanisms, execution patterns and market-structure observations that Alina may have missed.

V6.2 adds four genuinely distinct research families:

1. **Cross-Exchange Hedged Market Making (XEMM)**;
2. **HIP-3 / RWA Session & Reopen Edge**;
3. **Builder / Frontend / Participant-Flow Provenance**;
4. **Hyperp / Pre-Launch Relative Value**;

and strengthens the shared Execution Alpha Core with:

- volume-clock / VPIN-lite style flow state;
- side-specific toxicity;
- fill-burst detection;
- shock-chain detection;
- wall/depth quality;
- inventory half-life;
- API/data-budget value allocation.

These are research additions only. None enable real trading, none override existing kill verdicts, and none become global blockers.

#### Public Bot Intelligence Program

Maintain a structured registry of externally discovered bot/research ideas.

Each registry row records:

- source type: `X / GitHub / paper / official docs / framework`;
- source URL/repository;
- observed date;
- project/repository revision when available;
- claimed strategy/module;
- actual code path or documentation supporting the claim;
- license;
- maintenance/activity signal;
- whether the mechanism is already present in Alina;
- economic mechanism category;
- required data;
- required latency;
- expected turnover;
- likely dominant friction;
- falsification test;
- Alina research lane;
- disposition: `DUPLICATE / WATCH / PREREGISTER / TEST / KILL / PROMOTE`.

Rules:

- public PnL/APR claims are treated as **unverified claims**;
- X engagement, star count and marketing language are never evidence of edge;
- source code is inspected for mechanism, not assumed profitable because it is open source;
- code may not be copied into Alina without license compatibility and provenance review;
- prefer independent reimplementation from the economic idea where practical;
- every imported idea must pass the same causal data, cost, OOS and forward gates as an internally generated idea;
- external findings cannot override Alina safety, paper-only, causality or kill-resurrection rules;
- duplicate ideas are linked to the existing Alina experiment rather than creating parallel implementations.

This program is allowed to continuously improve the hypothesis backlog while keeping the HOT execution/replay path independent of social-media availability.

### P0B — Cross-Exchange Hedged Market Making (XEMM)

XEMM is a separate mechanism from both naive market making and taker-taker cross-venue arbitrage.

The core pattern is:

```text
liquid/reference venue
    -> executable hedge VWAP / fair-value envelope
    -> passive maker quote on a second venue
    -> maker fill
    -> immediate opposite hedge on reference venue
```

The economic objective is to **create** an executable spread rather than wait for a naturally occurring taker-taker dislocation.

For a candidate maker buy:

```text
max_maker_buy_px
= expected_executable_taker_sell_px
  - required_profit_buffer
  - maker_fee_or_rebate_adjustment
  - expected_hedge_slippage
  - hedge_latency_risk
  - adverse_selection_buffer
  - uncertainty_buffer
```

For a candidate maker sell, use the symmetric construction.

Required state:

- maker venue BBO/L2;
- hedge venue executable VWAP for the full candidate size;
- maker fee/rebate;
- taker hedge fee;
- maker queue/fill probability;
- hedge latency;
- hedge depth;
- hedge slippage;
- maker-side adverse-selection markout;
- inventory accumulated from partial maker fills;
- per-venue collateral/balance/margin availability;
- conversion/oracle rate if maker and hedge instruments are not denominated identically;
- stale-quote age;
- current alpha/fair-value half-life.

Research variants:

- Hyperliquid maker -> Binance/OKX/Bybit hedge;
- secondary perp venue maker -> Hyperliquid hedge;
- HIP-3 maker -> external reference venue hedge while that venue is open;
- maker quote conditioned by Lead-Lag price discovery;
- maker quote conditioned by Scheduled Flow/TWAP or toxicity state;
- multi-hedge-venue auction selecting the cheapest executable hedge path.

The paper simulator must reproduce the sequence causally:

1. compute hedgeable size and maker quote from information available at time `t`;
2. place a simulated passive order with queue assumptions recorded;
3. determine if/when the maker order fills from future tape without lookahead;
4. only after the simulated maker fill timestamp, price the hedge using the then-observable hedge venue book plus modeled latency;
5. charge all fees, slippage, partial-fill and residual-inventory costs.

Do **not** credit the quote with the hedge price observed before the maker fill.

XEMM failure modes to measure explicitly:

- maker fill occurs exactly when reference price moves adversely;
- hedge book disappears between quote and fill;
- partial maker fill creates awkward hedge size;
- repeated cancel/requote loses queue priority;
- stale reference feed;
- maker/taker collateral fragmentation;
- cross-venue mark/oracle divergence;
- hedge venue outage;
- asymmetric fee/funding regimes;
- inventory drift after failed hedge.

**XEMM success criterion:** conservative frozen-OOS/forward net USD/day improves materially over both:
- taker-taker Cross-Venue for the same economic relationship;
- naive passive market making without external hedge pricing.

If XEMM fails standalone but improves execution for Cross-Venue/Relative Value, retain it as an execution sleeve rather than a production module.

### Execution Alpha additions from public bot architectures

V6.2 adds the following candidate state variables to the shared Execution Alpha Core.

#### Volume-clock / VPIN-lite state

Maintain event/volume buckets in addition to wall-clock windows.

Example:

```text
signed_volume_bucket
= aggressive_buy_volume - aggressive_sell_volume
```

Track:

- normalized signed volume;
- bucket fill time;
- volume acceleration;
- imbalance persistence;
- toxicity following extreme buckets;
- divergence between wall-clock and volume-clock state.

The purpose is not to promote VPIN as a standalone strategy. It is to distinguish a quiet 5-second interval from a shock interval containing orders of magnitude more traded notional.

#### Side-specific toxicity

Maintain bid-side and ask-side post-fill markout distributions separately.

Use multi-horizon markouts and decay to estimate:

- maker-buy toxicity;
- maker-sell toxicity;
- fill-conditioned adverse selection;
- toxicity by volatility regime;
- toxicity by venue;
- toxicity by flow provenance;
- toxicity by TWAP/forced-flow/session state.

A symmetric toxicity score is insufficient when one side of the book is being repeatedly informed.

#### Fill-burst and shock-chain state

Detect clusters of rapid fills and sequential market shocks.

Candidate diagnostics:

- fills per rolling short horizon;
- successive same-side fills;
- successive depth depletion;
- repeated cross-venue mid jumps;
- cascading spread widening;
- OI/liquidation confirmation;
- recovery time.

A fill burst may trigger:

- quote widening;
- size reduction;
- temporary passive-side suppression;
- XEMM hedge urgency;
- promotion of the event to Forced-Flow analysis.

#### Wall/depth quality

A large resting wall is not automatically trusted.

Track:

- persistence;
- refill behavior;
- cancellation-before-touch;
- distance from BBO;
- side imbalance;
- venue consistency;
- execution actually obtained in front of/through the wall.

Wall information may condition execution but cannot be called support/resistance without OOS proof.

#### Inventory half-life

For every passive/XEMM sleeve, estimate:

```text
inventory_half_life
= expected time required for the strategy to reduce half of undesired inventory
```

Inventory control should react to:

- utilization;
- toxicity;
- expected liquidation/margin risk;
- expected hedgeability;
- regime;
- capital-time opportunity cost.

#### API/data budget by research value

When venue/API limits bind, allocate optional refresh/query budget by marginal research/execution value rather than uniformly.

Protect in order:

1. raw Tier-A/HOT evidence;
2. safety/reconciliation;
3. currently admitted opportunities;
4. high-value WARM challengers;
5. COLD discovery.

This extends Ultra-Scale V5 value-of-information scheduling to API/request budgets.

### Candidate Module 8 — HIP-3 / RWA Session & Reopen Edge

HIP-3 builder-deployed perpetuals require an explicit session model because many reference underlyings are not continuously tradable even though Hyperliquid is.

For each HIP-3 instrument, maintain a versioned market/session contract:

- deployer/DEX;
- underlying/reference asset;
- collateral token;
- margin mode;
- maximum leverage;
- oracle definition;
- external reference venue(s);
- reference market timezone/calendar;
- regular session;
- pre/post session where relevant;
- holiday calendar;
- `EXTERNAL_REFERENCE_ACTIVE` vs `INTERNAL_PRICE_DISCOVERY`;
- reopen timestamp;
- funding configuration;
- configured price/bounding constraints where known;
- oracle/mark/external-perp-price provenance;
- contract/config revision.

The module must distinguish at least:

```text
EXTERNAL_SESSION
-> external venue live
-> cross-venue price-discovery / XEMM / basis hypotheses eligible

CLOSURE_TRANSITION
-> external venue closes
-> participant mix and hedgeability change

INTERNAL_SESSION
-> Hyperliquid remains live
-> own-market price discovery dominates
-> external hedge path may disappear

REOPEN_APPROACH
-> external indicative/reference information may return
-> convergence hazard rises

REOPEN
-> external reference becomes executable again
-> re-anchoring / convergence dynamics measured
```

External analyses found substantial weekend price discovery in HIP-3/RWA markets, but Alina treats those statistics as hypothesis priors only.

Independent sleeves to test:

- **off-hours information discovery:** whether HIP-3 moves predict subsequent external reopen beyond simple Friday-close and news/regime baselines;
- **reopen convergence:** residual between HIP-3 internal price and the newly reopened external market;
- **session-switch Lead-Lag:** which venue becomes price leader before/after external open;
- **session-switch XEMM:** maker/hedge economics when external hedge venue becomes available;
- **weekend liquidity premium:** spread/depth/impact compensation during internal sessions;
- **boundary/band pressure:** behavior when internal prices approach protocol/deployer bounds;
- **cross-deployer same-underlying relative value:** e.g. multiple HIP-3 contracts referencing similar silver/equity/commodity exposure;
- **participant-mix-conditioned execution:** execution policy changes when retail/stat-arb/MM composition shifts.

Critical safeguards:

- never assume the weekend price equals fair value;
- no external reference is considered executable while its market is closed;
- reopen tests use the exact venue calendar and holiday schedule available at decision time;
- transaction costs and weekend tail depth are measured from actual books;
- external session/open times are versioned data, not hard-coded forever;
- contract/deployer/oracle specification changes invalidate incompatible historical comparisons;
- RWA-specific news may create genuine jumps and is not treated as mean-reverting noise.

**HIP-3 success criterion:** one session-conditioned sleeve shows incremental after-cost OOS value versus the equivalent strategy without session state, with enough events/capacity to matter toward the daily target.

### Shared Builder / Frontend / Participant-Flow Provenance Layer

Hyperliquid builder codes and order metadata can expose **how** some flow reached the venue.

Official builder-code infrastructure is per-order and public builder fill archives exist for known builder addresses.

Alina may construct a point-in-time flow-provenance layer using only public/replayable market data.

Potential provenance signals include:

- builder address;
- builder fee;
- builder category when independently documented;
- direct API vs known builder route;
- `FrontendMarket`-style order metadata when available;
- IOC/post-only/GTC mix;
- maker/taker ratio;
- order-to-fill ratio;
- cancellation ratio;
- fill frequency;
- temporal clustering;
- average size/notional;
- cross-deployer activity;
- cross-venue activity where public linkage is defensible.

Behavior classes are probabilistic research labels, e.g.:

- `LIKELY_RETAIL_FLOW`;
- `LIKELY_MARKET_MAKER`;
- `LIKELY_STAT_ARB_TAKER`;
- `LIKELY_ROUTER_OR_TERMINAL`;
- `UNCLASSIFIED`.

Requirements:

- classification confidence and evidence must be stored;
- `UNCLASSIFIED` is a valid dominant state;
- builder identity does not imply trader identity;
- no deanonymization, real-world identity inference or personal-profile enrichment;
- wallet-level behavior labels are market-structure features, not claims about a person;
- a paid builder route is not automatically retail;
- direct API is not automatically sophisticated/informed;
- limit-order-only humans may be indistinguishable from bots and must remain uncertain;
- classifier definitions are frozen before OOS evaluation.

Use cases:

- condition Copy-Vault copyability on leader execution channel;
- condition Lead-Lag on retail vs algorithmic flow bursts;
- detect disappearance of stat-arb flow during external-market closures;
- estimate adverse selection by flow category;
- identify when a builder/router concentration shift changes execution quality;
- improve XEMM quote width/size based on toxicity of current incoming flow.

**Flow-provenance success criterion:** the provenance layer adds incremental OOS calibration or after-cost value over simpler wallet/market features; otherwise it remains descriptive analytics.

### Candidate Sleeve — Hyperp / Pre-Launch Relative Value

Hyperliquid-only/pre-launch perpetuals can have a materially different reference-price mechanism from ordinary oracle-anchored perps.

Treat them as a separate instrument class.

Maintain:

- launch/listing event timeline;
- initial mark/reference;
- current Hyperp oracle/reference mechanism;
- external pre-launch perp venues;
- external venue contract differences;
- mark/oracle bounds;
- liquidity/depth;
- funding;
- expected conversion/settlement/listing event;
- time to scheduled/expected catalyst where defensibly known.

Candidate relationships:

- Hyperp vs external pre-launch perp;
- Hyperp vs prediction/derived listing reference where contract semantics truly match;
- cross-venue pre-launch consensus;
- mark/reference divergence;
- convergence around spot launch or contract conversion;
- post-listing transition from Hyperp-specific reference logic to ordinary market structure.

Critical rules:

- contract semantic equivalence is mandatory;
- a same ticker is not proof of same payoff;
- settlement/listing uncertainty is explicit;
- event dates from rumors/social media are not treated as facts;
- mark-price caps/reference formulas are included in replay;
- no convergence claim can ignore the fact that different venues may encode different listing outcomes or settlement rules;
- this sleeve remains within Cross-Instrument Relative Value until evidence justifies a standalone module.

### Cross-deployer same-underlying graph

HIP-3 can host multiple contracts linked to the same or similar underlying through different deployers.

Build a compatibility graph:

```text
economic_underlying
  -> deployer contract A
  -> deployer contract B
  -> deployer contract C
  -> external benchmark(s)
```

Each edge stores:

- semantic equivalence confidence;
- oracle/reference definition;
- collateral;
- margin mode;
- fees;
- funding;
- tick/lot;
- depth;
- session state;
- historical basis/residual;
- hedgeability.

This graph allows Alina to detect whether the best opportunity is:

- direct Cross-Venue;
- XEMM;
- Relative Value;
- same-underlying cross-deployer convergence;
- or `NO_TRADE`.

Never create a Cartesian all-deployer × all-symbol matrix when compatibility is absent.

### External-bot findings that do NOT become standalone modules

The following public-bot patterns are recorded but not promoted as first-class modules merely because other projects implement them:

- naive grid;
- martingale/DCA averaging-down;
- generic RSI/MACD/SuperTrend;
- unqualified mean reversion;
- generic AI/LLM trading agent;
- social-sentiment trading;
- Kelly sizing without independently proven edge;
- naive wall-fronting;
- market making credited only from spread/rebate;
- high-frequency strategies whose gross edge does not clear friction.

They may generate narrowly preregistered challengers only when they change a mechanism already supported by Alina evidence.

### Turnover/friction prior from public strategy sweeps

Public strategy sweeps on Hyperliquid reinforce a useful **prior**: turnover can destroy otherwise positive zero-fee backtests.

This does not create a fixed `200 trades/year` rule.

Instead, for every candidate report:

- annualized trade count;
- round-trip cost drag;
- gross profit per trade;
- net profit per trade;
- fraction of gross alpha lost to friction;
- sensitivity to +25%, +50% and +100% cost stress;
- break-even fee/slippage level.

Prefer hypotheses with a healthy **edge-to-friction ratio**, not merely low trade count.

A low-turnover strategy with four historical trades is not considered proven merely because fees are small; effective sample size and regime coverage remain mandatory.

### Updated V6 research ordering after public-bot review

V6.2 refines the research queue to:

1. **P0A — Shared Execution Alpha Core**
2. **P0B — XEMM / Hedged Market Making**
3. **P1A — Scheduled Flow / Native TWAP & Metaorder**
4. **P1B — Forced-Flow / Liquidation V2**
5. **P1C — HIP-3 / RWA Session & Reopen Edge**
6. **P2 — Cross-Instrument Relative Value, including Hyperp/pre-launch and cross-deployer sleeves**
7. **P3 — Medium-Horizon Trend / Breakout**
8. **always-on shared context — Options/Volatility + Builder/Participant Flow Provenance**

This remains a **research priority**, not a profitability ranking.

Reprioritization is allowed when Alina's own evidence shows a materially different target-gap reduction, falsification speed, event frequency, capacity or data-quality profile.

### V6.2 evidence scoreboard extensions

Extend the V6.1 scoreboard with:

| lane | maker fill % | hedge success % | hedge latency | adverse markout | flow toxicity | session | net USD/day LCB | capacity | evidence |
|---|---:|---:|---:|---:|---:|---|---:|---:|---|
| XEMM | | | | | | | | | |
| HIP-3 session | | | | | | | | | |
| flow provenance incremental | | | | | | | | | |
| hyperp/pre-launch RV | | | | | | | | | |

For XEMM also report:

- quoted opportunities/day;
- maker fills/day;
- hedgeable fraction;
- failed/partial hedge count;
- quote-to-fill adverse move;
- realized maker spread captured;
- realized hedge slippage;
- residual inventory capital-time.

For HIP-3 also report:

- external/internal session counts;
- reopen events;
- session-specific depth/spread;
- off-hours prediction error;
- reopen convergence markout;
- band/boundary events.

For flow provenance also report:

- classified fraction;
- unclassified fraction;
- label stability;
- incremental calibration value;
- incremental PnL/rejection value.



### Profitability Convergence V6.3 — execution truth, venue state and adversarial validation

The large public-bot/code survey identified a class of failure that can be more dangerous than a bad signal: **an apparently profitable edge produced by unrealistic execution, stale venue rules or hidden backtest leakage**.

V6.3 therefore introduces a strict distinction:

> **economic alpha is not proven until the causal event timeline, queue uncertainty, order lifecycle, venue cost/rule state and data-availability boundary are all explicit.**

The objective is to reduce false-positive PnL while also exposing new execution opportunities such as priority-fee optimization, better hedge policies and state-dependent routing.

All additions remain paper/read-only.

### Canonical causal timeline

Every event used by a latency-sensitive strategy must preserve separate clocks where the source permits:

- `ts_exchange`: exchange/source event timestamp;
- `ts_received` or `ts_local`: time the collector could first observe the event;
- `ts_decision`: strategy decision time;
- `ts_send`: hypothetical paper-order send time;
- `ts_exchange_arrival`: modeled order arrival at venue;
- `ts_ack`: modeled/observed acknowledgement time where available;
- `ts_fill`: fill time;
- `ts_cancel_send`;
- `ts_cancel_effective`;
- `ts_sim`: deterministic total-order simulation timestamp;
- source sequence / stable tie-break key when timestamps collide.

Rules:

- a decision sees only information with `ts_received <= ts_decision`;
- order matching uses the venue state at modeled `ts_exchange_arrival`, not the stale book seen at decision time;
- cancel requests remain exposed until `ts_cancel_effective`;
- a fill during `PENDING_CANCEL` is valid and must be accounted;
- equal-timestamp events use a documented deterministic tie-break rule;
- replay results must be reproducible from code SHA + data manifest + latency model + RNG seed + ordering policy;
- monetary/accounting state should use fixed-point/integer representation where practical so floating-point tie noise cannot change fills or PnL.

### Order lifecycle state machine

Paper execution supports at least:

`NEW_INTENT -> PENDING_NEW -> OPEN -> PARTIALLY_FILLED -> PENDING_CANCEL/PENDING_REPLACE -> FILLED/CANCELED/REJECTED/EXPIRED`.

Requirements:

- every partial fill immediately updates position, fee, realized/unrealized PnL, inventory, hedge requirement and remaining quantity;
- a later final fill cannot overwrite or erase earlier fill chunks;
- replacement is modeled as cancel + new-order semantics unless the venue provides atomic modify semantics and the historical rule is known;
- pending cancel/replace races are replayed;
- IOC remainder is canceled rather than silently rested;
- post-only orders that would cross after latency are rejected/canceled according to venue semantics, not filled optimistically;
- batch-level rejection semantics are preserved when one invalid action can reject the whole batch.

### Queue / fill uncertainty ensemble

When only L2/market-by-price data exist, Alina must not represent queue position as exact FIFO truth.

Maintain a **queue-belief interval** and multiple challenger fill models, including at minimum:

1. `RISK_AVERSE_QUEUE` — cancellations do not improve our position unless supported by trades / defensible evidence;
2. `PROBABILISTIC_QUEUE` — cancellations/depth reductions probabilistically occur ahead/behind based on calibrated state;
3. `PRIORITY_AWARE_QUEUE` — venue-specific priority/ALO rules modify recent-tail ordering where applicable;
4. `L3_FIFO` only when true order-level data and matching semantics are available.

Optional calibrated models may use:

- queue ahead lower/upper bounds;
- visible size;
- order count where available;
- same-price taker flow;
- adds/removals;
- cancellation intensity;
- iceberg/refill evidence;
- side-specific toxicity;
- venue/session state;
- priority-fee state.

Promotion rules:

- maker/XEMM economics must be reported across the ensemble, not only under the most favorable model;
- a strategy whose sign changes under modest plausible queue assumptions is `QUEUE_UNCERTAIN`, not proven;
- exact queue claims require L3/order-level evidence;
- public L2 cannot be reverse-engineered into false precision.

### Latency uncertainty decomposition

Model latency as components rather than one scalar:

```text
feed_latency
+ collector_processing
+ strategy_decision
+ paper_order_send
+ network/order_arrival
+ venue_processing/priority
+ hedge_latency
```

For every component track:

- empirical distribution if measurable;
- median / p90 / p99;
- jitter;
- missingness;
- source/provenance;
- version/regime.

Run stress surfaces such as:

- baseline;
- +25%;
- +50%;
- +100%;
- observed p90/p99;
- venue-specific outage/degraded regimes.

An edge that disappears before realistic latency uncertainty is included cannot be promoted.

### Hyperliquid Priority-Fee Economics

Hyperliquid priority fees make latency and queue position an explicit economic variable.

The paper engine must support **historically versioned priority semantics**.

For IOC-style priority research, evaluate a candidate schedule of priority rates:

`0 bp -> low bp -> ... -> documented useful cap`

and estimate:

```text
incremental_value(priority)
= alpha_preserved_by_faster_arrival
  + fill_probability_improvement
  - priority_fee
  - extra_adverse_selection
```

For ALO/post-only priority research, model the documented queue-priority effect during the eligible recent-order window rather than treating all same-price maker orders as FIFO forever.

Current official documentation reviewed on 2026-09-25 reports approximately **45 ms reduction in end-to-end IOC latency per 1 bp** in the 0-8 bp priority range and describes an ALO queue-priority window of roughly **400 ms**. These values are **versioned research inputs**, not universal constants.

Requirements:

- store `priorityGas` / equivalent fee evidence where present;
- do not extrapolate current priority semantics backward before activation;
- priority cost is part of execution cost, never omitted from net PnL;
- calculate break-even priority fee for each alpha-half-life bucket;
- if the edge cannot pay the priority fee required to reach it, choose lower priority or `NO_TRADE`;
- read/gossip priority and write/order priority are separate concepts;
- V6.3 remains read-only/paper and never sends priority-fee orders.

### Dynamic Venue Economics Engine

Fixed fee constants are insufficient for proof-quality replay.

Maintain a versioned fee/economic state for every venue/instrument where relevant:

- maker fee;
- taker fee;
- maker rebate;
- rolling-volume fee tier;
- staking/discount tier;
- referral discount when legitimately applicable;
- builder fee;
- HIP-3 deployer fee scale;
- growth-mode state;
- aligned-quote adjustments;
- priority fee;
- funding;
- borrow/custody cost for spot legs;
- withdrawal/transfer cost when the strategy requires transfers;
- minimum notional/tick/lot constraints.

For Hyperliquid specifically, fee tier depends on rolling 14-day weighted volume and current rules can include maker rebates and HIP-3-specific scaling.

Proof policy:

- do not credit a fee tier, staking discount, maker rebate or referral benefit that the paper account/evidence contract has not explicitly made achievable;
- baseline proof should use the conservative achievable cost state;
- lower-cost hypothetical tiers may be shown as sensitivity/capacity scenarios but cannot prove the +4 USD/day milestone;
- historical replay uses the rules effective at the historical timestamp whenever rule history is available;
- rule-history unknowns are `UNMEASURABLE`, not silently replaced by current fees.

### Venue Health & Rule-State Engine

Every venue/instrument carries an explicit health state such as:

`HEALTHY / DEGRADED / STALE / HALTED / RECOVERING / UNKNOWN`.

Inputs may include:

- last event age;
- timestamp monotonicity;
- sequence gaps;
- WS reconnects;
- REST/WS disagreement;
- BBO/L2 heartbeat;
- trade heartbeat;
- oracle age;
- market-status endpoint;
- maintenance/outage state;
- order-rejection bursts;
- open-interest cap state;
- contract/spec revision;
- trading halt/resume;
- fee/rule revision.

Rules:

- apparent Cross-Venue dislocations involving `STALE/HALTED/UNKNOWN` references are not admitted as normal arbitrage;
- recovery requires a bounded reconciliation/catch-up phase;
- venue health is replayable point-in-time state;
- no venue is permanently trusted because of historical uptime;
- data-source health and economic-market health are separate states.

### HIP-3 Oracle / Operator Health

HIP-3 markets require additional state because deployer-operated oracle/reference configuration can change independently of the order book.

Maintain where observable:

- oracle update timestamp/age;
- mark update timestamp;
- external reference price;
- order-book mid;
- `mark-oracle`, `mid-oracle`, `oracle-external` divergence;
- update cadence;
- stale/fallback state;
- open-interest cap;
- margin/leverage-table revision;
- deployer/DEX configuration revision;
- `haltTrading` / resume state;
- settlement state;
- reference market session state.

Candidate specialist hypotheses:

- oracle-update synchronization;
- stale-oracle/fallback liquidity withdrawal;
- OI-cap-induced one-sided flow;
- halt/resume/reopen dislocation;
- mark/oracle convergence;
- external-reference reacquisition after off-hours.

These are hypotheses only. A stale oracle is not automatically an exploitable arbitrage.

### Collateral / Quote-Currency Risk Engine

A nominally delta-neutral structure may still contain collateral or quote-currency risk.

Track:

- collateral token;
- quote token;
- USD/reference conversion;
- collateral/reference basis;
- depeg magnitude and liquidity;
- haircut/margin treatment where published;
- cross-venue collateral mismatch;
- collateral transfer/redemption dependency;
- stressed collateral value.

Relative Value/XEMM/carry reports must separate:

```text
underlying_delta
+ basis_delta
+ funding_delta
+ collateral_fx_delta
+ margin/liquidation risk
```

Rules:

- USDC/USDT/other stable assets are not hard-coded to exactly 1 USD under stress analysis;
- a hedge using mismatched quote/collateral assets is not labeled fully neutral without proving the residual;
- depeg/stress scenarios feed capacity and liquidation-risk calculations.

### Forced-Flow Route Classifier

Forced-Flow V2 is refined into distinct execution routes:

`MARKET_LIQUIDATION -> BACKSTOP_ABSORPTION -> ADL`.

Where public evidence permits, classify every forced execution into one of:

- open-book market liquidation;
- protocol/backstop position absorption;
- auto-deleveraging;
- unknown.

Do not collapse all forced executions into one liquidation counter.

Maintain route-specific:

- notional;
- coin;
- side;
- start/end time;
- execution price/markout;
- OI clearing;
- depth/impact state;
- absorber/backstop evidence where public and non-identifying;
- transition latency;
- subsequent ADL wave;
- recovery.

A **severity ladder** may be derived:

`BOOK_ABSORBS -> BACKSTOP_NEEDED -> ADL_NEEDED`

but must remain an observed/measured state rather than a causal claim.

Candidate sleeves:

- continuation during open-book liquidation;
- transition-to-backstop detection;
- backstop absorption/recovery;
- pre-ADL fragility state;
- post-ADL liquidity normalization;
- cross-asset propagation by liquidation route.

### Liquidity Fragility / Slippage-at-Risk surface

Depth at one notional is insufficient.

For each HOT/WARM instrument and important route, maintain a stress surface over notionals:

`Q1 < Q2 < ... < Qn`

with:

- executable VWAP;
- slippage bps;
- fraction of visible depth consumed;
- spread;
- recovery/resilience;
- depth concentration by level;
- provider concentration only when attribution is genuinely public and reliable;
- stale/cancel-adjusted uncertainty.

Derived research metrics may include:

- slippage quantiles across instruments;
- expected tail slippage;
- tail-dollar slippage;
- depth deterioration trend;
- stress-notional capacity.

No provider-concentration metric may be invented from anonymous aggregated L2.

Use this surface to:

- size Forced-Flow vulnerability;
- cap XEMM/Relative-Value notionals;
- detect fragile new listings/HIP-3 markets;
- reduce capacity before raw depth collapses.

### Backtest Integrity Firewall

Before any module/challenger can be promoted to OOS-valid, run adversarial integrity tests.

#### Lookahead perturbation test

Create a baseline replay, then rerun with selected future/unrelated slices withheld or signal branches isolated.

Fail if historical indicator/signal values at time `t` change because future data beyond `t` was removed, except for explicitly labeled ex-post analytics.

Common forbidden patterns include:

- negative shifts;
- whole-frame aggregation used as a live feature;
- row indexing that reaches future observations;
- future-complete labels available to the decision path;
- using final candle high/low/close before candle close;
- using future-normalized cross-sectional statistics.

#### Recursive / startup-history stability test

Recompute recursive indicators/features with several admissible history lengths.

Track:

- feature variance at the same timestamp;
- signal flips;
- admission flips;
- PnL sensitivity.

A feature with meaningful startup-history dependence must either:

- increase warmup/history requirements;
- use a stable alternative;
- remain research-only.

#### Closed-bar / event-finality rule

Bar-derived strategies use only completed bars unless the strategy is explicitly designed and tested as intrabar.

For every aggregate record, store:

- interval start;
- interval end;
- finalization timestamp;
- first timestamp at which the full value was knowable.

#### Dataset-slice invariance

For causal features, computing the same timestamp from:

- the full dataset;
- a prefix ending shortly after that timestamp;
- a replay stream

should produce the same value within documented numerical tolerance.

#### Randomness / determinism

Any stochastic queue/latency model records:

- seed;
- model version;
- parameters;
- number of simulations.

Economic proof reports distributional results, not only the lucky seed.

### XEMM Hedge Policy Frontier

XEMM no longer assumes that every maker fill must use one fixed hedge behavior.

Evaluate bounded policies:

1. **IMMEDIATE_HEDGE**;
2. **DELAYED_HEDGE** with strict maximum delay and signal/risk condition;
3. **SPLIT_HEDGE** across multiple independently healthy venues;
4. **SYNTHETIC_HEDGE** only when instrument/FX relationships are explicit and hedge error is measured;
5. **NO_NEW_QUOTE** when no acceptable hedge path exists.

Every policy reports:

- hedge fill probability;
- latency;
- hedge slippage;
- residual delta path;
- basis risk;
- collateral mismatch;
- margin use;
- capital-time;
- tail loss under hedge failure.

Delayed hedge cannot be credited with favorable future price selection. It is an explicit temporary directional exposure and must be measured as such.

Split-hedge routing uses executable depth and venue health, not static percentages unless those are the tested baseline.

### Funding / settlement-state refinement

Funding remains part of Relative Value rather than returning as naive carry.

However, the research layer may test point-in-time forecasts of:

- next funding settlement;
- premium-index persistence;
- cross-venue funding dispersion;
- funding compression/reversal;
- funding plus executable basis.

Requirements:

- exact funding timestamp/convention is versioned per venue;
- expected funding is separated from realized funding;
- the entry decision cannot use the finally realized rate if it was not known;
- delta-neutral funding sleeves include every hedge leg, margin/collateral and exit cost;
- funding prediction must improve a simpler executable basis baseline OOS.

### Listing / Delisting / Contract-Change Event Lane

Public bot research shows that some listing announcements can create large immediate moves, but those edges may require sub-second infrastructure and are highly venue/event specific.

Because Alina is GitHub-hosted and paper/read-only, V6.3 does **not** assume it can win a latency race.

Instead, maintain an event ledger for:

- listing announcement;
- trading-open time;
- pre-launch market creation;
- spot/perp conversion;
- delisting/caution announcement;
- contract rename/migration;
- leverage/margin change;
- market halt/resume;
- fee/rule change.

Use it for:

- event contamination tagging;
- Trend/Forced-Flow regime conditioning;
- Pre-Launch Relative Value;
- post-announcement continuation/reversal studies;
- excluding impossible pre-announcement fills from backtests.

The source must be official or provenance-scored, with both publication time and first-observed time stored when measurable.

### Corpus saturation rule

The Public Bot Intelligence Program should continue scanning, but research breadth is bounded by **novel mechanism yield**.

For each search batch, record:

- items reviewed;
- unique repositories/posts after deduplication;
- high-signal practitioner/code sources;
- new mechanisms discovered;
- duplicate/already-covered mechanisms;
- rejected marketing/no-evidence items.

A research family is considered **temporarily saturated**, not permanently complete, when several diverse new batches yield only duplicates or low-quality variants and no material new mechanism.

New code/releases/X discussions can reopen the family later.

### V6.3 research priority update

V6.3 refines the current priority stack to:

1. **P0A — Execution Alpha / Queue-Latency Certification**
2. **P0B — Priority-Fee Economics + Dynamic Cost State**
3. **P0C — XEMM + Hedge Policy Frontier**
4. **P1A — Scheduled Flow / TWAP**
5. **P1B — Forced-Flow with liquidation-route classifier**
6. **P1C — HIP-3 Session + Oracle/Operator Health**
7. **P2 — Relative Value / Hyperp / funding-settlement refinements**
8. **P3 — Medium-Horizon Trend**
9. **shared certification — Venue Health, Collateral Risk, Backtest Integrity, Options and Flow Provenance**

This is a research-order heuristic, not a predicted profitability ranking.


### Profitability Convergence V6.4 — portfolio intent netting and latent-flow intelligence

The continued public-bot/code corpus review identified a final class of opportunities that sits **between alpha generation and execution**:

- multiple Alina modules can create offsetting intents in the same instrument;
- public order/trigger state can reveal **latent future flow** for a tracked subset of wallets;
- repeated displayed-liquidity replenishment can reveal **absorption strength** even when hidden size is not directly observable;
- larger future notionals require an execution-policy frontier beyond one-shot maker/taker routing.

V6.4 adds these as shared portfolio/execution intelligence. They do not replace the independent proof obligation of any module.

### Cross-Module Intent Netting Engine

Alina must distinguish:

1. **module research PnL** — what each module would have done independently under its own certified execution model;
2. **portfolio execution PnL** — what the combined portfolio can save or lose after compatible intents are netted before external execution.

Example:

```text
Copy-Vault:     +50 USD BTC target delta
Trend:          -30 USD BTC target delta
Relative Value: -10 USD BTC target delta
-----------------------------------------
gross intents:   90 USD turnover-equivalent
net external:   +10 USD BTC delta
```

The portfolio may avoid unnecessary external turnover, but the research ledger must still preserve each module's standalone decision and attributable economics.

Required intent fields:

- module / edge sleeve;
- instrument;
- signed target delta;
- decision timestamp;
- urgency / alpha half-life;
- maximum acceptable delay;
- execution policy constraints;
- hedge requirement;
- venue constraints;
- confidence / evidence state;
- reason / opportunity id;
- expected gross edge;
- expected standalone execution cost.

#### Compatibility rules

Intents may be netted only when compatible on:

- economic instrument/payoff;
- collateral/margin assumptions where relevant;
- decision-time window;
- urgency;
- order/execution semantics;
- hedge requirements;
- evidence/accounting scope.

Do not net merely because ticker text matches.

Examples of non-compatible intents:

- one sleeve needs a spot leg while another needs a perp;
- one intent expires in 50 ms while another can wait 10 minutes;
- one intent is an XEMM hedge obligation and must not be canceled by unrelated speculative alpha;
- one position is isolated-margin constrained while another assumes cross-margin;
- two same-ticker HIP-3 contracts have different payoff/oracle semantics.

#### Attribution after netting

Maintain two ledgers:

```text
STANDALONE_RESEARCH_LEDGER
PORTFOLIO_EXECUTION_LEDGER
```

The standalone ledger prevents netting from hiding a weak module.

The portfolio ledger records:

- gross intended turnover;
- external turnover after netting;
- fees/spread/slippage avoided;
- opportunity cost created by waiting for netting;
- residual inventory;
- execution conflicts;
- fill allocation;
- netting savings.

A module cannot claim the portfolio's netting savings as its own signal alpha.

#### Internal-crossing boundary

In paper/replay, compatible opposite intents may be internally crossed at a clearly defined reference only for **portfolio accounting experiments**.

Requirements:

- reference price is causal and explicitly chosen, such as executable mid/arrival benchmark under the experiment;
- no fictional external fill is created;
- no maker rebate is credited;
- no market-impact benefit beyond avoided external turnover is invented;
- each internal cross preserves both contributing module records;
- standalone module proof remains based on its own external-execution counterfactual.

**Netting success criterion:** reduce conservative combined execution cost/turnover without degrading module-level evidence integrity or increasing missed-alpha loss beyond the savings.

### Tracked-Wallet Trigger / Latent Flow Map

Hyperliquid read-only order information can expose trigger-order fields for a **queried public wallet**, including trigger price and trigger state.

This enables a scoped latent-flow map for wallets already inside Alina's public research universe.

For every tracked wallet where public data is available, maintain:

- coin;
- side;
- trigger price;
- stop-loss vs take-profit where identifiable;
- reduce-only state;
- original size;
- remaining size;
- order creation timestamp;
- triggered/open/canceled/filled state;
- position relation;
- wallet cohort / leader score;
- freshness;
- provenance.

Aggregate by coin/price bucket into:

- tracked stop-long notional;
- tracked stop-short notional;
- tracked take-profit notional;
- number of independent wallets;
- concentration by wallet;
- distance from mark/oracle;
- overlap with liquidation-threshold density;
- overlap with visible depth and resilience.

#### Coverage rule

The trigger map must always report:

```text
tracked_wallets_with_order_visibility
/ eligible_tracked_wallets
```

and must be labeled:

`TRACKED_SAMPLE_TRIGGER_MAP`

unless Alina has a proven market-complete order source.

Never label a subset of known-wallet orders as "the market stop map."

#### Candidate uses

- improve Copy-Vault exit/copyability timing;
- identify likely forced/trigger flow near important levels;
- separate liquidation pressure from ordinary stop activation;
- condition Forced-Flow cascade state;
- identify overlap of stops + vulnerable liquidation notional + thin depth;
- study whether large tracked TP clusters create absorption/reversal rather than continuation.

Trigger state is not assumed informed.

**Trigger-map success criterion:** incremental OOS value versus the same module without tracked trigger-state features, with explicit coverage and concentration controls.

### Absorption / Replenishment Intelligence

Displayed L2 depth alone cannot distinguish fragile visible liquidity from a price level that repeatedly replenishes after aggressive flow.

Maintain causal level-level or band-level features where feed resolution permits:

- visible size;
- aggressive volume executed into the level/band;
- depletion amount;
- refill amount;
- refill latency;
- refill count;
- cancellation-before-touch rate;
- persistence duration;
- price movement despite aggressive volume;
- cross-venue agreement;
- post-event markout.

Define **replenishment/absorption evidence**, not "hidden size as fact."

Possible state labels:

- `FRAGILE_DISPLAYED_DEPTH`;
- `PERSISTENT_REPLENISHMENT`;
- `ABSORBING_BUY_PRESSURE`;
- `ABSORBING_SELL_PRESSURE`;
- `FLEETING_WALL`;
- `UNKNOWN`.

Rules:

- L2 replenishment is probabilistic evidence only;
- do not infer exact iceberg quantity from L2;
- spoof/manipulation labels remain probabilistic research labels;
- cancellations and trades must be distinguished where the feed permits;
- synthetic iceberg-model performance cannot certify real-market accuracy;
- L3/order-level evidence may increase confidence when genuinely available;
- features must be tested as incremental execution/forced-flow context before any standalone alpha claim.

Use cases:

- Execution Alpha maker-side selection;
- XEMM quote width/size;
- Forced-Flow absorption/exhaustion detection;
- TWAP visible-flow absorption measurement;
- Liquidity Fragility adjustment;
- distinguishing a real absorbing wall from fleeting displayed depth.

### Microstructure Cost & Impact Surface

V6.4 extends the execution state with a small set of interpretable microstructure diagnostics where supported:

- realized spread;
- effective spread;
- price impact per unit aggressive notional;
- depth recovery time;
- order-flow/price-response ratio;
- participation rate;
- volume acceleration;
- quote age;
- cancel-to-trade ratio;
- spread/depth elasticity.

Research metrics such as Kyle-style lambda, Amihud-style illiquidity or VPIN-like state may be used only when their exact construction is documented and they improve simpler baselines.

No named microstructure metric becomes strategy alpha by reputation.

### Capacity Execution Frontier

For small notionals, one-shot maker/taker decisions may remain optimal.

As notional approaches a meaningful fraction of available volume/depth, compare paper execution policies:

1. `ONE_SHOT_TAKER`;
2. `PASSIVE_MAKER`;
3. `TWAP`;
4. `VWAP`;
5. `POV` / participation-of-volume;
6. `IMPLEMENTATION_SHORTFALL`-style urgency schedule;
7. adaptive hybrid;
8. `NO_TRADE / REDUCE_SIZE`.

The objective is not to add execution sophistication where it is unnecessary.

Activate slicing research only when:

```text
order_notional / executable_depth
or
order_notional / rolling_market_volume
```

is large enough that self-impact/timing risk can matter.

Required accounting:

- arrival-price implementation shortfall;
- temporary/permanent impact proxy where measurable;
- spread/fee;
- participation rate;
- timing risk;
- completion probability;
- alpha decay during execution;
- residual quantity;
- opportunity cost;
- information leakage proxy such as spread/depth deterioration after repeated child orders.

A complex adaptive policy must beat simple TWAP/VWAP/one-shot baselines OOS.

### Funding Forecast Clarification

V6.3 already permits point-in-time funding forecasts.

V6.4 clarifies that funding data can enter three distinct states:

- `PUBLISHED_CURRENT`;
- `EXCHANGE_PREDICTED/NEXT` where the venue exposes such a value;
- `ALINA_FORECAST`.

They must never be merged.

For every funding observation store:

- source venue;
- applicable interval;
- observation timestamp;
- settlement timestamp;
- formula/source revision;
- current/predicted/realized type;
- premium/index inputs where available.

An Alina forecast must beat:

- current funding persistence;
- exchange-provided predicted funding where available;
- simple cross-venue median/consensus;

on frozen OOS economic value, not merely rate RMSE.

### Parameter-Change Event Ledger

Extend the V6.3 event ledger with point-in-time venue-rule changes:

- fee tier/schedule revision;
- maker rebate revision;
- priority-fee rule revision;
- leverage/margin tier change;
- open-interest cap change;
- growth-mode/deployer-fee change;
- oracle/reference specification revision;
- halt/resume;
- settlement/contract conversion;
- tick/lot/min-notional change;
- listing/delisting;
- API/feed semantic change.

Parameter changes may themselves create transient market-structure effects, but their first purpose is preventing invalid historical replay assumptions.

### Updated research order after corpus convergence

After filtering the large public-code/X corpus, the highest-value queue becomes:

1. **P0A — Execution Truth + Queue/Latency/Partial-Fill certification**
2. **P0B — Dynamic Cost / Priority-Fee Economics**
3. **P0C — Cross-Module Intent Netting**
4. **P0D — XEMM + Hedge Policy Frontier**
5. **P1A — Scheduled Flow / TWAP**
6. **P1B — Forced-Flow with route classifier + trigger/absorption context**
7. **P1C — HIP-3 Session / Oracle / Operator state**
8. **P2 — Relative Value / Hyperp / funding forecast**
9. **P3 — Trend**
10. **shared context — Options, Flow Provenance, Latent Trigger Map, Replenishment/Absorption**

This remains a research scheduling order, not a claimed profitability ranking.

### Corpus-convergence rule

The public-bot research program should continue, but the bar for adding a new first-class module rises as coverage converges.

A newly found public idea becomes a new module/layer only if it satisfies at least one:

- introduces a new economic counterparty/mechanism;
- exposes a new public data family unavailable to existing modules;
- changes execution economics materially;
- reduces a known false-positive source in proof;
- adds a materially independent opportunity class.

Otherwise classify it as:

- feature;
- baseline;
- execution policy;
- risk control;
- duplicate;
- watchlist;
- rejected/noise.

This prevents "research breadth" from becoming uncontrolled architecture growth.

### V6.4 research basis

High-signal findings supporting V6.4 include:

- **RustyBT order aggregation:** demonstrates explicit cross-strategy order netting, commission-savings accounting and fill attribution back to contributing strategies; Alina uses the mechanism only as a research architecture pattern, not its claimed savings.
- **institutional-style OMS/EMS public architectures:** normalized portfolio intent is translated into the smallest necessary external order after considering existing positions and compatible interests.
- **Hyperliquid read-only frontend/open-order schemas:** queried public wallets can expose trigger-order state and trigger prices, supporting a tracked-sample stop/TP map while not proving market-wide coverage.
- **Hyperliquid order-lifecycle public data providers:** order transitions can preserve trigger activation and partial-fill lifecycle; third-party completeness must be independently certified before use as authoritative evidence.
- **public L2/L3 iceberg/replenishment research implementations:** repeated refill and absorption signatures are observable, but L2 cannot reveal exact hidden size and synthetic classifiers cannot be imported as truth.
- **adaptive execution research/frameworks:** POV/VWAP/implementation-shortfall policies formalize the impact-versus-timing-risk tradeoff for larger orders; Alina applies them only when capacity makes slicing economically relevant.


### V6.3 research basis

The following high-signal public/official sources motivated V6.3. They create hypotheses and engineering requirements only:

- **Hyperliquid official Priority Fees documentation:** current IOC order priority explicitly trades additional bps for lower latency and ALO priority can alter recent queue ordering; priority fee evidence is exposed in recorded fills.
- **Hyperliquid official Fees documentation:** current fees depend on rolling volume and can include maker rebates, staking/referral discounts and HIP-3/deployer/growth-mode adjustments.
- **hftbacktest:** queue-aware, latency-aware L2/L3 replay demonstrates why passive fills require queue models rather than touch/cross heuristics.
- **realistic-mm-backtester / recent Rust-Python tick backtest projects:** separate feed/order/cancel latency, pending races, queue cancellation assumptions and true-book-at-arrival execution are standard requirements for believable maker research.
- **Freqtrade lookahead-analysis and recursive-analysis:** adversarial re-runs can reveal future leakage and unstable startup-history dependence that ordinary unit tests miss.
- **BBGO xmaker:** mature cross-exchange market making includes delayed, split and synthetic hedge policies, motivating an explicit hedge-policy frontier rather than one hard-coded hedge rule.
- **public Hyperliquid forensic liquidation replay projects:** market liquidation, backstop absorption and ADL can be separated from public evidence and should not be collapsed into one forced-flow state.
- **HIP-3 official/operator documentation:** oracle freshness, OI caps, margin/leverage configuration, halt/resume and external reference state are part of market mechanics and must be point-in-time inputs.
- **public listing-event bots:** some announcement families show large moves while others do not, reinforcing strict event-specific validation and the decision not to assume a generic listing edge.



### Profitability Convergence V6.5 — venue microstructure expansion

The continued corpus filter identified a new source of both opportunity and model risk: **new perp venues with materially different execution models**.

The V6.5 principle is:

> **a new venue is useful only when it adds a new economic surface, a new public data family or a materially better route — and its microstructure must be modeled before its prices are compared with a conventional CLOB.**

### Venue microstructure taxonomy

Every venue/instrument declares one versioned class:

- `VISIBLE_CLOB`;
- `PARTIALLY_HIDDEN_CLOB`;
- `RFQ_DUAL_BOOK`;
- `NATIVE_MULTI_LEG`;
- `AMM_OR_ORACLE_EXECUTION`;
- `UNKNOWN`.

The class determines which concepts are valid.

Examples:

- displayed depth can certify executable depth only on an appropriate executable book;
- hidden-order venues make public L2 structurally incomplete;
- RFQ indicative quotes cannot be substituted for the real executable resting book;
- native multi-leg semantics can change legging risk relative to sequential orders;
- fee and latency can depend on account class/tier.

### Venue capability contract

For every candidate venue maintain:

- public REST/WS;
- BBO;
- L2/L3;
- trades;
- funding/current + forecast if available;
- OI;
- oracle/index/mark;
- liquidations;
- market status/session;
- snapshot/delta/sequence semantics;
- archive/history;
- fee schedule;
- account/fee tier;
- latency tier;
- collateral;
- microstructure class;
- hidden-liquidity/privacy state;
- order-type capabilities;
- spec/version history;
- collector state: `DISCOVERY_ONLY / MEASURE_ONLY / REPLAY_GRADE / HOT_ELIGIBLE`.

A new venue is not promoted because it is popular. Promotion requires **distinct economics + replay-grade public evidence + useful symbol overlap**.

### Fee-latency frontier

Some venues directly exchange lower fees for higher latency or vice versa.

Evaluate route/account tier as:

```text
tier_value
= edge_preserved_by_latency
  - maker/taker fee
  - priority/tier/staking cost
  - adverse-selection change
  - capital/opportunity cost
```

A zero-fee path with slow execution can be inferior to a paid faster path when alpha half-life is short.

A faster paid tier can be inferior when the edge cannot pay the fee.

The tier/account class is part of route identity and is never switched silently in replay.

### Stage-A venue candidates

#### Lighter

Official documentation reviewed in this corpus pass provides:

- public WebSocket order book;
- snapshot + delta state;
- nonce/begin-nonce continuity;
- order-book updates in short batches;
- account tiers with distinct fee and latency economics;
- current Standard account economics with zero maker/taker fees and slower processing;
- faster paid/premium configurations.

Candidate opportunities:

- zero-fee slower taker versus paid faster taker;
- Lighter as XEMM hedge venue;
- Lighter as maker venue;
- Hyperliquid/Binance/edgeX -> Lighter Lead-Lag;
- funding/basis Relative Value;
- TWAP/parent-order research only where a public read-only source exposes enough point-in-time evidence.

No proof may credit an account tier that the modeled account cannot achieve.

#### edgeX

Official public API/WS material exposes:

- public depth;
- funding history;
- next funding timestamp;
- market status;
- oracle/index context;
- premium index;
- impact bid/ask;
- forecast/predicted funding fields.

This creates high-value research lanes:

- venue-provided funding forecast versus realized settlement;
- forecast-revision velocity;
- cross-venue funding forecast dispersion;
- impact-price versus BBO/depth;
- RWA/session-aware Cross-Venue;
- XEMM;
- basis/Relative Value.

A venue-provided `forecastFundingRate` is an input feature, not future truth.

### Stage-B venue candidates

#### Paradex

Paradex exposes public order-book data and different retail/pro fee regimes.

Rules:

- retail/pro/API order classification is explicit;
- retail zero-fee economics cannot be assigned to incompatible pro/API execution;
- token/staking discounts are sensitivity scenarios unless the proof contract can achieve them;
- sequencing/data quality must pass replay certification before HOT use.

#### GRVT

GRVT exposes order-book/RFQ concepts and native multi-leg order semantics.

Candidate opportunities:

- native multi-leg Relative Value;
- joint/FOK/AON execution versus sequential legging;
- RFQ versus visible-book pricing;
- stable-perp/RWA session effects;
- XEMM/funding basis.

Native multi-leg does not automatically mean atomic risk-free execution; the exact TIF and partial-fill semantics govern proof.

#### Extended

Extended RFQ markets use a materially different model:

- an **indicative book**;
- a separate **real RFQ book** with actual resting orders/child quotes;
- role-based fee semantics;
- quote-walk child orders for market/RFQ execution.

Therefore:

- the standard indicative book is never treated as executable resting depth;
- RFQ real-book collection is a separate evidence family;
- maker/taker labels follow venue role semantics, not generic CLOB assumptions.

Candidate sleeves:

- RFQ pickup economics;
- indicative-real divergence;
- child-quote acceptance hazard;
- RFQ liquidity drought;
- RFQ-CLOB basis;
- RWA session effects.

### Stage-C / partial-visibility candidates

#### Aster

Aster publicly documents hidden orders and hidden positions.

Therefore public order-book/wallet evidence can be incomplete.

Maintain:

- `displayed_depth`;
- `hidden_liquidity_possible`;
- `public_position_visibility`;
- `depth_completeness_confidence`;
- `wallet_flow_completeness_confidence`.

Consequences:

- absence from public L2 is not proof of absence;
- public wallet/smart-money maps cannot claim total participant coverage;
- slippage uses uncertainty bands;
- Aster may still be valuable as price/funding/reference venue.

Aster native chase/scaled/hidden order types are execution features only when their semantics are point-in-time documented and replayable.

### Venue-native order type registry

Record support for:

- ALO/post-only;
- IOC/FOK/AON/GTT;
- chase/pegged;
- scaled;
- native TWAP;
- parent/child;
- multi-leg;
- hidden;
- STP;
- cancel-on-disconnect/dead-man switch.

Operational features receive no alpha credit unless they change measurable fill/cost/risk.

### Cross-Venue Route Graph V2

Route nodes now include:

```text
venue
instrument
microstructure_class
account_fee_tier
latency_tier
collateral
session
health
visibility_confidence
fee_state
funding_state
oracle_state
depth_state
```

Route edge types include:

- taker-taker;
- maker-taker XEMM;
- maker-maker;
- spot-perp;
- perp-perp;
- RFQ-CLOB;
- native-multileg;
- synthetic hedge.

Only economically equivalent contracts/routes are compared.

### Funding forecast intelligence

When venues publish point-in-time forecasts, store:

- current funding;
- venue forecast/predicted funding;
- premium index;
- average premium index;
- impact bid/ask;
- next funding time;
- forecast revision;
- forecast error after settlement.

Rules:

- final settlement cannot backfill the decision-time feature;
- venue forecasts compete with persistence and Alina simple consensus baselines;
- retain only if frozen-OOS route/economic value improves.

### Cross-venue capital-efficiency graph

For every route, track:

- collateral posted;
- margin used;
- isolated/cross;
- idle prefunding;
- unhedged interval;
- transfer dependency;
- collateral mismatch;
- liquidation distance;
- capital-time.

Report:

```text
net_usd_day
net_usd_day / committed_capital
net_usd_day / margin_used
net_usd_day / capital_time
```

Separate venues are not assumed to share margin/netting.

### Collection rollout after V6.5

**Stage A — strongest distinct data/economics**
- Lighter;
- edgeX.

**Stage B — distinct execution semantics**
- GRVT;
- Extended;
- Paradex.

**Stage C — structurally incomplete public visibility**
- Aster;
- future hidden/private/RFQ venues;
- Variational or other venues only after public replay-grade access is verified.

This is a collection research order, not a profitability ranking.

Promotion uses:

- overlap with HOT/WARM instruments;
- data freshness/sequence quality;
- archive feasibility;
- new independent opportunities;
- distinct fee/latency mechanics;
- funding/OI/oracle richness;
- GitHub-hosted quota feasibility.

### V6.5 corpus rule

A new venue or bot idea enters architecture only if it adds at least one of:

- new economic mechanism;
- new executable route class;
- new public data family;
- material fee/latency improvement;
- material proof-quality improvement;
- independent opportunity class.

Otherwise classify as:

`FEATURE / BASELINE / EXECUTION_POLICY / RISK_CONTROL / DUPLICATE / WATCHLIST / NOISE`.



### Profitability Convergence V6.6 — selective L4 truth and backstop-inventory intelligence

The final high-signal corpus pass found two Hyperliquid-native information advantages that are materially different from ordinary L2 research:

1. **order-level raw book diffs / L4-style evidence** can improve queue and cancellation truth without violating the paper-only boundary;
2. **protocol backstop inventory** can create a second-stage forced-flow process after initial liquidation/backstop absorption.

Because complete order-level history is extremely large, V6.6 is explicitly selective and event-windowed.

### Selective L4 Evidence Lane

Hyperliquid official node data schemas expose raw resting-order lifecycle events including fields such as:

- public user address;
- order id;
- coin;
- side;
- price;
- new/update/remove state;
- original/current size where provided.

Official order-book semantics are price-time based, with venue-specific priority behavior that can modify the effective ordering of recent orders.

The L4 lane is **not** a replacement for the normal BBO/L2 collection path.

Use it only for bounded high-value evidence windows such as:

- XEMM maker-fill calibration;
- maker queue/fill studies;
- TWAP/metaorder events;
- forced-flow/liquidation/backstop windows;
- HIP-3 session/oracle transitions;
- priority-fee studies;
- unexplained L2 replenishment/absorption events;
- representative calm control windows.

#### L4 reconstruction contract

Where the source is complete enough, reconstruct per-order state keyed by at least:

`(coin, oid)`

and maintain:

- side;
- price;
- current/original quantity;
- add/update/remove sequence;
- deterministic block/sequence position;
- order age;
- queue-ahead quantity;
- order count/queue depth at the level;
- cancellation/removal;
- fill linkage;
- public owner address as market-structure provenance only;
- priority/reordering metadata only when explicitly present and verified.

Rules:

- raw diffs require a known initial state/snapshot; diffs alone cannot establish the starting book;
- sequence gaps invalidate exact queue claims until repaired;
- same-block/timestamp ordering follows canonical source ordering;
- public owner addresses are never deanonymized;
- if priority/reordering information is unavailable, queue position remains an interval/uncertain estimate;
- third-party L4 feeds are certified against official node schemas on sampled windows before being treated as authoritative;
- the historical simulator never upgrades an L2-only window to exact FIFO merely because another period had L4.

### L4-to-L2 Queue Calibration Bridge

Use certified L4 windows to score each cheaper broad-replay queue model.

Per model measure:

- fill/non-fill accuracy;
- false-fill rate;
- missed-fill rate;
- queue-ahead error;
- fill-time error;
- partial-fill error;
- cancel-race error;
- post-only rejection error;
- maker/taker misclassification;
- PnL optimism/pessimism;
- adverse-selection bias.

Condition calibration where sample size permits by:

- venue;
- coin/liquidity bucket;
- volatility;
- spread/depth regime;
- side;
- session;
- priority-fee regime.

The objective is:

> **use the cheapest broad model whose bias is measured and sufficiently conservative, while escalating fragile maker claims to L4 evidence.**

Evidence tiers:

- `L2_ONLY`;
- `L2_CALIBRATED_BY_L4`;
- `L4_WINDOW_RECONSTRUCTED`;
- `L4_GAPPED_OR_UNCERTAIN`.

A strategy can be rejected from L2-only evidence. Queue-sensitive promotion should prefer L4-calibrated or stronger evidence where feasible.

### L4 Resource / GitHub-Only Contract

Official node data can be extremely large and is not suitable for blind replication into the project dataset.

Therefore:

- never mirror the full raw-node corpus by default;
- fetch bounded time/coin/event windows;
- retain content hashes and source manifests;
- compress retained evidence;
- prefer reproducible refetch manifests when permanent raw retention is disproportionate;
- use GitHub-hosted/cloud-compatible access only;
- do not introduce a self-hosted node;
- do not touch or wake the user's PC;
- paid/proprietary L4 access that is unavailable is reported `UNMEASURABLE`, never replaced by optimistic assumptions.

### Backstop Inventory / Unwind Intelligence

Forced-Flow currently distinguishes:

`MARKET_LIQUIDATION -> BACKSTOP_ABSORPTION -> ADL`.

V6.6 extends the state machine beyond absorption:

```text
NO_BACKSTOP
-> BACKSTOP_ABSORPTION
-> INVENTORY_HELD
-> INVENTORY_UNWINDING
-> INVENTORY_CLEARED
```

with `UNKNOWN` whenever public evidence is incomplete.

For a verified protocol/liquidator vault or equivalent backstop actor, maintain where publicly observable:

- absorbed coin;
- signed absorbed size/notional;
- absorption timestamp;
- protocol/vault identity provenance;
- remaining inventory;
- inventory age;
- subsequent unwind fills;
- unwind participation;
- funding carried during inventory;
- price impact during unwind;
- inventory half-life;
- concurrent depth/liquidity;
- concurrent liquidation activity;
- subsequent ADL state.

#### Backstop candidate sleeves

Test independently:

- **post-backstop continuation:** remaining inventory creates persistent same-direction pressure;
- **absorption relief:** transfer to the backstop removes visible forced flow and stabilizes price;
- **inventory unwind:** backstop exit creates later pressure or reversal;
- **inventory-overhang filter:** avoid or resize entries while material verified backstop inventory remains;
- **cross-asset backstop stress:** simultaneous absorbed inventory across many markets indicates systemic fragility;
- **inventory-cleared transition:** liquidity/markout changes after verified inventory materially clears.

No direction is assumed a priori.

### Backstop provenance

An address is classified as protocol/backstop only when supported by:

- official documentation/state;
- official vault relationship;
- or reproducible first-party/on-chain evidence.

Do not classify a profitable wallet as HLP/backstop based on behavior alone.

Report separately:

- open-book liquidation edge;
- backstop-absorption edge;
- backstop-inventory/unwind edge;
- ADL edge.

One parent cascade/backstop episode remains one clustered dependency for effective-sample accounting.

### Versioned Large-Liquidation Mechanics

Hyperliquid liquidation behavior can be size-dependent.

Where applicable and valid for the historical rule version, replay:

- liquidation threshold/rule;
- large-position threshold;
- staged fraction sent to the book;
- cooldown;
- cross vs isolated semantics;
- mark-price inputs;
- backstop threshold;
- ADL semantics.

Current rules must not be applied blindly to older history.

### Portfolio-Margin / Collateral Forced Flow

As unified/portfolio-margin mechanics expand, classify forced flow by source where public evidence permits:

- ordinary perp liquidation;
- isolated perp liquidation;
- cross-margin liquidation;
- collateral/borrow liquidation;
- portfolio-margin collateral liquidation;
- backstop transfer;
- ADL.

Collateral liquidation may create forced spot/collateral flow even when a perp price did not initiate the stress.

This state may condition Forced-Flow and Relative Value but does not become a separate module without independent evidence.

### V6.6 research basis

High-signal sources supporting V6.6 include:

- **Hyperliquid official L1 data schemas:** raw book diffs expose per-order add/update/remove information with order and public-user identifiers;
- **Hyperliquid official order-book documentation:** price-time and transaction ordering define the causal matching rules that queue replay must respect;
- **Hyperliquid official historical-data documentation:** archive families and node-derived data have different availability and storage profiles, motivating bounded event-window acquisition;
- **public Hyperliquid L4 reconstruction projects/providers:** demonstrate deterministic order-level reconstruction and explicitly distinguish L4 queue truth from aggregated L2;
- **Hyperliquid official liquidation documentation:** liquidation starts on the book, can escalate to the liquidator vault, and includes size-dependent staged mechanics;
- **public forensic liquidation work:** separates market liquidation, backstop absorption and ADL, motivating an additional inventory-aftermath state rather than ending analysis at absorption.



### Profitability Convergence V6.7 — HIP-4 outcome relative value

The saturation pass identified one genuinely independent opportunity family outside ordinary perpetuals: **HIP-4 outcome markets**.

HIP-4 outcomes are fully collateralized contracts with bounded settlement. They introduce non-linear, dated payoff structures that are economically different from perps, funding carry, spot/perp basis and ordinary market making.

V6.7 treats HIP-4 as a **candidate relative-value/event-derivatives family**, not as an automatic production module.

### Outcome semantic contract

For every outcome instrument store point-in-time:

- outcome id;
- side ids/names;
- question id where applicable;
- encoded contract description;
- underlying;
- target/threshold(s);
- expiry/settlement timestamp;
- settlement price/source;
- interpolation/rounding rule;
- quote token;
- settleFraction domain;
- deployer;
- fee scale;
- question/fallback structure;
- split/merge/negate capabilities;
- market status;
- specification revision.

No two outcome contracts are considered equivalent because their labels look similar.

Cross-venue equivalence requires matching:

- underlying;
- strike/threshold;
- settlement timestamp/timezone;
- settlement data source;
- interpolation/rounding;
- payout definition;
- cancellation/invalid-market rules;
- quote/collateral currency;
- settlement finality.

### Candidate Sleeve 1 — Internal YES/NO Parity

For a binary outcome whose complementary sides settle to one unit of quote value in total, test executable parity relationships such as:

```text
ask_yes + ask_no + all_costs < settlement_pair_value
```

or the symmetric unwind relationship where executable bids exceed the recoverable combined value.

Where protocol split/merge operations are available, compare:

- direct book execution;
- split then sell one/both legs;
- buy complementary legs then merge;
- hold-to-settlement;
- NO_TRADE.

Requirements:

- use current/historical fee semantics;
- maker rebates are never assumed where outcome rules do not provide them;
- split/merge actions are modeled only when actually available for the contract/version;
- quote-token conversion costs are explicit;
- capital lock/time-to-expiry is explicit;
- no theoretical parity edge is credited if operational actions cannot realize it in the paper model.

### Candidate Sleeve 2 — Multi-Outcome / Question Parity

For mutually exclusive exhaustive question outcomes, test whether the executable price set violates the protocol's settlement identities.

Potential structures include:

- sum-of-YES parity;
- NO/negate relationships;
- complete-set merge;
- fallback-outcome consistency.

Every relationship is generated from official question metadata rather than hard-coded assumptions.

The solver should build a small payoff matrix:

```text
state x instrument -> payout
```

and search for bounded-cost portfolios whose terminal payout dominates their entry cost across all valid states.

This is a deterministic payoff check first, economic trade candidate second.

Fees, liquidity, action costs and capital-time can eliminate a theoretical arbitrage.

### Candidate Sleeve 3 — Cross-Venue Outcome Parity

When the **same economically defined event** trades on another venue, build a semantic-compatibility edge between contracts.

Candidate venues may include public prediction/outcome CLOBs such as Polymarket or Kalshi where access/data terms permit research.

For each paired event store:

- semantic equivalence score;
- settlement-source equivalence;
- expiry difference;
- payout-currency basis;
- fee model;
- executable BBO/depth;
- venue health;
- settlement/counterparty haircut;
- transfer/collateral fragmentation;
- data latency.

Research:

- direct cross-venue binary spread;
- maker on one outcome venue / hedge on another;
- convergence as expiry approaches;
- venue-specific participant-flow lead-lag.

No "risk-free arbitrage" label is allowed unless payoff equivalence is exact across all settlement states and every execution/settlement cost is included.

### Candidate Sleeve 4 — Outcome ↔ Perp / Options Parity

Recurring price outcomes create a direct relationship between:

- current underlying/perp price;
- threshold;
- time to expiry;
- expected volatility/distribution;
- outcome-implied probability.

For BTC/crypto price outcomes, test fair-value challengers in increasing sophistication:

1. simple empirical return distribution;
2. realized-volatility distribution;
3. regime-conditioned distribution;
4. perp/order-flow conditioned distribution;
5. options-implied distribution from certified Deribit/options features;
6. ensemble calibrated strictly on TRAIN.

The outcome market price is compared to a **probability distribution**, not to the perp price linearly.

Candidate features:

- distance-to-strike in volatility units;
- time-to-expiry;
- implied binary probability;
- outcome-vs-model residual;
- YES/NO microprice;
- perp microprice/OFI;
- options risk reversal/skew;
- realized vs implied volatility;
- scheduled funding/TWAP/forced-flow state;
- settlement-source mark/oracle dynamics.

Rules:

- Black-Scholes/digital formulas are baselines, not truth;
- crypto returns are not assumed lognormal;
- options-derived distributions require point-in-time surfaces;
- delta hedging costs/turnover are explicit if a hedge is part of the strategy;
- near-expiry models must account for settlement interpolation/source mechanics exactly;
- no future settlement mark is visible before settlement.

### Settlement-Window Specialist Lane

Known settlement times create a specialized event window.

Track:

- time-to-settlement;
- settlement-source update cadence;
- last pre-settlement source observation;
- first post-settlement source observation;
- interpolation inputs where the contract uses them;
- outcome-book spread/depth;
- perp/spot volatility;
- probability sensitivity to a small underlying move.

Test:

- price-discovery lead-lag between outcome and perp;
- late repricing delay;
- liquidity withdrawal near expiry;
- over/underreaction after a large underlying move;
- post-settlement residual/cleanup only where contracts continue to expose tradable state.

Because edge half-life may become extremely short near settlement, GitHub-hosted latency limitations must be applied honestly. A discovered theoretical edge that requires unavailable sub-second execution remains `UNEXECUTABLE`.

### Outcome Fee / Rule Versioning

HIP-4 fee and market rules are versioned state.

For every replay window preserve:

- base outcome trading fee;
- deployer fee scale;
- open/close/burn/settlement fee semantics;
- maker rebate policy;
- quote token;
- minimum trade/notional;
- outcome action availability.

Current announcements or current documentation cannot be back-applied to earlier outcome periods.

### Outcome module relationship

HIP-4 research does not create an isolated architecture silo.

It reuses:

- Venue Health;
- Dynamic Cost State;
- Execution Truth;
- Cross-Venue Route Graph;
- Options/Volatility Intelligence;
- Lead-Lag;
- Cross-Module Intent Netting;
- deterministic replay;
- OOS/forward gates.

Initial state:

`DISCOVERY_ONLY -> MEASURE_ONLY -> G3/G4 CANDIDATE`.

### HIP-4 promotion standard

A HIP-4 sleeve can be promoted only if:

- contract semantics are machine-verified;
- point-in-time outcome metadata is retained;
- execution books are replay-grade;
- all fee/settlement/collateral costs are modeled;
- effective independent event count is sufficient;
- frozen OOS economics are positive;
- capacity and capital-time contribution can matter toward the +4 USD/day milestone;
- edge does not rely on unavailable latency.

### V6.7 research basis

High-signal sources supporting V6.7 include:

- **Hyperliquid official HIP-4 documentation:** outcomes are fully collateralized bounded-settlement contracts with complementary side payouts and staged support for questions/multiple outcomes;
- **Hyperliquid official outcomeMeta / settledOutcome APIs:** expose machine-readable point-in-time outcome specifications and settlement information;
- **Hyperliquid official contract specifications:** recurring price outcomes define exact threshold, expiry and mark-price settlement mechanics, including interpolation;
- **Hyperliquid official deployer/action docs:** split/merge/negate and fee-scale semantics create protocol-native parity relationships that must be modeled exactly;
- **public HIP-4 codebases:** independently converge on three research mechanisms — outcome market making, cross-venue event relative value and underlying/perp parity — but their profitability claims are not imported into Alina.



### Profitability Convergence V6.8 — rule, coverage and observability completeness

V6.8 captures low-level venue rules and data-coverage limits that can create false edge, false completeness or avoidable friction even when the higher-level strategy logic is correct.

Core rule:

> **a paper trade is admissible only if it could have been a valid order under the point-in-time venue rules and if the evidence used to justify it was actually observable with the recorded coverage.**

### Hyperliquid precision / validity contract

For each instrument version, store at least:

- `szDecimals`;
- effective tick / price precision;
- lot/size increment;
- minimum notional;
- max leverage;
- margin table / margin tier;
- margin mode;
- collateral token;
- delisted flag;
- growth-mode state;
- DEX/deployer identity.

Current documented Hyperliquid validity rules include:

- price up to 5 significant figures;
- perps: no more than `6 - szDecimals` decimal places;
- spot: no more than `8 - szDecimals` decimal places;
- integer prices are always allowed even when they exceed five significant figures;
- size must conform to `szDecimals`.

Paper-order construction must:

1. compute intended economic price/size;
2. normalize to the venue-valid representation;
3. record normalization/rounding delta;
4. recompute expected edge/cost after normalization;
5. reject if the normalized order no longer clears the gate.

Never credit favorable rounding silently.

### Exact order-status / rejection taxonomy

Preserve venue reason rather than only a generic terminal state.

Hyperliquid states to retain include when observed:

- `open`;
- `filled`;
- `canceled`;
- `triggered`;
- `rejected`;
- `marginCanceled`;
- `vaultWithdrawalCanceled`;
- `openInterestCapCanceled`;
- `selfTradeCanceled`;
- `reduceOnlyCanceled`;
- `siblingFilledCanceled`;
- `delistedCanceled`;
- `liquidatedCanceled`;
- `scheduledCancel`;
- `tickRejected`;
- `minTradeNtlRejected`;
- `perpMarginRejected`;
- `reduceOnlyRejected`;
- `badAloPxRejected`;
- `iocCancelRejected`;
- `badTriggerPxRejected`;
- `marketOrderNoLiquidityRejected`;
- `positionIncreaseAtOpenInterestCapRejected`;
- `positionFlipAtOpenInterestCapRejected`;
- `tooAggressiveAtOpenInterestCapRejected`;
- `openInterestIncreaseRejected`;
- `insufficientSpotBalanceRejected`;
- `oracleRejected`;
- `perpMaxPositionRejected`;
- unknown/unmapped future statuses.

Status-frequency features may be researched only after separating mechanical venue constraints from informational market state.

### Self-trade prevention detail

Hyperliquid self-trade prevention cancels the resting order when the same address would trade against itself; no ordinary trade is created and no normal trade fee is charged.

Therefore:

- Portfolio Intent Netting should remove avoidable same-address opposing intents before paper execution;
- if a same-address cross still occurs under the tested policy, simulate self-trade prevention rather than two fills;
- `selfTradeCanceled` is excluded from aggressor/trade-flow volume;
- subaccounts are treated as separate account identities unless an explicit rule proves otherwise.

### Trigger-order observability

For any queried public user, `frontendOpenOrders` can expose point-in-time trigger metadata including:

- `isTrigger`;
- `triggerPx`;
- `triggerCondition`;
- order type;
- `reduceOnly`;
- `isPositionTpsl`;
- current/original size.

Hyperliquid TP/SL documentation states the **mark price** is the trigger reference.

Rules:

- trigger activation and resulting execution are separate events;
- a visible TP is not liquidation pressure;
- tracked-wallet trigger maps are lower-bound/sample maps;
- global completeness requires certified market-wide L4/order evidence;
- every trigger map stores wallet/source coverage and freshness.

### Wallet-monitoring coverage budget

Official WebSocket limits currently include:

- maximum 10 connections;
- maximum 30 new connections/minute;
- maximum 1000 subscriptions;
- maximum **10 unique users across user-specific WebSocket subscriptions**.

Copy-Vault / trigger-map tracking therefore uses tiers:

- `HOT_WS`;
- `WARM_REST`;
- `COLD_DISCOVERY`;
- `ARCHIVE_OR_REMOTE_ORDER_SOURCE` when approved.

Per wallet store:

- observation method;
- cadence;
- staleness;
- gaps;
- rate-cost;
- reason for tier;
- coverage confidence.

No report may label hundreds of wallets as live user-WS tracked under a 10-user documented limit.

### Historical retention and censoring

Official API limits include:

- `historicalOrders`: at most 2000 most recent historical orders;
- `userFills`: at most 2000 most recent fills;
- `userFillsByTime`: at most 2000 fills per response and only the 10,000 most recent fills are accessible through that API family.

Therefore:

- high-activity wallets require ongoing capture before API history rolls off;
- reaching a cap is a censoring warning, not completeness proof;
- record `coverage_start`, `coverage_end`, rows, pages, cursor progress and `possibly_truncated`;
- restore older history only from a certified archive/order source;
- leader scoring discounts or rejects materially censored windows.

### Snapshot / reconnect contract

For streams that emit bootstrap snapshots:

- persist `isSnapshot` where provided;
- record connection/session and bootstrap timestamp;
- deduplicate already-committed snapshot rows;
- reconcile missed intervals with matching read-only info endpoints where possible;
- keep source state `RECOVERING` until reconciliation completes;
- never count snapshot bootstrap as fresh event frequency.

### L2 order-count metadata

Preserve the L2 level `n` field when available.

Possible uses:

- order-count / depth ratio;
- visible average order size;
- queue fragmentation;
- refill/cancel intensity;
- calibration against selective L4 windows.

It cannot create an exact queue-ahead claim without stronger order-level evidence.

### Predicted funding as first-class causal input

Hyperliquid officially exposes `predictedFundings` for the first perp DEX, returning per coin/venue:

- predicted `fundingRate`;
- `nextFundingTime`.

Store:

`observed_at, coin, venue_label, predicted_rate, next_funding_time, source_version`.

Research:

- forecast error to realized funding;
- revision velocity;
- cross-venue predicted-funding dispersion;
- basis response before settlement;
- incremental Relative-Value admission value.

Rules:

- never reconstruct missing predictions from finally realized funding;
- unsupported HIP-3 DEXs remain missing;
- compare Alina forecasts against persistence and exchange-predicted baselines.

### Asset-context detail

Where point-in-time asset context exposes:

- `impactPxs`;
- `premium`;
- `oraclePx`;
- `markPx`;
- `midPx`;
- `openInterest`;
- `funding`;

store values plus nullability/freshness.

Use as:

- fast liquidity sanity check;
- mark/oracle/mid divergence;
- funding/premium regime;
- OI state;
- cross-check against reconstructed depth.

Do not substitute `impactPxs` for certified L2/L4 depth in final capacity proof.

### Open-order / action feasibility

Even in paper mode, quote-heavy strategies must report whether their hypothetical behavior fits venue constraints.

Track:

- simulated open-order count;
- trigger/reduce-only count;
- orders/minute;
- cancels/minute;
- modifies/minute;
- quote layers per instrument.

Current Hyperliquid rules include an open-order allowance that scales with volume up to a capped maximum, with special rejection behavior for trigger/reduce-only orders at high counts.

A paper strategy requiring impossible action/open-order throughput is `EXECUTION_INFEASIBLE`.

### Scheduled cancel / dead-man semantics

Schedule-cancel/dead-man behavior is safety, not alpha.

Model only as:

- orphan-quote protection;
- source of `scheduledCancel`;
- feasibility/safety state.

### Portfolio-margin / unified-account state

Hyperliquid supports account abstraction states including classic/disabled, unified account and portfolio margin.

This can change:

- collateral efficiency;
- cross spot/perp PnL offsets;
- borrowing;
- liquidation distance;
- capital fragmentation;
- spot-perp carry feasibility.

Relative-Value reports therefore store assumed account mode.

Rules:

- do not credit PM efficiency to classic mode;
- PM scenarios version collateral eligibility, LTV/borrow and margin semantics;
- report conservative classic-account economics alongside PM economics when both are relevant;
- account mode changes capital efficiency, not underlying signal alpha.

### Canonical instrument identity

Preserve separately:

- canonical HyperCore/L1 identifier;
- DEX namespace;
- spot `@index` where applicable;
- UI/display symbol;
- economic-underlying id.

Do not join datasets solely on ticker text because UI remappings can differ from L1 names.

### L4 source-availability state

Selective L4 from V6.6 records:

- `OFFICIAL_NODE_DERIVED`;
- `CERTIFIED_REMOTE_L4`;
- `THIRD_PARTY_UNVERIFIED`;
- `UNAVAILABLE`.

The standard official historical S3 archive does **not** imply complete historical L4.

Any remote L4 source records:

- coverage dates;
- markets;
- snapshot availability;
- diff gaps;
- retention;
- schema/version;
- provider transformations.

### Rule-change regression suite

Whenever venue metadata/rules change, rerun bounded fixtures for:

- price normalization;
- size normalization;
- GTC/IOC/ALO;
- reduce-only;
- trigger behavior;
- OI-cap rejection;
- margin-tier rejection;
- delisting;
- self-trade prevention;
- fee calculation;
- priority semantics.

### V6.8 proof-report fields

Execution-sensitive lanes additionally report:

- invalid-order rejection rate;
- normalization-loss bps;
- unknown/unmapped status count;
- API/history truncation flags;
- wallet observation-tier distribution;
- reconnect repair count;
- predicted-funding coverage;
- metadata/rule-version coverage;
- account abstraction/margin mode;
- L2/L4 evidence tier.

A material UNKNOWN/truncated field that affects economics prevents the lane from being labeled fully measured.

### V6.8 research basis

This layer is grounded primarily in current official Hyperliquid documentation for tick/lot size, order statuses/errors, self-trade prevention, WebSocket/user limits, history caps, snapshots, predicted funding, perp metadata, portfolio margin and node/L4/historical-data boundaries.

Public bot/framework sources only determined which edge cases deserved inspection; official venue rules control final semantics.



### Profitability Convergence V6.9 — protocol-mechanics edge cases

V6.9 converts newly verified protocol mechanics into explicit point-in-time state so they cannot silently distort PnL, capacity or forced-flow research.

### Open-interest-cap constraint lane

Hyperliquid exposes a read-only `perpsAtOpenInterestCap` query, scoped by DEX.

Maintain:

- whether the instrument is currently at OI cap;
- DEX-level and per-asset cap state where documented;
- cap type: notional / size;
- current OI;
- cap value when available;
- rejection/cancel counts caused by cap;
- distance/time since entering cap state;
- time since leaving cap state.

Candidate hypotheses:

- one-sided positioning constraint;
- basis/funding distortion near cap;
- asymmetric rejection flow;
- post-cap-release normalization.

Rules:

- OI cap is a market constraint, not automatically an alpha signal;
- `positionIncreaseAtOpenInterestCapRejected`, `positionFlipAtOpenInterestCapRejected`, `tooAggressiveAtOpenInterestCapRejected` and `openInterestIncreaseRejected` remain distinct;
- HIP-3 cap configuration is versioned per deployer/DEX.

### Growth-mode / deployer-fee exactness

HIP-3 fee economics depend on:

- user fee tier;
- maker/taker rate;
- referral/staking discount where applicable;
- deployer fee scale;
- aligned quote-token treatment;
- growth-mode state.

Growth mode and deployer fee scale materially alter all-in fees, rebates, volume contribution and user action-limit contribution.

Requirements:

- version `growthMode`, deployer fee scale and change timestamp;
- do not use a validator-operated-perp fee schedule on HIP-3 without adjustment;
- do not credit a maker rebate or discount unavailable to the modeled account;
- growth-mode cooldown/rule changes are treated as venue-rule events.

### Contract-capacity limits

Point-in-time contract specifications may impose maximum order values.

For validator-operated Hyperliquid perps, current documentation links maximum market-order value to max-leverage bucket and sets maximum limit-order value as a multiple of the market-order cap.

The capacity engine therefore takes:

`min(certified_depth_capacity, venue_order_cap, margin_capacity, risk_capacity)`.

If a desired notional exceeds the venue cap:

- split only if allowed by strategy timing/alpha half-life/action limits;
- otherwise reduce capacity;
- never assume one impossible giant order.

### Funding mechanics exactness

For standard Hyperliquid perps, current documentation states:

- funding is paid hourly;
- the 8-hour formula is converted to hourly payment;
- premium is sampled every 5 seconds and averaged over the hour;
- funding uses a fixed interest component plus clamped premium component;
- funding is capped per hour;
- payment notional uses **oracle price**, not mark price;
- impact bid/ask prices are derived at a contract-specific impact notional.

Current impact-notional defaults documented for validator-operated perps include larger impact notional for BTC/ETH than other assets.

Store/version:

- funding formula version;
- sampling cadence;
- funding cap;
- interest component;
- impact notional;
- oracle source;
- next settlement time;
- HIP-3-specific premium formula/multiplier when applicable.

Predicted funding research must reconstruct only from inputs knowable before settlement.

### Quanto / collateral-basis nuance

Validator-operated Hyperliquid perps can reference a USDT-denominated oracle while collateral/PnL accounting is in USDC without applying a live USDC/USDT conversion in the contract itself.

Therefore Relative Value and collateral-risk reports must distinguish:

- underlying price basis;
- USDT reference;
- USDC collateral;
- USDC/USDT market basis;
- collateral haircut/portfolio-margin effect.

Do not call such structures perfectly fiat-neutral during stablecoin stress.

### Liquidation mechanics exactness

Forced-Flow V2 must version the actual liquidation rules.

Current documented behavior includes:

- maintenance margin depends on maximum leverage/margin tier;
- positions are first attempted against the book;
- sufficiently large liquidatable positions may initially send only a fraction of the position to market;
- after partial liquidation, a cooldown can alter subsequent liquidation sizing;
- cross and isolated positions use different margin-available definitions;
- margin tiers alter maintenance leverage at larger notional.

Store:

- liquidation-rule version;
- cross/isolated/portfolio-margin mode;
- margin tier;
- threshold for partial-liquidation treatment;
- initial liquidation fraction;
- cooldown duration;
- actual book liquidation fraction;
- residual position;
- backstop/ADL transition.

Current values are versioned inputs, never timeless constants.

### ADL-risk state

Hyperliquid ADL ranks opposite-side profitable traders using profitability/leverage-related state.

Where the required public/account evidence is available, paper risk can estimate:

- whether a position lies in a high-ADL-risk cohort;
- unrealized PnL;
- effective leverage;
- current ADL environment / cascade severity.

Rules:

- ADL probability is not invented when queue/rank inputs are unavailable;
- forced close due to ADL is a distinct execution/risk event;
- ADL risk affects capacity/risk, not raw signal alpha.

### Portfolio-margin liquidation mechanics

Portfolio margin is not just a fee/capital-efficiency toggle.

Version where applicable:

- eligible collateral;
- LTV;
- liquidation threshold;
- borrow cap;
- supply cap;
- borrow oracle;
- minimum borrow offset;
- portfolio maintenance requirement;
- portfolio liquidation value;
- portfolio margin ratio.

Current documentation indicates liquidation eligibility is based on a portfolio margin ratio threshold and that liquidation ordering across spot borrows/perps may depend on oracle update ordering.

Therefore:

- do not assume deterministic liquidation order under PM;
- capital-efficiency simulations include borrow/collateral constraints;
- PM carry/relative-value reports include collateral price and borrow-cap stress.

### TWAP V2 mechanics

Scheduled Flow research incorporates current native TWAP behavior when applicable:

- running time can span from minutes to multiple days;
- child interval has a documented lower bound;
- child size may be randomized;
- child orders have a bounded slippage tolerance;
- optional trigger price can activate the parent based on mark price;
- optional max/min price can terminate the parent;
- minimum parent notional applies.

For each observed/replayed TWAP state, preserve whichever fields are actually exposed by the source.

Do not infer private/unstored parent constraints when the public read-only source omits them.

### Chase-order provenance

The Hyperliquid frontend now offers Chase orders that repeatedly reprice a post-only order near the touch and are browser-managed.

Treat Chase-like order activity as:

- execution/order-management behavior;
- possible flow-provenance feature;
- repeated ALO modify/cancel activity.

Do not create a standalone Chase alpha module.

If order-level data cannot reliably identify Chase provenance, label it `CHASE_LIKE` rather than exact Chase.

### Protocol-change event ledger expansion

Add point-in-time events for:

- OI cap change;
- margin table change;
- leverage change;
- growth-mode change;
- deployer-fee change;
- funding formula/multiplier change;
- order-value cap change;
- portfolio-margin parameter change;
- TWAP/order-type feature change.

Every affected replay window references the rule revision.

### V6.9 proof-report fields

Relevant lanes additionally report:

- OI-cap occupancy %;
- OI-cap rejection counts;
- fee/growth-mode version coverage;
- order-cap binding frequency;
- funding formula/input coverage;
- oracle-vs-mark funding-notional consistency;
- partial-liquidation/cooldown events;
- ADL events/unknown-ADL-risk fraction;
- PM collateral/LTV/borrow-cap coverage;
- TWAP parent-rule coverage.



### Profitability Convergence V6.10 — options volatility relative value

The final corpus-saturation pass identified one remaining economically independent research family that should not remain only a contextual feature layer: **direct crypto-options volatility relative value**.

The existing Options / Volatility Intelligence layer remains useful as context for perp strategies. V6.10 adds a separate candidate family in which the option structure itself is the economic position.

Initial research should reuse existing Deribit/data-normalization components where possible.

### Point-in-time option instrument contract

For every option instrument used in evidence, retain:

- venue;
- underlying/index;
- call/put;
- strike;
- expiry;
- contract size/unit;
- quote and settlement currency;
- settlement source/rule;
- instrument state;
- best bid/ask and executable size;
- deeper book when required by candidate notional;
- mark price;
- bid IV / ask IV / mark IV where available;
- point-in-time delta/gamma/theta/vega/rho where available;
- independently computed reference greeks/model inputs where used;
- open interest;
- volume;
- underlying future/index reference;
- fee schedule;
- margin/account model;
- data timestamp and freshness.

**Mark price and mark IV are state/reconciliation inputs, not executable fills.**

### Options collection tiers

The full options chain can be computationally and bandwidth expensive.

Use V5-style tiers:

- **COLD:** instrument metadata, lifecycle, coarse chain summaries;
- **WARM:** selected expiries/deltas, top executable quotes, OI/volume, IV/greeks;
- **HOT:** full required executable depth for candidate legs and hedge instruments.

Promotion into WARM/HOT may use:

- liquidity/spread;
- OI/volume;
- time to expiry;
- surface residual;
- expected edge-to-friction;
- relevance to HIP-4/perp regimes.

Do not subscribe to raw full depth for every strike/expiry without measured value.

### Volatility surface evidence contract

Maintain the distinction between:

- executable bid surface;
- executable ask surface;
- mark/model surface.

Candidate surface methods can include:

- strike/delta bucket interpolation;
- SVI/SSVI challengers;
- local non-parametric baselines.

If a surface is described as arbitrage-free, validate the relevant constraints, including:

- butterfly/convexity consistency;
- calendar/total-variance consistency where applicable.

Store:

- fit error;
- stale/missing strike flags;
- quote width;
- fit timestamp;
- calibration universe;
- parameter/version hash.

A smooth surface is never evidence that an executable arbitrage exists.

### Sleeve A — Volatility Risk Premium / IV versus realized volatility

Test long/short volatility structures conditional on the difference between option-implied volatility and a causal realized-volatility forecast.

Possible structures:

- delta-neutral straddle;
- delta-neutral strangle;
- defined-risk spread;
- long-volatility structure during compressed IV regimes;
- short-volatility structure only under explicit jump/tail controls.

Economic decomposition:

```text
expected_net_vol_edge
= option_repricing_or_decay
  + gamma_scalping_value
  - option_bid_ask
  - option_fees
  - delta_hedge_spread_slippage
  - perp/future_funding_or_basis
  - jump_tail_loss_expectation
  - margin_and_capital_time
```

The rule is **not** `IV > RV => SHORT_VOL`.

Required stress:

- discontinuous jumps;
- volatility clustering;
- sudden skew change;
- liquidity withdrawal;
- funding inversion;
- near-expiry gamma acceleration.

### Sleeve B — Calendar / term-structure relative value

Test relative implied variance across expiries.

Candidate structures:

- rich near-term versus cheaper longer-term variance;
- reverse calendars during inversion;
- event-expiry kinks;
- term-structure convergence/repricing.

Measure rather than assume:

- net delta;
- vega mismatch;
- theta mismatch;
- gamma mismatch;
- event exposure;
- roll/close friction.

### Sleeve C — Skew / risk-reversal / butterfly relative value

Test dislocations in:

- 25-delta risk reversal;
- 10-delta tail skew where liquid;
- butterflies;
- wing-versus-ATM richness;
- skew term structure.

Every candidate specifies exact executable legs, ratios and residual greeks.

A chart anomaly is not an edge.

### Sleeve D — Transaction-cost-aware gamma / delta hedging

Compare hedge policies:

- fixed-time hedge;
- fixed absolute-delta threshold;
- volatility-scaled threshold;
- transaction-cost-aware no-trade band;
- regime-adaptive band;
- close/no-hedge baseline.

Track:

- hedge turnover;
- spread/slippage;
- hedge fees;
- funding/basis;
- residual delta;
- gamma capture;
- timing error.

Near expiry, reject a candidate when theoretical gamma capture is consumed by hedge friction.

### Sleeve E — Executable surface / synthetic consistency

Test only realizable structures such as:

- put/call or synthetic-forward consistency when contract semantics support it;
- executable butterfly convexity violations;
- executable calendar total-variance violations;
- option/future forward inconsistency;
- option-implied distribution versus HIP-4 outcome probabilities.

A model residual becomes a candidate only after constructing a bounded-risk executable portfolio.

Include:

- every leg's bid/ask;
- fees;
- legging risk;
- margin;
- settlement/currency basis;
- hedge cost;
- capital time.

### Options PnL attribution

Paper reports must decompose:

- option entry/exit premium;
- option spread/fees;
- delta-hedge PnL;
- hedge spread/fees/slippage;
- funding/basis;
- gamma contribution;
- theta;
- vega/IV move;
- skew/surface move;
- residual directional delta;
- settlement/expiry;
- margin/capital-time cost.

Reject a claimed volatility edge when most of the result came from unintended directional underlying exposure.

### Options margin/stress

Convex derivatives cannot use a simplistic flat notional margin assumption when that changes capacity or liquidation risk.

Where exact historical account/portfolio-margin rules are available, version them.

Otherwise use conservative scenario stress and label the result `MODELLED_MARGIN/UNCERTAIN`.

Stress dimensions should include where relevant:

- underlying shock;
- IV shock;
- skew shock;
- correlated leg move;
- expiry compression;
- hedge dislocation.

### Deribit data efficiency and causality

For Deribit-style option chains:

- seed/refresh instrument universe from official public instrument metadata;
- use lifecycle/state updates where available rather than wasteful full polling;
- prefer efficient chain-wide mark/IV summaries for COLD/WARM observation;
- request deeper books only for HOT candidate legs;
- preserve exchange timestamps/freshness;
- reconcile point-in-time chain state after reconnects.

Public greeks and mark IV are acceptable observable features, but any Alina-computed model must record its exact convention and inputs.

### HIP-4 / options / perp bridge

V6.10 directly strengthens V6.7.

For a HIP-4 price-threshold outcome:

- options can provide a market-implied distribution;
- futures/perps provide forward/basis and delta-hedge references;
- HIP-4 provides an observed bounded-event probability.

Cross-instrument comparison requires exact alignment of:

- underlying;
- threshold;
- expiry;
- settlement source/rule;
- time convention.

No options observation after the HIP-4 decision timestamp may enter the probability estimate.

### Chase-order experimental completion

V6.9 already classifies Chase as execution/provenance behavior.

V6.10 adds the missing economic benchmark requirement when replayability permits:

compare the same causal opportunity under:

- static ALO;
- ALO + timeout/cancel-replace;
- Chase/CHASE_LIKE;
- IOC/taker;
- NO_TRADE.

Measure:

- maker fill probability;
- completion time;
- repricing count;
- queue loss/reset uncertainty;
- partial-fill path;
- spread captured;
- post-fill adverse-selection markout;
- missed-alpha cost.

If historical repricing/queue semantics are insufficiently observable, Chase remains descriptive/`UNMEASURABLE` for certification.

### Saturation classifications

The final long-tail sweep classifies repeated public-bot ideas as follows unless later evidence demonstrates a materially independent mechanism:

- triangular/graph arbitrage -> existing route graph / Relative Value;
- stablecoin quote-basis -> Collateral Risk + Relative Value;
- HLP/vault deposits/withdrawals -> Copy-Vault / Backstop context;
- liquidation-conditioned passive liquidity provision -> Forced-Flow + Execution Alpha, not a separate module;
- Hawkes/self-exciting event-intensity models -> order-flow/Forced-Flow feature family unless independent OOS economics appear;
- basket/index/constituent dispersion -> Cross-Instrument Relative Value or Options Volatility sleeve, not a duplicate engine;
- on-chain exchange/bridge/stablecoin flows -> Lead-Lag/regime/context features with explicit observation latency and entity-label uncertainty;
- native order types such as Chase -> Execution Alpha;
- pre-execution/split-client-block observability -> `WATCHLIST/UNMEASURABLE` unless a GitHub/cloud-compatible read-only source becomes replayable without a self-hosted node;
- generic grid/martingale/DCA -> not a first-class module;
- generic RSI/MACD/indicator bots -> baselines;
- generic AI/LLM directional agents -> not a distinct economic edge;
- sentiment/social data -> contextual challenger only;
- Kelly -> sizing only after edge proof.

The public-bot research program remains open, but after this corpus pass the **novel high-signal mechanism yield is now low and mostly maps into existing architecture**. New first-class architecture still requires the V6.4 novelty test.

### V6.10 research basis

High-signal support for V6.10 includes:

- **Deribit official public APIs:** public option books/tickers expose executable quotes, IV, greeks, OI and instrument state suitable for read-only point-in-time research;
- **Deribit official options data-collection guidance:** recommends chain-wide efficient feeds and selective escalation to deeper books rather than brute-force full-depth subscription across the entire chain;
- **public crypto-options research codebases:** independently converge on IV/RV, calendar, skew/surface and delta-hedging-band research patterns, but their reported performance remains unverified hypothesis input;
- **Hyperliquid official Chase documentation/announcement:** Chase is a native post-only repricing mechanism and therefore belongs in Execution Alpha benchmarking, not strategy alpha.



### Profitability Convergence V6.11 — event identity and feed semantics

The corpus red-team found one remaining cross-cutting failure mode capable of corrupting several modules simultaneously: **treating exchange messages as if one row always equals one independent market event and as if similarly named fields have identical semantics across venues**.

V6.11 introduces a source-semantic contract before any normalized event can reach Hawkes/OFI, Lead-Lag, Forced-Flow, execution simulation or PnL accounting.

### Canonical event identity

Every raw/normalized event carries, where available:

- venue;
- market / canonical instrument id;
- source channel;
- source message/event type;
- source-native unique id;
- parent/aggregate id;
- first/last child trade ids where provided;
- order id / client order id where relevant;
- source sequence/update id;
- block/transaction index where relevant;
- exchange timestamp;
- local receive monotonic timestamp;
- ingest session / stream epoch;
- raw payload hash;
- live/backfill/archive provenance.

A normalized row never invents an id when the source provides none. It instead uses an explicitly weaker composite identity with collision risk recorded.

### Trade and sweep de-fragmentation

Different trade feeds represent different event grains.

For Binance futures, official aggregate-trade semantics group market trades associated with **one taker order** in the aggregation window and expose:

- aggregate trade id;
- first raw trade id;
- last raw trade id;
- buyer-maker flag.

Therefore:

- an `aggTrade` row is not treated as one arbitrary raw match;
- `firstTradeId..lastTradeId` is preserved;
- raw trades and aggTrades for the same venue/time cannot both contribute full notional to the same signal without explicit de-overlap;
- a market sweep represented by several child fills is clustered before event-count/Hawkes calibration when the source semantics support that reconstruction;
- sweep fragmentation sensitivity is reported for event-intensity features.

Public crypto Hawkes research shows that sub-millisecond child-fill fragmentation can severely distort goodness-of-fit and apparent self-excitation. Sweep aggregation therefore becomes a mandatory challenger for Hawkes/event-intensity research, not an optional cosmetic cleanup.

### Aggressor / maker-side semantics

Every venue adapter declares the exact meaning of its side fields.

Examples:

- Binance `isBuyerMaker=true` means the buyer supplied liquidity, so the **aggressor is sell**;
- feeds that expose `side=buy` as taker/aggressor buy are normalized differently;
- private order-side fields describe the user's order direction and must not automatically be reused as public aggressor side.

Canonical fields:

- `order_side`;
- `aggressor_side`;
- `maker_side`;
- `liquidity_role`;
- `side_semantics_source`.

If aggressor side cannot be determined, use `UNKNOWN`; never guess from price movement.

### Duplicate and replay idempotency

Retries, reconnect snapshots, archive overlaps and REST gap repair can legitimately deliver the same event more than once.

Every durable event family defines an idempotency key.

Examples:

- venue + symbol + native trade id;
- venue + symbol + aggregate-trade id;
- venue + oid + fill/trade id;
- block + transaction/event index where stable.

Requirements:

- duplicate ingestion is safe;
- an event is economically accounted once;
- failed validation before commit does not poison the key for a later valid retry;
- repaired/backfilled events follow the same canonical normalization path as live events;
- source provenance distinguishes `LIVE / BACKFILL / ARCHIVE / REPAIR`;
- eventual-dedup storage cannot be queried as though duplicates are already absent.

### Gap repair without double counting

For streams with monotonic ids/sequence ranges:

1. detect gap;
2. quarantine affected derived state;
3. repair only through a compatible source;
4. mark repaired events as backfill/repair;
5. deduplicate overlap;
6. rebuild dependent features from the last certified checkpoint;
7. return to `LIVE` only after invariants pass.

Large unrecoverable gaps remain explicit evidence gaps rather than being bridged by interpolation.

### Order-book reconstruction state machine

Each venue has a source-specific book synchronizer.

Canonical state:

`EMPTY -> SNAPSHOT_LOADING -> CATCHING_UP -> LIVE -> GAP/CHECKSUM_FAIL/STALE -> RECOVERING -> LIVE`.

Per venue define:

- snapshot source;
- delta sequence fields;
- inclusive/exclusive sequence rules;
- duplicate/repeated-update handling;
- checksum rule if available;
- reset/new-stream semantics;
- maximum buffered age/count while snapshot loads.

Book-dependent signals run only on `LIVE` certified state.

A plausible BBO after a sequence gap does not make the book valid.

### Venue-specific sequence semantics

Do not create one generic sequence rule for all venues.

Adapters preserve native semantics such as:

- Binance futures update ranges/previous-update linkage;
- Bybit snapshot/delta update identifiers and reset semantics;
- OKX `seqId/prevSeqId` and checksum where available;
- Hyperliquid block/source ordering and L2/L4 semantics.

The normalized schema may expose a common continuity state, but native ids remain available for audit.

### Crossed / impossible book invariants

After every applied snapshot/delta where applicable, test:

- best bid < best ask unless the venue explicitly permits locked/crossed transitional state;
- positive finite price/size;
- sorted levels;
- no negative depth;
- tick/lot validity where source metadata permits;
- checksum/sequence continuity;
- timestamp non-regression within documented tolerance.

Violations quarantine the book rather than feeding a strategy.

### Stream epoch / reconnect identity

A reconnect may restart source ids or deliver a new snapshot epoch.

Persist:

- connection id;
- source session/epoch;
- reconnect reason;
- last certified id before disconnect;
- first id after reconnect;
- overlap/gap classification.

Never compare sequence ids across epochs unless the venue explicitly guarantees continuity.

### Clock-quality envelope

Cross-venue causality uses timestamp uncertainty, not timestamp values alone.

For each feed/source record:

- exchange timestamp resolution;
- local monotonic receive timestamp;
- wall-clock receive timestamp;
- clock-sync source/status where relevant;
- observed offset/drift estimate;
- network/collector jitter estimate.

Lead-Lag/latency claims require:

`measured_lead > combined_timing_uncertainty`.

If not, classify as `TIMING_UNRESOLVED`.

Wall-clock adjustments/NTP steps cannot reorder already captured monotonic receive events.

### Contract/payoff normalization before cross-venue joins

A ticker match is never sufficient.

Canonical instrument mapping includes:

- linear / inverse / quanto;
- perpetual / dated future / spot / option / outcome;
- contract multiplier;
- base/quote/settlement currency;
- collateral currency;
- index/oracle;
- expiry;
- funding convention;
- tick/lot;
- notional conversion;
- payoff direction.

Cross-Venue/Relative-Value computes comparable USD/base notionals from the actual contract formula.

Inverse or quanto contracts cannot be compared using raw `price × quantity` when that is not their payoff/notional definition.

### Fee and rebate fill accounting

Store fee economics at the **fill** level when available:

- fee amount;
- fee currency/token;
- maker/taker role;
- rebate sign;
- builder/deployer component where exposed;
- conversion rate and timestamp when fee currency differs from reporting currency.

Rules:

- negative fee/rebate remains negative cost rather than being absolute-valued;
- fee-token conversion uses point-in-time conversion, not today's price;
- cumulative order fee is the exact sum of unique fill fees;
- funding/borrow/transfer costs remain separate from trade fee attribution.

### Exact decimal/fixed-point boundary

Exchange numeric strings are parsed into exact decimal/fixed-point representation for:

- price;
- quantity;
- fee;
- funding;
- PnL;
- collateral/accounting state.

Binary floating point may be used for statistical research after normalization, but it is not authoritative for order validity, fill notional or ledger reconciliation.

### Fill-to-position reconciliation

A fill-derived position and venue/account-state position are separate evidence streams.

At reconciliation checkpoints compare:

- expected position from unique fills;
- reported clearinghouse/account position;
- funding/ledger changes;
- liquidation/ADL/system events;
- transfers/borrow changes where relevant.

A discrepancy creates `RECONCILIATION_GAP`.

Do not invent a missing fill merely to force equality.

Some venues can aggregate several position changes into one update or change position due to liquidation/ADL without an ordinary user-order update; adapters document these exceptions.

### Archive / correction provenance

Historical exchange datasets can be revised.

For every durable source file/partition store:

- source URL/path;
- retrieval time;
- size;
- checksum;
- source revision/changelog when available;
- normalization schema version.

If an upstream archive changes:

- do not silently mutate a previously certified dataset;
- create a new dataset version/manifest;
- compare affected partitions;
- invalidate dependent evidence only where necessary.

### Event-family effective sample count

One parent action can generate:

- many child fills;
- many trade rows;
- many L2 deltas;
- multiple venue echoes.

Effective sample counts use causal/event clusters, not raw message rows.

This applies to:

- Hawkes;
- forced liquidations;
- TWAP slices;
- metaorders;
- order sweeps;
- cross-venue propagation.

### Data-semantic regression fixtures

Each native collector/normalizer keeps small golden fixtures covering:

- one valid trade;
- duplicate trade;
- gap + repair;
- snapshot + overlapping deltas;
- reconnect/new epoch;
- ambiguous/unknown side;
- aggregate/sweep event;
- partial fill;
- negative maker rebate;
- fee in non-reporting currency;
- contract multiplier/inverse notional;
- malformed/invalid precision;
- corrected archive row where a real case exists.

A collector upgrade that changes normalized scientific output must explain why and invalidate/rebuild affected evidence.

### V6.11 proof-report fields

Relevant modules additionally report:

- raw rows;
- unique native events;
- sweep/parent-event count;
- duplicate rate;
- repaired-gap count;
- unrepaired-gap duration;
- book LIVE coverage %;
- checksum/sequence failures;
- UNKNOWN-side fraction;
- timing-unresolved fraction;
- reconciliation-gap count;
- archive/version hash;
- effective independent event count.



### Profitability Convergence V6.12 — lifecycle, calendar and reference integrity

The final micro-detail pass focuses on events where the **meaning of the instrument or reference clock changes** even though the ticker may look unchanged.

### HIP-3 / RWA corporate-action contract

HIP-3 deployers are responsible for market definition, oracle definition and operation. There is no assumption in this spec that every equity/RWA perp applies one universal stock-split, dividend or corporate-action convention.

For every RWA/equity/index instrument store when available:

- underlying legal/economic reference;
- price-return vs total-return interpretation;
- dividend treatment;
- split/reverse-split treatment;
- merger/spinoff/tender treatment;
- symbol change;
- index reconstitution;
- oracle adjustment rule;
- deployer announcement/spec revision;
- halt/settlement/recycle event.

If the market specification does not define a corporate-action treatment, use `UNMEASURABLE/MARKET_SPECIFIC`.

Do not automatically:

- add cash dividends to perp PnL;
- back-adjust a perp because the cash equity was back-adjusted;
- assume a split changes contract size or position quantity;
- assume the post-action ticker is economically identical.

### Session calendar and DST integrity

Every non-24/7 external reference uses a versioned exchange calendar with:

- timezone;
- regular open/close;
- pre/post-market if relevant;
- holidays;
- early closes;
- daylight-saving transitions;
- exceptional closures;
- external session source/version.

All event times are stored in UTC plus original timezone context where needed.

Rules:

- never hard-code a fixed UTC equity open across DST transitions;
- reopen studies use the actual historical session boundary;
- Friday/weekend windows account for holiday Mondays and early closes;
- an RWA event cannot be labeled `INTERNAL_SESSION` merely from wall-clock hour without calendar confirmation.

### External-reference source switching

If a HIP-3/RWA deployer changes external oracle/reference source by session or rule revision:

- preserve source identity;
- preserve switch timestamp;
- treat switch as a regime/event boundary;
- do not splice price series without a basis/discontinuity check;
- calculate pre/post-source residual separately.

If exact source switching is not public, mark it unknown rather than inferring a specific oracle path.

### haltTrading / settlement / recycle semantics

HIP-3 deployers can halt/settle markets under protocol rules and may later recycle/resume assets.

Store:

- halt announced/observed time;
- final trading-state transition;
- mark/reference used at settlement where observable;
- settlement timestamp;
- position close/settlement event;
- resume/recycle timestamp;
- new contract/spec revision.

A halt/settlement is not an ordinary market close.

Historical data before and after a recycled asset cannot be concatenated under one continuous instrument identity without confirming specification continuity.

### Dated-future lifecycle

Where Cross-Instrument Relative Value uses dated futures, each contract stores:

- exact expiry;
- last trading time;
- settlement type;
- settlement reference/index;
- settlement calculation window;
- delivery/cash-settlement semantics;
- contract multiplier;
- expiry timezone/calendar;
- roll candidate universe.

Research distinguishes:

- hold-to-settlement convergence;
- pre-expiry basis;
- calendar spread;
- explicit roll.

Continuous/back-adjusted futures series are research features only and cannot be used as executable contract prices.

### Roll logic and liquidity migration

If a continuous future is used for signal generation, store:

- mapping/roll rule;
- actual front contract;
- next contract;
- roll timestamp;
- liquidity/OI used to choose roll;
- adjustment method;
- raw unadjusted prices for execution.

A back-adjustment cannot generate artificial PnL or eliminate real roll cost.

Roll cost includes both closing and opening legs plus spread, fees, slippage and legging risk.

### Funding-boundary exactness

Funding research records separately:

- funding observation time;
- predicted/current rate time;
- settlement timestamp;
- position state immediately before/at settlement if the venue exposes the rule;
- realized funding ledger timestamp.

If the venue documentation/data does not prove the exact position-snapshot boundary, the simulator uses a conservative documented convention or marks boundary-sensitive trades `FUNDING_BOUNDARY_UNCERTAIN`.

Strategies cannot earn funding solely by assuming an unverified infinitesimal enter-before/exit-after boundary.

### Account / subaccount / vault lineage

Public Hyperliquid data can expose subaccount relationships and vault structures.

Maintain a graph only from explicit public protocol relationships:

- master/account address where public;
- subaccount address;
- vault address;
- depositor/leader role where exposed;
- DEX/account-abstraction state.

Rules:

- subaccounts remain separate execution/risk identities;
- portfolio margin does not merge separate subaccounts;
- Copy-Vault can optionally cluster clearly linked public subaccounts for leader-level statistics, but must preserve address-level fills and execution delays;
- do not infer that two unrelated wallets belong to one person/entity from behavior alone;
- vault depositors are not automatically equivalent to the vault strategy/leader.

### Wallet-event pre-positioning watch lane

Deposits, withdrawals, transfers and margin changes may precede trading, but public anecdotal examples are vulnerable to hindsight bias.

Treat account-funding/movement events as a `WATCH/FEATURE` lane for Copy-Vault only.

Required test:

- point-in-time public observation;
- fixed wallet universe;
- event-time relative to subsequent OPEN/ADD/REDUCE/CLOSE;
- matched no-event control;
- forward markout after actual observation latency;
- multiple-testing correction.

No "wallet deposited -> will long" rule is assumed.

### Instrument lineage graph

Maintain:

`economic_underlying -> venue product -> contract/version -> symbol aliases`.

Version edges for:

- listing;
- delisting;
- redenomination;
- token migration;
- contract multiplier change;
- collateral change;
- oracle change;
- deployer recycle;
- corporate action;
- expiry/roll.

This prevents data from two economically different contracts sharing the same symbol from being merged.

### V6.12 proof fields

Relevant modules additionally report:

- calendar coverage/version;
- DST/holiday correctness;
- corporate-action unknown count;
- oracle/reference-source change count;
- halt/settlement/recycle events;
- dated-contract roll count/cost;
- funding-boundary uncertainty count;
- subaccount/vault lineage coverage;
- instrument-lineage breaks.



### Profitability Convergence V6.13 — market-rule edge-case closure

V6.13 closes the remaining low-level Hyperliquid execution details verified against current official documentation and the final public-bot corpus filter.

The governing rule is:

> **an apparent edge is not admissible if it depends on an order lifecycle, trigger, batch action, funding value, queue interaction or throughput assumption that the venue would not actually permit at that timestamp.**

V6.13 does not add a new alpha module. It hardens every existing module whose economics depend on realistic execution.

### Self-trade prevention — exact expire-maker semantics

Current Hyperliquid self-trade prevention uses an **expire-maker** behavior.

When the same address would trade against itself:

- the resting maker order is canceled;
- no self-trade fill is created;
- no normal trade fee is charged for that prevented match;
- the cancellation does not appear as an ordinary trade-feed print;
- the aggressing order may continue matching against eligible liquidity behind the expired maker order up to its limit.

Replay requirements:

1. run Portfolio Intent Netting first;
2. if a same-account crossing still occurs, cancel the resting self order;
3. retain the aggressor's remaining quantity;
4. continue external matching when the order type/rule permits;
5. record `selfTradeCanceled` separately from ordinary market cancel/trade statistics.

Do not model STP as two fills, and do not model it as "both orders vanish" unless a different venue/version explicitly specifies that behavior.

### TP/SL trigger and child-order lifecycle

Hyperliquid TP/SL uses **mark price** as the trigger reference.

Replay separates:

`PARENT_STATE -> TRIGGER_ACTIVATION -> CHILD_PLACEMENT -> CHILD_EXECUTION`.

Current documented edge cases include:

- full parent fill activates the associated TP/SL children;
- a partially filled parent that is manually canceled can cause the associated children to be canceled rather than automatically resized to the filled fraction;
- a partially filled parent canceled for insufficient margin can have different child-placement behavior under the current rule;
- paired TP/SL siblings can cancel when the other sibling fills;
- TP/SL limit orders can trigger yet remain unfilled;
- TP/SL market orders use the venue's bounded slippage semantics rather than unlimited market consumption.

Current documentation describes a **10% slippage tolerance** for TP/SL market orders. This value is versioned and must not be treated as timeless.

Therefore:

> **triggered not equal filled**.

Trigger maps count only observed trigger state; expected forced notional requires modeling the resulting child order and executable book.

### Native TWAP child and catch-up mechanics

Scheduled-Flow replay must reproduce native TWAP mechanics rather than imposing an ideal uniform schedule.

Current documented behavior includes:

- scheduled child execution;
- per-child bounded slippage;
- underfilled children can leave the parent behind target;
- later children may increase to catch up;
- catch-up size is capped relative to a normal child;
- a parent can finish with residual unexecuted quantity;
- network post-only periods can interrupt child execution.

Current documentation describes child slippage capped at **3%** and catch-up children capped at **3x the normal suborder size**. These values are rule-version inputs, not permanent assumptions.

Record:

- target cumulative size;
- realized cumulative size;
- execution lag;
- normal child size;
- catch-up child size;
- child slippage envelope;
- residual quantity at completion;
- rule version.

Do not reconstruct a perfectly smooth TWAP when actual native behavior could lag/catch up.

### Action expiry

For actions supporting `expiresAfter`:

- store expiry timestamp;
- reject modeled arrival after expiry;
- distinguish stale-expiry rejection from market rejection;
- include any documented additional action-rate-limit penalty in execution-feasibility analysis.

Current documentation states an action canceled because of a stale `expiresAfter` can consume **5x** the normal address-based rate-limit cost.

No replayed trade may occur after its action deadline.

### Modify / batchModify semantics

Modify semantics are versioned and may not equal atomic in-place editing.

Store:

- target oid/cloid;
- original order state;
- replacement order;
- `always_place` state;
- cancel result;
- replacement result;
- effective queue reset/reordering;
- TIF transformation;
- trigger eligibility.

Current documented behavior distinguishes:

- `always_place = true`: replacement can be placed regardless of whether the cancel succeeded;
- `always_place = false`: replacement is subject to tighter constraints and, in documented cases, a non-executable GTC replacement can be forced to ALO semantics.

Replay cannot choose the more favorable interpretation after observing future fills.

### Whole-batch pre-validation rejection

Hyperliquid batched requests can fail in two different ways:

1. per-item result vector;
2. a single payload-level pre-validation error rejecting the whole batch.

For multi-order/multi-leg paper execution:

- perform payload-level validation before child matching;
- if pre-validation rejects the batch, reject every child action;
- do not allow apparently valid children to reach the book;
- distinguish `BATCH_PREVALIDATION_REJECT` from per-child rejection.

This is mandatory for multi-leg Relative Value, XEMM hedge batching and any future portfolio order batching.

### Fast cancel semantics

The `fast` cancel flag is versioned explicitly.

Current documentation states:

- fast cancel cannot be used for trigger orders;
- in the currently documented period, the flag has no other effect;
- documentation notes a future network upgrade may give it mempool priority.

Therefore:

- do not credit faster cancellation before that priority behavior is actually active;
- do not back-apply future behavior historically;
- trigger-order cancel attempts using an invalid fast mode are rejected in feasibility simulation.

### Scheduled cancel / dead-man switch

Schedule-cancel remains safety behavior, never alpha.

Current documented rules include:

- deadline must be at least **5 seconds** in the future;
- when the deadline is reached, open orders are canceled and the trigger count increases;
- current maximum scheduled-cancel triggers is **10 per day**, resetting at 00:00 UTC.

Version these values.

A paper market maker that would exhaust the safety trigger allowance is operationally invalid even if its fills look profitable.

### Open-order / action-limit feasibility

Quote-heavy strategies report whether their hypothetical behavior fits point-in-time account limits.

Current documented Hyperliquid behavior includes:

- a default open-order allowance of **1000**;
- one additional open-order slot per **5M USDC** of volume;
- a maximum total open-order limit of **5000**;
- once already at/above 1000 open orders, additional reduce-only or trigger orders can be rejected under the documented rule;
- address action allowance scales with cumulative traded volume;
- a new address has a documented initial action buffer;
- cancels receive an expanded cumulative allowance;
- batch actions consume IP/address budgets differently.

These are feasibility constraints only; paper Alina still sends no actions.

### Congestion maker-share constraint

Hyperliquid documents an additional write-capacity restriction during high congestion tied to prior-day maker share and asset-volume weighting.

Where the historical congestion state and applicable maker share are measurable, replay stores them.

Where they are not measurable:

- quote-heavy strategies run a conservative congestion stress;
- report `CONGESTION_LIMIT_UNKNOWN`;
- do not certify a strategy whose economics require unbounded cancel/requote throughput.

### Market-order / IOC price protection

A paper "market order" is never an unlimited fill through arbitrary depth.

Replay must model the actual order mechanism and applicable protection envelope:

- IOC unfilled remainder cancels;
- no-liquidity states can reject;
- Frontend/UI market behavior is distinguished from a raw API IOC when semantics differ;
- TP/SL-market slippage bounds are applied separately;
- venue price/oracle rejection rules remain active.

### Mark/oracle event timing

Mark and oracle events are separate from raw trade/BBO events.

Current Hyperliquid documentation states:

- validator oracle prices update approximately every few seconds;
- mark price is recomputed using robust oracle/venue inputs;
- mark drives margin, liquidation, TP/SL triggering and unrealized PnL.

Replay therefore records:

- oracle timestamp;
- mark timestamp;
- raw trade timestamp;
- BBO timestamp.

A transient last-trade move that does not update the relevant mark cannot automatically trigger a TP/SL or liquidation.

### Funding known-vs-final state

V6.9 already specifies the funding formula. V6.13 makes **information finality** explicit.

For standard Hyperliquid perps, current documentation states:

- premium is sampled every **5 seconds**;
- samples are averaged over the hour;
- the formula uses the 8-hour convention;
- funding is paid hourly at one eighth of the computed rate;
- the current standard interest component is **0.01% per 8 hours**;
- current funding is capped at **4% per hour**;
- final payment uses `position_size × oracle_price × funding_rate`, not mark-price notional.

Maintain states:

- `PREMIUM_SAMPLE`;
- `RUNNING_HOURLY_ESTIMATE`;
- `EXCHANGE_PREDICTED`;
- `FINAL_SETTLED_RATE`;
- `REALIZED_PAYMENT`.

A strategy decision cannot consume `FINAL_SETTLED_RATE` before it was actually knowable.

Standard-perp, HIP-3 and Hyperp funding formula families remain separate and versioned.

### Funding impact-notional exactness

Funding premium reconstruction stores the exact impact notional/rule version.

Current validator-operated specifications document different impact notionals for BTC/ETH versus many other assets.

A reconstructed funding edge using the wrong impact notional is invalid for proof.

Store:

- impact notional;
- premium formula family;
- interest component;
- clamp;
- cap;
- multiplier;
- settlement cadence;
- oracle source.

### Maximum order-value constraints

Capacity uses venue order-value limits in addition to depth and margin.

For every instrument/rule version store, where documented:

- max market-order value;
- max limit-order value;
- leverage bucket driving the cap.

If desired size exceeds one-order capacity:

- split only when action budget, timing and alpha half-life permit;
- charge additional fees/slippage/impact;
- otherwise reduce capacity.

### Precision and normalization fixtures

V6.8 defines precision rules. V6.13 requires deterministic fixtures for:

- valid 5-significant-figure price;
- invalid sixth significant figure;
- integer-price exception;
- perp `6 - szDecimals` decimal bound;
- spot `8 - szDecimals` decimal bound;
- valid/invalid size precision;
- minimum notional;
- normalization that flips a trade from positive edge to `NO_TRADE`.

The normalized order is re-evaluated economically before any paper fill.

### Reconnect disappearance is not a fill

After reconnect/snapshot:

- disappearance of an order from the current open-order snapshot does not imply fill;
- reconcile against order-status/fills/history;
- classify fill/cancel/reject/liquidation/scheduled-cancel only from compatible evidence;
- unresolved disappearance remains `ORDER_STATE_UNKNOWN`.

This prevents phantom fill PnL after reconnect.

### V6.13 rule manifest

Every execution-sensitive proof emits a point-in-time rule manifest including, when relevant:

- STP behavior;
- precision/tick/lot;
- min/max order size/value;
- margin/leverage/OI cap;
- fee/priority state;
- funding formula/cap/impact notional;
- TP/SL trigger source and child lifecycle;
- TWAP child/catch-up mechanics;
- modify/batch/always-place semantics;
- action expiry;
- fast/scheduled cancel;
- open-order/action/congestion limits;
- market/IOC slippage/protection;
- mark/oracle timing.

A missing rule that can change fill validity, cost or forced-flow state is `RULE_UNKNOWN`.

Promotion is prohibited when a favorable assumption about that missing rule is necessary for positive PnL.

### V6.13 proof contribution

V6.13 is valuable even when it finds **no new alpha**.

Success includes:

- invalidating impossible fills;
- removing phantom self-trades;
- correcting funding timing;
- correcting stop/TWAP paths;
- exposing infeasible quote throughput;
- reducing queue/rule uncertainty enough to confidently `KILL` or `PROMOTE` a candidate.

This directly improves the credibility of the +4 USD/day milestone.

### V6.13 research basis

V6.13 was verified primarily against current official Hyperliquid documentation for:

- Funding;
- Robust price indices;
- Self-trade prevention;
- TP/SL;
- Order types;
- Exchange endpoint;
- Error responses;
- Tick/lot size;
- Rate limits and user/open-order limits;
- Contract specifications.

Exa and Parallel Search were used to discover/cross-check the relevant details. Official protocol documentation controls when third-party descriptions differ.



### Profitability Convergence V6.14 — exact fee, priority and reference-price semantics

V6.14 closes the remaining protocol details that can change after-cost PnL by only a few basis points but are material relative to the +4 USD/day proof target.

The governing rule is:

> **a paper edge cannot use a cheaper fee, better queue position, cleaner mid, lower funding notional or more favorable trigger/reference price than the protocol would have provided at that timestamp.**

### Hyperliquid priority-fee exactness

Priority state is versioned separately for:

- IOC/write priority;
- ALO queue priority;
- gossip/read priority.

Do not merge these mechanisms.

#### IOC/write priority

For rule versions that support IOC priority:

- priority rate belongs to the order action/grouping;
- eligible orders must satisfy the then-current asset/order-type restrictions;
- priority cost is converted/charged according to the then-current protocol rule;
- recorded `priorityGas` is reconciled where available;
- temporal benefit is evaluated separately from fee cost.

Current documentation reviewed in this pass describes:

- a 0-8 bps region that affects temporal prioritization;
- priority above 8 bps providing no further ordinary time-preference benefit, while higher rates can still determine ordering among similarly timed orders in the high-priority bucket;
- a current empirical mainnet effect around 45 ms lower end-to-end latency per 1 bp in the useful 0-8 bps range.

These are **current/versioned observations**, not historical constants.

#### ALO queue priority

For rule versions that support ALO priority:

- priority does not simply make the transaction "arrive faster";
- it changes queue ordering among sufficiently recent same-level ALO orders;
- the relevant recent-order window is versioned;
- current documentation describes a roughly **400 ms** rolling eligibility window.

Critical economic detail:

> **ALO priority cost is charged when the order is placed, regardless of whether that order later fills.**

Therefore maker/XEMM replay must include:

```text
expected_alo_priority_cost
= placement_rate
  * resting_notional
  * number_of_priority_placements
```

subject to the exact historical protocol formula.

Consequences:

- canceled/unfilled priority ALO orders still consume cost when the rule version charges at placement;
- repeated repricing/cancel-replace can destroy an apparently profitable maker edge even with zero fills;
- queue improvement is measured against placement cost, adverse selection and queue aging;
- priority-fee PnL is not conditioned only on fills;
- a strategy cannot estimate ALO priority cost from fill records alone if placement-level evidence is missing.

When historical placement-level priority evidence is unavailable, result is `PRIORITY_COST_UNMEASURABLE`, not zero.

#### Eligibility/version drift

Official priority documentation has changed over time.

Therefore the rule manifest stores:

- supported asset class;
- allowed TIF/order family;
- reduce-only eligibility;
- max/useful priority range;
- charging basis;
- queue window;
- mempool/time-priority behavior;
- fee currency/conversion;
- activation/revision timestamp.

Never apply current ALO capability or current high-priority ordering rules to a historical period without rule evidence.

### Point-in-time fee-tier engine V2

Hyperliquid fee proof must use the actual/account-achievable fee state, not a repo-wide constant.

Current official fee mechanics reviewed in this pass include:

- rolling **14-day weighted volume**;
- perp and spot volume jointly contributing to tier qualification;
- spot volume counting with a different weight under the current schedule;
- master/sub-account aggregation behavior;
- vault volume treatment distinct from ordinary master/sub-account aggregation;
- VIP taker/maker tiers;
- market-maker rebate tiers;
- referral discounts with eligibility limits;
- staking discounts;
- HIP-3 deployer fee scaling;
- growth-mode scaling;
- aligned-quote adjustments where applicable;
- builder fees;
- priority fees.

For every paper account state store when measurable:

- `userCrossRate`;
- `userAddRate`;
- spot cross/add rates;
- active referral discount;
- active staking discount;
- rolling weighted volume;
- maker-fraction/rebate tier;
- vault-vs-user account class;
- deployer/growth-mode fee state;
- builder fee;
- fee-rule timestamp.

The official `userFees` endpoint is a preferred point-in-time source when collected causally.

Rules:

- do not infer future VIP/MM tier from volume accumulated later in the backtest;
- a sub-account cannot be assigned a fee state inconsistent with current master-account aggregation rules;
- vault fee economics are modeled under vault rules, not automatically inherited from the master account;
- referral/staking discounts cannot prove +4 USD/day unless the paper proof contract explicitly allows and can sustain them;
- fee rebates remain negative cost and are reconciled fill-by-fill;
- current fee rules are never back-applied across known rule changes.

### allMids / midpoint provenance

A field named "mid" is not automatically executable midpoint truth.

Current Hyperliquid `allMids` documentation states that when the order book is empty, the **last trade price can be used as fallback**.

Therefore every normalized midpoint carries:

- `mid_source = BBO_MID / LAST_TRADE_FALLBACK / OTHER / UNKNOWN`;
- book age;
- last-trade age;
- bid/ask availability;
- executable-depth confidence.

Rules:

- Cross-Venue and Lead-Lag cannot use `LAST_TRADE_FALLBACK` as if it were a two-sided executable BBO;
- a fallback midpoint may be used as context/reference only with explicit lower confidence;
- an apparent dislocation caused by an empty book plus stale last trade is rejected from executable-arbitrage admission;
- fallback-state frequency becomes a market-liquidity/data-quality metric.

### Funding cash-flow exactness

Funding prediction and funding settlement remain separate.

For standard Hyperliquid perps under the current documented formula:

```text
premium
= [max(impact_bid_px - oracle_px, 0)
   - max(oracle_px - impact_ask_px, 0)]
  / oracle_px

funding_rate_8h
= average_premium
  + clamp(interest_rate - average_premium, lower, upper)

hourly_payment_rate
= rule-specific hourly fraction of the computed rate
```

Current documentation states:

- premium samples are taken every **5 seconds** and averaged over the hour;
- the standard interest component is currently **0.01% per 8h**;
- funding is paid every hour;
- standard funding is currently capped at **4% per hour**;
- standard impact notional is currently **20,000 USDC for BTC/ETH** and **6,000 USDC for other ordinary assets**, subject to contract/rule version.

Most importantly, the realized funding cash flow uses:

```text
funding_payment
= position_size * oracle_price * funding_rate
```

under the documented standard rule.

Do **not** substitute mark price for oracle price in funding cash-flow notional.

HIP-3 and Hyperp use separate formula families and remain independently versioned.

### Funding evidence ladder

For every funding interval distinguish:

1. raw point-in-time premium/index inputs;
2. running premium average;
3. current/published funding state;
4. venue-predicted/next funding;
5. Alina forecast;
6. final settled funding rate;
7. realized account funding payment.

A decision at time `t` can access only states 1-5 that were actually observable by `t`.

State 6/7 cannot leak backward.

For `predictedFundings` specifically:

- record observation timestamp;
- venue label;
- predicted rate;
- `nextFundingTime`;
- supported DEX scope;
- missing venues.

Current official docs state the endpoint is supported for the **first perp DEX**; do not silently extend its coverage to other HIP-3 DEXs.

### Robust mark/oracle reference contract

Mark, oracle, BBO/mid and last trade are distinct data products.

Current official documentation states:

- validators publish oracle state approximately every few seconds;
- mark uses robust combinations of oracle, Hyperliquid market state and external-perp references;
- mark drives margining, liquidations, TP/SL triggering and unrealized PnL;
- oracle participates in funding calculation.

Replay stores:

- raw oracle value/timestamp;
- raw mark value/timestamp;
- BBO/mid value/timestamp;
- last trade value/timestamp;
- source/fallback state.

No module may trigger a liquidation/TP/SL solely from a last trade if the required mark state did not cross.

### Quanto / quote-currency accounting

Some standard Hyperliquid perp contracts can have an oracle/reference denominated in USDT while collateral/accounting is in USDC.

Current contract documentation notes that no automatic USDC/USDT conversion is applied for such contracts, making the economic exposure technically quanto-like.

Therefore instrument normalization stores:

- oracle denomination;
- collateral denomination;
- settlement/accounting denomination;
- whether a conversion is applied by protocol;
- residual quote/collateral basis exposure.

Cross-Venue/Relative-Value cannot assume USDC and USDT exposures cancel perfectly.

Stress:

- USDC/USDT basis;
- collateral depeg;
- reference-market quote divergence.

### Exact TP/SL child behavior

V6.13 already separates trigger activation, child placement and fill.

V6.14 locks additional current documented details:

- TP/SL uses mark-price triggering;
- TP/SL market orders currently use bounded slippage rather than infinite market depth;
- parent-attached children are not necessarily resized to the actually filled parent quantity after manual partial-parent cancellation;
- a partially filled parent canceled for insufficient margin can have a different child-placement outcome;
- sibling TP/SL cancellation semantics are versioned.

No generic OCO model may replace these rules.

### Native TWAP exact child behavior

For the currently documented native TWAP rule family, record:

- target cumulative schedule;
- actual cumulative execution;
- normal child size;
- child slippage bound;
- underfill;
- catch-up size;
- catch-up cap;
- residual unfilled parent size;
- post-only/network interruption state;
- randomization/config fields when exposed.

Current documentation reviewed in this pass describes:

- **3% maximum child slippage**;
- catch-up children up to **3x normal child size** when prior slices underfill.

These values are versioned rule inputs.

A Scheduled-Flow model must not assume a perfectly uniform execution path.

### Self-trade expire-maker exactness

Hyperliquid current STP behavior is explicitly **expire maker**:

- same-address attempted self-trade cancels the resting maker order;
- no ordinary fill is created for that prevented match;
- no normal fee is charged on that prevented match;
- the cancel does not appear as an ordinary trade-feed print;
- the aggressing order can continue matching eligible liquidity behind the expired maker up to its limit.

Therefore paper simulation must not:

- create two fills;
- cancel both orders;
- stop the aggressor prematurely;
- count the prevented match in market trade flow.

### Action expiry / modify exactness

Current action semantics reviewed in this pass include:

- `expiresAfter` rejection for stale actions;
- stale `expiresAfter` can carry a higher action-rate cost under current rules;
- fast cancel has trigger-order restrictions;
- scheduled cancel has minimum lead-time / daily trigger-count semantics;
- `modify` / `batchModify` have `always_place` behavior;
- when `always_place=false`, allowed replacement order types/TIF behavior are restricted and can transform a non-executable GTC into ALO behavior;
- payload-level pre-validation can reject an entire batch with one error rather than independent child outcomes.

Replay stores action-level and batch-level outcome separately.

Do not distribute a payload-level batch rejection into optimistic per-child successes.

### Open-order / throughput feasibility exactness

Current Hyperliquid documentation reviewed in this pass includes:

- base open-order allowance;
- volume-linked additional slots;
- capped total allowance;
- special trigger/reduce-only behavior at high open-order counts;
- address-level action budget linked to traded volume;
- larger cancel allowance;
- distinct batch accounting under IP versus address limits;
- high-congestion write constraints tied to prior-day maker-share state.

For quote-heavy research:

- simulate maximum concurrent open orders;
- actions/minute;
- cancels/minute;
- modifies/minute;
- batch composition;
- congestion stress;
- action-budget headroom.

A strategy requiring infeasible throughput is `EXECUTION_INFEASIBLE` even if its theoretical fill model is profitable.

### Maximum order-value contract

Current standard contract documentation exposes maximum market-order value by leverage bucket and a larger maximum limit-order value.

These limits are versioned metadata and participate in capacity.

If desired notional exceeds the current venue cap:

- split into admissible child orders;
- add extra latency/action/impact;
- re-evaluate alpha half-life;
- reject if slicing destroys net edge.

### Frontend/UI market provenance

A UI/frontend market order must not be normalized blindly to an abstract infinite market order.

When `FrontendMarket` or equivalent provenance is visible:

- retain the original TIF/order-type marker;
- preserve the then-current price/slippage protection semantics;
- distinguish UI-generated market behavior from raw API IOC behavior when they differ.

This matters especially for Copy-Vault reconstruction and order-status interpretation.

### Entry-price / PnL accounting contract

Hyperliquid documentation describes entry price and displayed unrealized/closed PnL as convenience/frontend-derived accounting, while fundamental account truth is margin/balance plus trades/ledger.

Therefore Alina keeps:

- exact fill ledger;
- fee ledger;
- funding ledger;
- collateral/account ledger;
- derived entry price;
- derived unrealized PnL;
- venue-reported account state.

The derived entry-price/PnL fields are reconciled but never used to invent missing trades.

For position accounting:

- opening fills update weighted-average entry;
- closing fills retain entry price for remaining position under the documented model;
- unrealized PnL uses mark price;
- closed PnL/fee sign conventions are validated with fixtures rather than assumed from display formatting.

### Source-conflict rule

When two official pages appear to reflect different generations of a protocol rule:

1. do not average/merge the rules;
2. identify the latest applicable rule where publication/version evidence exists;
3. retain older behavior as a separate historical rule version;
4. mark periods without activation-boundary evidence `RULE_VERSION_UNCERTAIN`;
5. run conservative sensitivity if the rule changes PnL.

This is especially important for priority-fee eligibility and charging semantics, which have evolved.

### V6.14 research basis

V6.14 was cross-checked with Exa and Parallel Search, with current official Hyperliquid documentation treated as the controlling source for:

- Priority fees;
- Fees / userFees;
- Funding;
- Predicted fundings;
- Oracle / robust price indices;
- Contract specifications;
- Self-trade prevention;
- TP/SL;
- Order types / native TWAP;
- Exchange endpoint;
- Error responses;
- Rate limits and user limits;
- Entry price and PnL.

Public wrappers and practitioner code were used only to identify edge cases; they do not override official protocol semantics.



### Profitability Convergence V6.15 — exact protocol constants and accounting closure

This layer records the remaining current protocol constants and accounting rules verified against official Hyperliquid documentation on 2026-09-26.

The rule is:

> **current numeric values are versioned protocol inputs, not timeless truths. A historical replay uses the rule valid at that timestamp or reports the field UNMEASURABLE.**

V6.15 does not add a new alpha module. It prevents small specification mismatches from manufacturing or destroying a few basis points of apparent edge.

### Standard-perp contract constants

For validator-operated standard perps, the current documented contract specification includes:

- funding impact notional: **20,000 USDC for BTC and ETH**;
- funding impact notional: **6,000 USDC for all other standard assets**;
- maximum market-order value:
  - **30,000,000 USD** when max leverage is at least 25x;
  - **5,000,000 USD** when max leverage is in [20x, 25x);
  - **2,000,000 USD** when max leverage is in [10x, 20x);
  - **500,000 USD** otherwise;
- maximum limit-order value: **10x the maximum market-order value**.

These constants feed:

- funding reconstruction;
- capacity;
- adaptive slicing;
- XEMM hedge feasibility;
- Forced-Flow stress size;
- Relative Value route sizing.

Never infer capacity only from visible depth when a venue order cap is tighter.

### Funding numeric closure

For standard Hyperliquid perps under the current documented rule:

- the interest component is **0.01% per 8 hours**;
- the hourly equivalent is **0.00125%**;
- premium is sampled every **5 seconds** and averaged over the hour;
- the premium formula uses impact bid/ask versus oracle;
- the clamp band in the current standard formula is **±0.0005** around the interest-minus-premium term;
- funding is paid hourly at one eighth of the 8-hour formula;
- the current documented funding cap is **4% per hour**;
- funding cash flow uses **position size × oracle price × funding rate**, not mark-price notional.

Store separately:

- raw premium samples where available;
- hourly average premium;
- impact notional;
- oracle price;
- computed candidate rate;
- published/current rate;
- realized funding ledger entry.

A published or predicted funding rate is not substituted for the realized funding payment without reconciliation.

### Oracle source construction

For standard validator-operated spot-oracle assets, current Hyperliquid documentation describes validator oracle construction from a weighted median of spot mids including:

- Binance weight 3;
- OKX weight 2;
- Bybit weight 2;
- Kraken weight 1;
- KuCoin weight 1;
- Gate.io weight 1;
- MEXC weight 1;
- Hyperliquid spot weight 1 where the asset's primary-liquidity rules allow it.

The final clearinghouse oracle is the stake-weighted median of validator submissions.

Rules:

- source membership is instrument/rule dependent;
- do not force Hyperliquid spot into the oracle for assets whose primary spot liquidity is external;
- do not force external sources into the oracle where the documented instrument rule excludes them;
- store source set, weights and rule revision.

### Mark-price construction

For ordinary perps, current documentation defines mark as the median of candidate reference prices including:

1. oracle price plus a **150-second EMA** of Hyperliquid mid minus oracle;
2. the median of Hyperliquid best bid, best ask and last trade;
3. a weighted median of perp mids from Binance, OKX, Bybit, Gate.io and MEXC with current weights **3, 2, 2, 1, 1**.

When exactly two of the main candidate inputs exist, current documentation adds a **30-second EMA** of the Hyperliquid bid/ask/last-trade median as an additional candidate.

Current documentation states oracle and mark are updated approximately every **3 seconds**.

Because mark drives:

- margin;
- liquidation;
- TP/SL trigger activation;
- unrealized PnL;

the replay must not substitute last trade or raw mid for mark in these mechanics.

Every mark/oracle sample carries:

- event timestamp;
- received timestamp;
- source-rule version;
- missing-input state;
- fallback state.

### Margin-tier arithmetic

When tiered leverage applies, maintenance margin is reconstructed from the point-in-time margin table.

Current documented structure:

```text
maintenance_margin
= notional_position_value * maintenance_margin_rate
  - maintenance_deduction
```

with:

```text
maintenance_margin_rate(tier n)
= initial_margin_rate_at_max_leverage(tier n) / 2
```

and maintenance deduction recursively chosen so maintenance margin remains continuous across tier boundaries.

Requirements:

- do not approximate a tiered market using only one max-leverage number;
- use the tier corresponding to position notional under the applicable rule;
- store margin-table id and table revision;
- capacity/liquidation stress must cross tier boundaries explicitly.

### Current large-liquidation constants

For the current documented standard liquidation rule:

- liquidatable positions above **100,000 USDC** may initially send only **20%** of the position to the book;
- after a block with partial liquidation, the current documented cooldown is **30 seconds**;
- during that cooldown, subsequent market liquidation orders for the user can use the full position under the documented rule.

These are versioned constants.

Forced-Flow must therefore distinguish:

- ordinary full-book liquidation;
- large-position initial partial liquidation;
- cooldown-period liquidation;
- residual/backstop transition.

Do not back-apply the 100k/20%/30s rule to periods lacking historical rule evidence.

### Exact action-budget constants

Current documented address-level action limits include:

- **1 request per 1 USDC of cumulative traded volume** since address inception;
- initial buffer of **10,000 requests**;
- after address-level rate limiting, allowance of **1 request every 10 seconds**;
- cancel cumulative allowance:
  `min(default_limit + 100000, default_limit * 2)`.

Current open-order capacity:

- default **1000 open orders**;
- +1 slot per **5M USDC** of volume;
- capped at **5000 open orders**;
- at/above 1000 existing open orders, additional reduce-only or trigger orders may be rejected under the current rule.

Current batch accounting:

- a batch of `n` orders/cancels counts as **one** request for IP rate limiting;
- it counts as **n** requests for address-based rate limiting.

Paper Alina does not consume these quotas, but quote-heavy strategies must demonstrate that the hypothetical policy is operationally feasible.

### Congestion block-space constraint

During current documented high-congestion handling:

- an address can be limited to approximately **2x its previous-day maker-share percentage of block space**;
- maker share is scaled by the same asset-volume weighting used for fee-tier contribution;
- the maker share is computed once per UTC date.

If historical congestion/maker-share state is unavailable:

- mark `CONGESTION_LIMIT_UNKNOWN`;
- stress cancel/requote throughput;
- do not certify a strategy that requires effectively unlimited writes.

### Native Chase exactness

Current Chase behavior is frontend/browser-side, not treated as a generic persistent server-side order primitive.

Current documentation states:

- Chase is an ALO/post-only limit order;
- for a buy, it tracks one tick above best bid;
- for a sell, it tracks one tick below best ask;
- when spread is one tick, it rests at the current best bid/ask;
- it continually reprices until filled or terminated;
- it runs in the browser tab where created;
- up to **5 Chase orders** can be active at once.

Consequences:

- Chase is modeled as an execution-policy controller that emits cancel/replace behavior;
- historical Chase queue state is not inferred without actual repricing/order evidence;
- browser/frontend availability is not treated as a server guarantee;
- the policy must pay queue-loss/repricing/action-cost consequences;
- GitHub-hosted paper research may simulate Chase logic but does not imply a live browser dependency.

### Native TWAP numeric contract

Current documented native TWAP behavior includes:

- running time from **5 minutes to 7 days**;
- minimum child interval of **30 seconds**;
- minimum total TWAP order size of **100 USD**;
- maximum child slippage of **3%**;
- optional child-size randomization currently documented as up to **±20%**;
- optional trigger price using **mark price**;
- optional max/min price that terminates the parent when the mark reaches the stop;
- catch-up child size capped at **3x the normal child size**;
- residual quantity may remain unexecuted at the end;
- child execution can pause during documented network post-only periods.

Store:

- requested duration;
- effective interval;
- expected child count;
- randomization setting;
- target cumulative schedule;
- realized cumulative execution;
- catch-up state;
- trigger/termination conditions;
- residual;
- rule version.

Do not assume a mathematically perfect constant-size TWAP.

### Entry-price / PnL accounting closure

Official Hyperliquid documentation states that displayed entry price, unrealized PnL and closed PnL are frontend convenience fields; fundamental accounting is based on margin/balance and trades.

For paper reconciliation:

- opening trades update entry price using size-weighted average entry;
- closing trades leave the remaining position entry price unchanged;
- current documented unrealized PnL convention is:
  `side * (mark_price - entry_price) * position_size`;
- opening-trade closed-PnL display includes only fee under the documented frontend convention;
- closing-trade closed PnL combines fee plus realized price PnL under the documented convention.

Rules:

- preserve the source's fee sign convention explicitly;
- do not use frontend PnL as the authoritative cash ledger;
- reconcile fills, fees, funding and ledger/account changes separately;
- distinguish position PnL from funding and fee cash flows;
- use mark price for unrealized PnL where the protocol does.

### Margin-use closure

Current ordinary margin documentation includes:

```text
initial_margin_required
= position_size * mark_price / leverage
```

and for margin-removing transfers:

```text
transfer_margin_required
= max(initial_margin_required,
      0.1 * total_position_value)
```

under the current documented rule.

Use these only where applicable to the account/margin mode and historical version.

Cross and isolated positions maintain distinct margin pools/availability semantics.

### Hyperp exact reference/cap contract

Hyperps are not ordinary external-oracle perps.

Current documentation describes:

- the external spot/index oracle replaced by an **8-hour exponentially weighted moving average** derived from the prior day's minutely mark-price history;
- external pre-launch CEX perp prices can enter the Hyperp mark calculation;
- current Hyperp mark capped at **3x the 8-hour mark-price EMA**;
- when external pre-launch perp listings are present, mark can also be capped at **1.5x the median external perp-price component**;
- current oracle additionally capped at **4x the one-month average mark price**.

Therefore Hyperp Relative Value must store:

- Hyperp reference/oracle formula version;
- EMA history sufficiency;
- external-prelaunch source set;
- cap state;
- which cap is binding;
- mark/reference residual before and after cap.

A capped mark/oracle residual is not interpreted as free convergence alpha.

### Instrument-class reference firewall

Different Hyperliquid instrument families may use materially different reference mechanisms.

At minimum distinguish:

- standard spot-oracle perp;
- HIP-3 deployer-defined perp;
- Hyperp/pre-launch perp;
- index perp;
- Uniswap/AMM-referenced perp;
- HIP-4/outcome instrument.

A symbol-level normalization cannot erase instrument-class reference semantics.

For Uniswap-referenced perps, preserve the isolated-only/reference-price semantics from the applicable specification.

For index perps, preserve the published index formula/source and revision rather than forcing the standard CEX-spot oracle model.

### Constants manifest

Create a versioned `PROTOCOL_CONSTANTS_MANIFEST` whose entries include:

- venue;
- instrument class;
- field;
- value;
- units;
- effective-from;
- effective-until if known;
- official source;
- collected-at;
- confidence;
- whether the value is current-only or historically certified.

Candidate fields include:

- impact notional;
- funding interest/clamp/cap;
- max order values;
- tick/lot/precision rules;
- margin/liquidation thresholds;
- TWAP/Chase constraints;
- action/open-order limits;
- priority parameters;
- oracle/mark source weights;
- update cadence.

Tests fail if a hard-coded current constant bypasses this manifest in a historical replay path.

### V6.15 research basis

High-signal official sources verified on 2026-09-26 include:

- Hyperliquid Contract Specifications;
- Funding;
- Robust Price Indices / HyperCore Oracle;
- Rate Limits and User Limits;
- Order Types;
- Entry Price and PnL;
- Margining / Margin Tiers;
- Liquidations;
- Hyperps.

External summaries were used only for discovery/cross-checking; official documentation governs the spec constants.


### Profitability Convergence V6.16 — liquidation, margin and trigger exactness

V6.16 closes the remaining low-level Hyperliquid rules that were still represented too loosely after the V6.13-V6.15 hardening passes.

The governing rule is:

> **when official venue semantics are explicit, replay must reproduce them exactly enough that a few basis points, a liquidation route, a TP/SL child or a margin transition cannot be created or removed by approximation.**

This layer does not add a new alpha module.

### Liquidation state machine — exact current standard semantics

For the current documented Hyperliquid standard liquidation flow:

1. an account becomes liquidatable when account equity falls below the applicable maintenance-margin requirement;
2. positions are first attempted against the public order book through market liquidation orders;
3. those book liquidations may fully or partially close the position;
4. if enough risk is removed for maintenance requirements to be restored, remaining collateral remains with the trader;
5. if account equity falls below **2/3 of maintenance margin** without successful liquidation through the book, a backstop liquidation can transfer risk to the liquidator vault;
6. ADL remains a distinct later route/state where applicable.

This state machine is combined with the already-versioned large-position rule:

- current documented threshold above 100,000 USDC;
- current initial partial book liquidation fraction of 20%;
- current 30-second cooldown semantics.

Do not collapse PUBLIC_BOOK_LIQUIDATION, PARTIAL_BOOK_LIQUIDATION, BACKSTOP_TRANSFER and ADL into one liquidation print.

### Backstop transfer accounting

For a cross-margin backstop under the current documented rule:

- the user's cross positions are transferred to the liquidator;
- the user's cross margin is transferred with those positions;
- isolated positions remain outside that transfer;
- if the user has no isolated positions, the documented result can leave the account with zero equity after the cross backstop.

For an isolated-position backstop:

- only that isolated position and its isolated margin are transferred;
- cross margin and unrelated cross positions remain untouched.

Current documentation also states that the maintenance-margin buffer is not returned to the liquidated user during backstop liquidation because the liquidator vault requires a loss buffer.

Replay/accounting therefore distinguishes:

- user residual collateral after successful public-book liquidation;
- collateral/margin transferred on backstop;
- liquidator-vault acquired inventory;
- later liquidator-vault unwind;
- ADL transfer if any.

The backstop margin buffer is not modeled as an ordinary exchange trading fee.

### Liquidation-price dependency contract

For cross margin:

- account value includes unrealized PnL from the relevant cross portfolio;
- funding payments can move liquidation state;
- changes in other cross positions can move liquidation state;
- the actual liquidation price is not simply a fixed function of the leverage selector once the cross position is open.

For isolated margin:

- isolated margin and the isolated position drive liquidation state;
- selected leverage affects initial isolated margin allocation and therefore liquidation economics.

Where margin tiers apply:

- maintenance leverage/rate is taken from the tier applicable to the position value under the point-in-time rule;
- tier transitions are recomputed rather than approximated from one max-leverage number.

A displayed or estimated liquidation price is a derived estimate, not authoritative event truth, unless reconstructed from matching point-in-time account and rule state.

### Margin-mode exactness

Every position/instrument record carries its point-in-time margin mode. Distinguish:

- CROSS;
- ISOLATED;
- STRICT_ISOLATED;
- NO_CROSS;
- unified/portfolio-margin semantics where enabled;
- unknown/legacy state.

Current official semantics include:

- cross margin as the ordinary shared-collateral mode;
- isolated margin with position-specific collateral;
- strictIsolated, where margin cannot be manually removed and is released proportionally as the position closes;
- HIP-3 no-cross mode, which permits isolated-style margin handling but no cross margin;
- unified/portfolio-margin modes where cross positions across DEXs sharing the same collateral can share margin;
- standard account abstraction where cross margin remains scoped to the same DEX.

Consequences:

- two positions on different DEXs are never assumed to share margin unless account abstraction and collateral rules explicitly permit it;
- Relative Value cannot claim capital efficiency from cross-margining unavailable to the modeled account;
- Forced-Flow distinguishes account-wide cross liquidation from isolated-position liquidation.

### TP/SL child lifecycle — exact current rule

Hyperliquid TP/SL parent-child behavior is versioned exactly.

Current documented semantics include:

- position-associated TP/SL defaults to full position size;
- if an explicit size is configured, that TP/SL is fixed-size and does not automatically resize with later position changes;
- order-associated TP/SL children have a fixed size tied to the parent order;
- if the parent is fully filled at placement, children are placed immediately;
- if the parent is not fully filled, children remain untriggered/not-yet-placed;
- canceling an unfilled parent cancels its children;
- manually canceling a partially filled parent cancels child TP/SL orders rather than automatically resizing them to the already-filled amount;
- if a parent is partially filled and then canceled for insufficient margin, current documentation states the children are placed as if the parent were fully filled;
- paired sibling TP/SL orders preserve their one-cancels-other lifecycle where applicable.

The insufficient-margin exception is explicit because it differs from ordinary manual cancellation.

### Trigger validity and trigger reference

For TP/SL under the applicable current rule:

- trigger activation uses mark price;
- a last trade or BBO move alone cannot trigger the order if mark has not crossed;
- triggered is distinct from filled;
- limit TP/SL may trigger and then remain resting/unfilled;
- market TP/SL follows the venue's bounded-slippage behavior.

Current official documentation describes 10% slippage tolerance for TP/SL market orders. This is a versioned rule input.

When creating hypothetical stop/take orders, validate the point-in-time allowed trigger direction rather than accepting an impossible trigger configuration.

### Funding transfer accounting

For standard current Hyperliquid perpetual funding:

- funding is a peer-to-peer transfer between long and short sides;
- the protocol does not collect a separate fee from the funding payment itself under the documented standard rule;
- positive funding means longs pay shorts;
- negative funding reverses the direction;
- hourly settlement remains governed by the exact funding formulas and constants already frozen in V6.14/V6.15.

Accounting separates TRADING_FEES, BUILDER_DEPLOYER_PRIORITY_FEES, FUNDING_TRANSFER and LIQUIDATION_BACKSTOP_MARGIN_EFFECT.

Funding is never double-counted as both a trading fee and a holding transfer.

### Native TWAP completion cross-check

V6.15 already freezes native TWAP numeric constants. V6.16 adds a strict completion check:

- target schedule and actually executed schedule remain distinct;
- catch-up attempts do not guarantee parent completion;
- terminal residual remains unexecuted;
- child non-fill from wide spread/low liquidity is not retroactively filled;
- documented network post-only periods can interrupt child execution;
- trigger and max/min parent conditions use applicable mark-price state.

Scheduled-Flow studies compare reconstructable child execution with the idealized schedule and never treat schedule target as executed quantity.

### Order-state versus trade-feed reconciliation

Some order-state transitions intentionally do not appear in the normal trade feed.

Current self-trade prevention is an example: the resting same-address maker is canceled without a self-trade fill or trade-feed print, while the aggressing order may continue through eligible external liquidity.

Therefore reconciliation combines order-status lifecycle, fills/trades, account/order state, and L4/order-level evidence where available.

Absence from the trade feed is not proof that no order-state transition occurred.

### V6.16 official-source basis

Verified against current official Hyperliquid documentation on 2026-09-26:

- Liquidations;
- Margining;
- Funding;
- Self-trade prevention;
- Take profit and stop loss orders;
- Order types;
- Exchange endpoint;
- Tick and lot size;
- Rate limits and user limits;
- WebSocket behavior.

All rules remain versioned; current behavior cannot be back-applied historically without rule evidence.

### Profitability Convergence V6.17 — portfolio-margin, delisting and accounting exactness

V6.17 closes the remaining account-mode, portfolio-margin and delisting details verified against current official Hyperliquid documentation on 2026-09-26.

The governing rule is:

> **capital efficiency, liquidation path and displayed PnL depend on account abstraction and contract lifecycle; replay must use the exact mode and rule state that existed at the decision timestamp.**

### Account-abstraction mode contract

Every paper account state declares one point-in-time abstraction mode:

- UNIFIED;
- PORTFOLIO_MARGIN;
- STANDARD / MANUAL;
- legacy DEX_ABSTRACTION where historical evidence requires it;
- UNKNOWN.

Current documented semantics:

- Unified uses a single balance per asset and unifies eligible spot balance with cross-margin perp collateral using that asset;
- Portfolio Margin combines eligible spot and perp exposures into one portfolio risk system;
- Standard/Manual keeps spot and perp balances separate and keeps DEX balances separate; cross margin is scoped per DEX;
- the discontinued DEX-abstraction mode remains historical-only and must not be silently mapped to current semantics.

Data-source rule:

- for Unified and Portfolio Margin API users, current documentation states balances and holds are represented through spot clearinghouse state;
- individual perp-DEX user states are not treated as authoritative account-balance truth for those modes;
- Standard mode uses the separate account/DEX states appropriate to that mode.

### Account-mode action and builder constraints

Current official documentation states:

- Unified and Portfolio Margin are limited to 50,000 user actions per day;
- Standard mode does not have that same documented 50k daily action restriction;
- builder-code addresses must be in Standard mode to accrue builder fees.

Consequences:

- a quote-heavy paper strategy cannot claim Unified/Portfolio-Margin capital efficiency while assuming unlimited write throughput;
- builder-fee attribution must be compatible with the builder account mode;
- action-mode feasibility is part of the route/account identity.

### Portfolio Margin eligibility and cap state

Portfolio Margin is not assumed universally available.

Current documented entry constraints include:

- master account weighted volume above 5M USD OR account value above 10k USD;
- account value below 25M USD;
- point-in-time global and per-user supply/borrow caps by eligible asset.

Current documented caps include:

- USDT: 50M global supply, 10M global borrow, 5M user supply, 1M user borrow;
- USDC: 1B global supply, 500M global borrow, 250M user supply, 50M user borrow;
- HYPE: 10M global supply and 1M user supply;
- BTC: 2,000 BTC global supply and 200 BTC user supply.

All values are versioned protocol constants, not timeless limits.

If a cap is hit, replay must follow the documented fallback/non-Portfolio-Margin behavior rather than continuing to grant unavailable borrowing/capital efficiency.

### Portfolio Margin LTV / borrowing / interest

Eligible collateral uses point-in-time LTV.

Current documentation states HYPE and BTC have LTV 0.5 under the current rule.

When insufficient balance is available for eligible spot/perp actions, Portfolio Margin may automatically borrow against eligible collateral subject to balance, oracle, LTV and cap constraints.

Borrowed assets accrue interest continuously and are indexed hourly under the documented model.

For current stablecoin borrowing, official documentation gives the rate formula:

borrow APY = 0.05 + 4.75 * max(0, utilization - 0.8)

with utilization = total borrowed value / total supplied value.

Current documentation also states:

- suppliers earn interest from the same borrowing system;
- the protocol retains 10% of borrowed interest as a liquidation buffer.

Replay stores:

- supplied amount;
- borrowed amount;
- utilization;
- applicable LTV;
- borrow oracle;
- interest accrual;
- cap headroom;
- protocol interest retention;
- rule version.

### Portfolio Margin liquidation exactness

Portfolio Margin is a generalization of cross margin and must not reuse the ordinary perp liquidation state machine unchanged.

Current documentation defines a portfolio margin ratio and states the account becomes liquidatable when that ratio exceeds 0.95.

Current rule components include:

- portfolio maintenance requirement across DEX cross-maintenance plus borrowing requirement;
- portfolio liquidation value based on portfolio balances, borrow caps, supply caps, borrow-oracle values and liquidation thresholds;
- liquidation_threshold(token) = 0.5 + 0.5 * LTV(token);
- a current minimum borrow offset of 20 USDC;
- conversion of relevant values to USDC through documented borrow-oracle logic.

Important route distinction:

- Portfolio Margin liquidation goes directly to the backstop liquidator under the current documented mechanism;
- there is no ordinary public-market liquidation phase for the spot-borrow component described by the current Portfolio Margin rule.

### Portfolio Margin partial/full takeover

Under current documented semantics:

- sufficiently unhealthy accounts can have positive-LTV supplied assets and borrowed assets fully taken over by the backstop liquidator;
- accounts between partial and full liquidation thresholds can be taken over in 20% intervals until no longer liquidatable.

Where the protocol uses asset-specific takeover/slippage widths, record those values point-in-time.

Current documentation names example width values of:

- 3M USDC for HYPE;
- 300k USDC for BTC.

These are versioned constants.

### Portfolio Margin collateral unwind

Current documentation states the backstop liquidator converts collateral assets to debt assets for repayment using a TWAP with a half-life of 10 minutes.

This creates a distinct observable process:

PORTFOLIO_BACKSTOP_TAKEOVER -> COLLATERAL_UNWIND -> DEBT_REPAYMENT.

Forced-Flow and backstop-inventory research may study this unwind separately from perp liquidation, but no direction is assumed a priori.

### Portfolio Margin liquidation ordering uncertainty

Current documentation states that, depending on oracle-update ordering, perp positions or spot borrows may be liquidated first.

Therefore:

- do not impose one deterministic liquidation sequence when the source rule does not guarantee it;
- record the observed route where reconstructable;
- otherwise branch/sensitivity-test admissible ordering or mark LIQUIDATION_ORDER_UNCERTAIN.

### Delisting settlement contract

Validator-operated perp delisting is an explicit lifecycle event, not an ordinary close.

Current official documentation states:

- validators vote on delisting validator-operated perps;
- if delisted, the perp settles to the 1-hour time-weighted spot oracle price before the scheduled delisting voting time;
- all positions are settled;
- all open orders are canceled;
- after settlement no new orders are accepted.

Replay requirements:

- preserve announcement/vote/scheduled-settlement timestamps where observable;
- use the documented 1-hour TW spot-oracle settlement rule for the applicable version;
- cancel open orders at delisting settlement;
- do not create post-settlement fills;
- classify delisting PnL separately from ordinary discretionary exit.

### Entry-price / PnL display versus accounting truth

Current official documentation states entry price, unrealized PnL and closed PnL are frontend/convenience calculations; fundamental accounting is based on trades and margin/balance.

For perps under the documented display model:

- position-increasing trades update entry price as a size-weighted average;
- position-reducing trades keep the entry price of the remaining position unchanged;
- unrealized PnL uses mark price;
- displayed closed-PnL behavior includes fee effects.

Alina therefore treats:

- fill ledger;
- fee ledger;
- funding ledger;
- collateral/margin ledger;
- transfer/borrow ledger

as accounting authority.

Displayed entry/PnL fields are reconciliation views and cannot invent missing fills or cash flows.

### Spot-leg accounting provenance

For Relative Value strategies that use spot legs, do not assume the displayed spot entry price is economic acquisition cost.

Official documentation uses frontend-specific rules for spot buys/sells and some transfer/legacy balances.

Therefore:

- strategy accounting uses actual fills/transfers and causal mark/oracle data;
- venue-displayed spot entry price is a reconciliation field;
- imported/legacy balances with ambiguous acquisition history are marked COST_BASIS_UNCERTAIN for strategy-PnL attribution.

### V6.17 official-source basis

Verified against current official Hyperliquid documentation on 2026-09-26:

- Account abstraction modes;
- Portfolio margin;
- Delisting;
- Entry price and PnL;
- Margining;
- Liquidations;
- Fees and account/user-limit documentation.

Current constants and eligibility rules are versioned and are never back-applied automatically.

### Profitability Convergence V6.18 — exact ADL queue semantics

V6.18 closes the final currently identified gap in the forced-flow state machine: exact Hyperliquid auto-deleveraging behavior.

Current official documentation states that ADL is a solvency safeguard triggered when a user's account value, or an isolated position value, becomes negative.

### ADL counterparty ranking

Users on the opposite side are ranked by unrealized PnL and leverage used.

The current documented sorting index for profitable counterparties is:

(mark_price / entry_price) * (notional_position / account_value)

Replay must use the historical rule version and point-in-time inputs rather than a generic 'highest leverage first' approximation.

### ADL execution price

Current documentation states that selected profitable counterparties are closed against the underwater user at the **previous mark price**.

Therefore:

- ADL fills are not priced from contemporaneous BBO/VWAP as ordinary market orders;
- ADL mark reference must be the protocol-defined previous mark for that rule version;
- current BBO depth cannot be charged as ordinary slippage for an ADL transfer unless another rule explicitly requires it;
- ADL PnL remains separate from public-book liquidation and backstop-unwind PnL.

### Backstop and ADL queue interaction

Current documentation states that backstop-liquidated positions receive **no special treatment** in ADL queue logic.

Therefore a position acquired through backstop cannot be given privileged or protected ADL ranking solely because of its provenance.

### Solvency/account boundary

The official invariant states that a user with no open positions does not socialize platform losses.

Alina therefore:

- does not allocate ADL/socialized-loss cash flows to flat accounts;
- clusters ADL events with their parent insolvency episode for effective-sample accounting;
- preserves the identity of the underwater side and selected opposite-side ADL counterparties only as public market-structure evidence, never for deanonymization.

### Forced-Flow route closure

The full modeled route family is now:

PUBLIC_BOOK_LIQUIDATION -> PARTIAL_BOOK_LIQUIDATION -> BACKSTOP_TRANSFER -> BACKSTOP_INVENTORY/UNWIND -> ADL

with Portfolio Margin direct-backstop routes kept separate under V6.17.

Each transition remains UNKNOWN whenever public evidence is insufficient.

### V6.18 official-source basis

Verified against the current official Hyperliquid Auto-deleveraging documentation on 2026-09-26.

All ADL constants/formulas are versioned and are not back-applied to historical periods without rule evidence.

### Profitability Convergence V6.19 — AMM-oracle and formula-index relative value

The continued official-doc and public-code filter identified two Hyperliquid instrument classes not explicitly represented in Alina:

1. perps whose underlying oracle comes from a Uniswap V2/V3 AMM;
2. formula/index perpetuals whose underlying is a published index formula rather than ordinary spot.

V6.19 adds them as scoped Relative-Value / execution research sleeves, not core modules.

### Oracle-source instrument taxonomy

Every perp carries a versioned oracle-source class where applicable:

- CEX_SPOT_MEDIAN;
- HYPERLIQUID_SPOT;
- UNISWAP_V2_AMM;
- UNISWAP_V3_AMM;
- FORMULA_INDEX;
- HYPERP_EMA_REFERENCE;
- HIP3_DEPLOYER_ORACLE;
- OTHER / UNKNOWN.

Oracle-source class is part of instrument identity because it changes:

- fair-value reconstruction;
- latency/update cadence;
- manipulation/fragility model;
- external hedge path;
- funding reference;
- data requirements.

### Candidate Sleeve — AMM Spot ↔ Hyperliquid Perp Relative Value

For an AMM-oracle perp, independently reconstruct the executable AMM-side price and compare it with Hyperliquid perp state.

Candidate states:

- AMM executable buy quote;
- AMM executable sell quote;
- pool fee tier;
- gas/transaction cost estimate;
- price impact by notional;
- current liquidity/range state;
- Hyperliquid BBO/L2;
- mark/oracle/funding;
- basis after all costs;
- hedge latency and settlement/collateral state.

Critical rule:

> raw pool spot, slot0, sqrtPrice or a theoretical AMM marginal price is not an executable hedge price.

Use executable quote/swap simulation for the candidate notional, including:

- AMM pool fee;
- route fee;
- price impact;
- gas;
- slippage tolerance;
- stale-state risk;
- chain/RPC observation delay;
- bridge/transfer cost only if the proposed route actually requires transfer.

Cross-protocol opportunity is admitted only when both legs are economically realizable from already-positioned collateral or the required capital movement is explicitly modeled.

### Hyperliquid Uniswap-perp contract state

Current official Hyperliquid documentation states some perps use Uniswap V2/V3 AMM price as the underlying spot asset.

Current documented semantics include:

- these contracts are isolated-only;
- cross margin is unavailable;
- margin cannot be manually removed while the position remains open;
- isolated margin is returned only as the position is partially or fully closed;
- Uniswap pool prices are converted to USDT using robust CEX oracle prices.

Store point-in-time:

- pool protocol/version;
- chain;
- pool address;
- token0/token1;
- fee tier;
- decimals;
- oracle-conversion path;
- isolated-only rule;
- contract/rule revision.

Pool addresses are versioned metadata, not timeless constants.

### Candidate Sleeve — Delta-Neutral Concentrated-Liquidity + Perp Hedge

Public implementations and academic work independently support a research architecture where a Uniswap V3 concentrated-liquidity position is dynamically hedged with derivatives.

Alina may test this as a paper-only experimental sleeve.

The economic decomposition is:

LP fees
- loss-versus-rebalancing / impermanent-loss component
- gas and LP rebalance cost
- hedge trading fees/slippage
- hedge funding
- hedge basis drift
- residual delta/gamma exposure
- collateral/margin opportunity cost
= net hedged LP economics

Required state:

- LP range bounds;
- liquidity;
- token inventory implied by current price;
- unclaimed fees;
- current pool tick/liquidity distribution where available;
- LP delta;
- optional higher-order exposure estimate;
- perp hedge size;
- funding;
- hedge markout/execution cost;
- rebalance threshold;
- out-of-range state;
- capital locked in LP and hedge.

Rules:

- do not call a simple 1:1 short-perp hedge fully delta-neutral if LP delta changes with price;
- do not credit LP fees without LVR/IL and hedge costs;
- use a no-hedge LP, static hedge and dynamic hedge as separate baselines;
- rehedging frequency is optimized only on TRAIN and penalized for turnover;
- options-based IL hedges may be challengers where liquid, but are not required for the first sleeve;
- small LP positions for which gas/hedge minimums dominate remain UNEXECUTABLE.

### LP hedge success criterion

Promotion requires frozen-OOS evidence that the hedged LP sleeve improves conservative net return on capital/time versus:

- unhedged LP;
- passive spot/hold baseline where economically relevant;
- simple static perp hedge;
- no-trade.

Fee income alone is not evidence of alpha.

### Candidate Sleeve — Formula / Index Perpetual Relative Value

Official Hyperliquid documentation states that index perpetuals track a formula instead of an ordinary spot asset price.

Validators periodically publish the index-formula value to Hyperliquid L1, and the median of submitted values replaces the normal spot-oracle input for funding mechanics.

For each formula/index perp store:

- machine-readable formula/version where available;
- component universe;
- component weights;
- conversion/FX rules;
- rebalance schedule;
- announcement timestamp;
- effective timestamp;
- validator publication cadence;
- published index value;
- independently reconstructed index value;
- mark/perp price;
- funding;
- formula/oracle revision history.

Candidate hypotheses:

- index reconstruction residual;
- validator-publication lag versus independently reconstructable components;
- scheduled rebalance/reconstitution flow;
- perp basis to a replicating basket;
- component-to-index Lead-Lag;
- index-perp funding distortion.

### Index-rebalance causality firewall

Historical constituent/rebalance information must be point-in-time.

Do not use:

- future constituent membership;
- final rebalance weights before announcement;
- post-event corrected index values;
- later formula revisions

in earlier decisions.

Announcements and effective times are separate timestamps.

### Formula-index execution boundary

An index residual is not directly executable unless a hedge basket or another equivalent instrument exists.

For a replicating basket, include:

- every component leg;
- component spread/slippage;
- basket execution timing;
- residual tracking error;
- rebalance cost;
- FX/quote conversion;
- partial-fill/legging risk;
- capital requirement.

If only the index perp itself is executable and the formula basket cannot be hedged economically, use the reconstructed index only as a reference/forecast feature rather than claiming arbitrage.

### AMM/index data collection contract

GitHub-hosted collection may use public read-only RPC/API/archive sources without requiring a user PC or self-hosted node.

Store:

- block number / chain timestamp for AMM state;
- RPC provider/source;
- quote/simulation timestamp;
- pool state hash or sufficient reproducibility metadata;
- Hyperliquid receive timestamp;
- index-component source timestamps.

Do not compare an onchain AMM state from one block with a later Hyperliquid state as if synchronous without timing uncertainty.

### V6.19 research priority

V6.19 is initially lower priority than Execution Alpha, XEMM, TWAP and Forced-Flow because AMM/LP strategies add gas, chain-state and inventory complexity.

Promote priority only if discovery shows:

- frequent executable after-cost AMM-perp residuals;
- meaningful independent daily opportunity contribution;
- or a hedged-LP sleeve with robust fee-minus-LVR economics.

### V6.19 research basis

High-signal sources reviewed on 2026-09-26 include:

- Hyperliquid official Uniswap perpetuals documentation;
- Hyperliquid official Index perpetual contracts documentation;
- Uniswap oracle/executable-quote documentation;
- public AMM↔CEX/perp arbitrage implementations that account for pool fees, gas and price impact;
- academic work on delta hedging and market-neutral concentrated-liquidity positions, including impermanent-loss/LVR and capital-cost limitations.

Public bot profitability claims are not imported as Alina evidence.


### Profitability Convergence V6.20 — priority, transport and client-semantics exactness

V6.20 resolves the final current discrepancies found while cross-checking V6.13-V6.18 against the latest official Hyperliquid Markdown documentation, official Python SDK behavior and the continuing X/GitHub corpus review.

The governing rule is:

> **priority, transport and client-wrapper behavior must be modeled as separate layers; a paper edge may not inherit latency, queue position, fill protection or fee treatment from an infrastructure path Alina does not actually possess.**

V6.20 adds no new alpha module. It tightens the executability proof for Execution Alpha, XEMM, Lead-Lag, Cross-Venue, Scheduled Flow and any queue-sensitive sleeve.

### Priority-fee capability contract

For every priority-capable action, record point-in-time:

- priority mechanism: `NONE / GOSSIP_READ / IOC_WRITE / ALO_QUEUE`;
- raw priority parameter;
- interpreted rate;
- eligible asset class;
- eligible TIF/order family;
- reduce-only eligibility;
- batch homogeneity requirement;
- charging basis;
- charging time;
- charging balance/currency;
- conversion reference;
- burn/destination rule;
- queue/mempool effect;
- source rule revision.

Current official documentation reviewed on 2026-09-26 states that write-priority grouping is accepted only when:

1. every order is on a **non-outcome** asset; and
2. the action is homogeneous: either every order is IOC, or every order is a **non-reduce-only ALO**.

A mixed IOC/ALO priority batch is therefore invalid under the current rule.

A priority-enabled paper policy must fail closed if its batch composition is invalid.

### Priority-fee unit and payment exactness

Current official write-priority rate uses:

```text
priority_rate = p / 100_000_000
```

with examples such as `p = 10000` representing 1 basis point.

Current official charging basis differs by order family:

- IOC: priority charge is based on **filled notional**;
- ALO: priority charge is based on **resting notional** and is charged at placement.

Current official payment semantics state that order-priority cost is charged from **undelegated staking balance**, converted to HYPE using the **spot mark price**, and burned.

Therefore paper accounting distinguishes:

- ordinary trading fee;
- builder/deployer fee;
- IOC priority gas;
- ALO placement priority gas;
- gossip/read-priority auction cost.

Do not charge all priority mechanisms to the same balance or at the same lifecycle event.

### IOC priority — exact current ordering semantics

Current official IOC priority behavior includes:

- temporal prioritization responds approximately linearly in the **0-8 bps** region;
- current empirical mainnet effect is approximately **45 ms lower end-to-end latency per 1 bp** in that useful region;
- priority above 8 bps does not buy additional ordinary temporal preference;
- the maximum priority rate itself can extend to **100%** under the current rule;
- sufficiently high-priority IOC orders that fall into the same proposer time bucket can still be ranked by priority rate;
- current documentation describes proposer buckets on the order of **70 ms** for this tie-breaking behavior;
- all cancels remain ahead of immediately executable orders under the documented ordering class.

Replay requirements:

- do not clamp the *parameter* to 8 bps merely because temporal benefit saturates there;
- do cap ordinary time-shift benefit at the documented saturation rule;
- if testing >8 bps, account only for the documented same-time/same-bucket ranking effect plus the full fee;
- `priorityGas` from node/user-fill evidence is reconciled where available;
- the current 45 ms/bp figure is an empirical/versioned prior, not a guaranteed deterministic latency reduction.

### ALO priority — continuous 400 ms queue-tail semantics

Current official ALO priority is a queue-position mechanism, not a mempool-latency mechanism.

At each price level:

- the queue tail consisting of orders placed within the previous **400 ms** is priority-sortable;
- the window is **continuous**, not bucketed;
- a newly placed ALO compares against orders still inside that rolling tail;
- once older queue structure has effectively locked, a later high-priority ALO cannot leapfrog arbitrarily old resting orders;
- ALO priority does not accelerate transaction arrival in the mempool;
- ALO actions remain processed under their ordinary transaction ordering class;
- the priority mechanism changes same-level queue position after application to the L1;
- ALO priority cost is charged at placement whether or not the order ever fills.

Replay must therefore distinguish:

```text
transaction_arrival_order
!=
same_price_queue_order_after_ALO_priority
```

The simulator must not model ALO priority as a generic latency subtraction.

For current rule reconstruction, ALO priority cost in USDC-equivalent terms may be derived from the documented resting notional and priority rate when the required source fields are present.

An unfilled priority ALO can have negative realized value purely from placement cost.

### Cancel / ALO / IOC ordering class

Official latency documentation states that Hyperliquid intentionally protects makers by sequencing cancels and ALO actions ahead of IOC/GTC taker-style actions submitted at similar times.

It also states that this behavior can span multiple blocks and that within a consensus bundle ALO/cancel actions are processed before the other action class.

Important precision:

- documentation uses language equivalent to **"almost always"**, not an absolute mathematical guarantee across every network path;
- paper replay therefore models this as a venue/version ordering rule with uncertainty where exact block/action ordering is absent;
- an IOC priority fee cannot be credited with overtaking a cancel when the documented class ordering places cancels first;
- a CEX-style "first packet received wins" assumption is invalid for Hyperliquid.

### Gossip/read priority — separate economic surface

Read priority is distinct from write/order priority.

Current official documentation describes:

- **2 independent Dutch auctions**;
- synchronized on a **3-minute** schedule;
- each auction affects the following auction interval;
- lower slot indices are strictly prioritized over higher slot indices for nodes that opt into the scheme;
- multiple slots are not additive for the same IP; the lowest/best slot governs that ordering;
- the onchain IP must match the peer-visible IP for the priority to matter;
- individual network hops may or may not respect the priority ordering;
- current minimum auction price is **0.1 HYPE**;
- gossip-priority bid gas is denominated in HYPE from spot balance and burned under the current rule;
- current empirical mainnet effect is approximately **25 ms latency reduction per auction slot**;
- current auction state is queryable through the documented `gossipPriorityAuctionStatus` info request.

These numbers are versioned.

### GitHub-hosted latency boundary

Alina's current architecture must **not** pretend to possess node/gossip infrastructure that it does not run.

Official latency documentation states that:

- `split_client_blocks` on a node can expose pending transaction inputs before client-block inclusion;
- current documentation estimates roughly **70-150 ms** read-latency improvement from that path;
- those early inputs do **not** yet include final execution results;
- running a local/non-validating node can provide more granular/faster state than the public API.

Under Alina's explicit GitHub-hosted-only rule:

- no self-hosted Hyperliquid node is introduced;
- no user-PC node is introduced;
- node/gossip priority is not credited to Alina's executable latency unless an actually available remote/cloud source with certified timing exists;
- node-class latency is treated as a **competitor/infrastructure latency frontier** and stress scenario;
- an edge that requires split-client-block or privileged peer timing unavailable to GitHub-hosted Alina is labeled `UNEXECUTABLE_CURRENT_ARCHITECTURE`, even if a professional colocated/node strategy could exploit it.

This prevents public HFT bots from making Alina's paper results look achievable merely because their infrastructure is faster.

### End-to-end latency versus sequencing latency

Hyperliquid's documented latency model is not identical to a centralized exchange.

Current official material notes:

- end-to-end write latency includes API-server travel, mempool inclusion and consensus commit;
- commit commonly spans roughly two pipelined HyperBFT blocks under the current architecture;
- cancel/ALO end-to-end time can be hundreds of milliseconds while transaction ordering can remain much more predictable;
- current documentation gives an example around **380 ms** end-to-end for cancel/ALO while controlled relative send timing can exhibit much lower ordering variance.

Therefore Alina must store separately:

- absolute end-to-end latency;
- relative sequencing/ordering latency;
- queue insertion time;
- data-observation latency;
- consensus/application timestamp.

A large absolute latency does not imply equally noisy relative ordering.

### Market-order client-wrapper semantics

The official Hyperliquid Python SDK does not submit a protocol-level "infinite market order."

Current SDK behavior reviewed on 2026-09-26 implements `market_open` / `market_close` as an **aggressive IOC limit order**.

The current SDK default helper behavior:

- obtains a reference from `allMids` when no explicit price is supplied;
- applies a default **5% slippage envelope** in the SDK helper;
- normalizes the resulting limit price to protocol precision;
- submits an IOC limit;
- uses reduce-only for the close helper.

Critical distinctions:

- the SDK's 5% default is a **client-library default**, not a universal protocol constant;
- frontend/UI slippage settings can differ;
- TP/SL-market uses its own documented current slippage semantics;
- `allMids` may itself use fallback provenance already handled by V6.14;
- actual fill still requires executable book liquidity and can partially fill/cancel.

Therefore paper "market" execution always records:

`MARKET_INTENT -> CLIENT_PROTECTION_LIMIT -> IOC_MATCHING -> PARTIAL/FULL/NONE`.

No module may assume unlimited-depth market fills.

### Action-transport feasibility without live signing

V6.20 records transport constraints for **paper feasibility only**.

Official nonce documentation currently states:

- Hyperliquid stores a bounded set of recent nonces per signer rather than requiring strict sequential Ethereum-style nonces;
- the current implementation stores the **100 highest nonces** per signer;
- a new nonce must exceed the lowest retained nonce and must not have been used;
- current accepted nonce time window is approximately `T - 2 days` to `T + 1 day`;
- different subaccounts using the same API/agent signer share that signer nonce state;
- official guidance recommends batching automated order/cancel requests and separating ALO-only batches from IOC/GTC batches because ALO-only batches receive their own prioritization behavior.

Alina does **not** create or use API wallets/private keys.

These rules enter only a hypothetical feasibility ledger:

- can the claimed action rate be represented by a realistic batching policy?
- would batch composition destroy priority eligibility?
- would a shared-signer architecture create a throughput/nonce collision bottleneck?
- is the paper strategy dependent on transport engineering that the current project explicitly does not operate?

No nonce/signature code belongs in the research hot path.

### Batch-class purity

Because execution ordering and priority eligibility differ by action class, paper batching must preserve class composition.

When replaying a hypothetical batching policy:

- ALO-only;
- IOC-only;
- GTC/taker-style;
- cancels;
- modify/cancel-replace;

remain separately attributable unless the historical venue rule explicitly allows mixed semantics.

Do not merge incompatible actions into one synthetic batch to reduce modeled latency or API cost.

### Priority evidence sources

Prefer source-native evidence:

- IOC priority gas: node/user-fill `priorityGas` where available;
- ALO priority: order action/grouping + resting notional + raw-book/ordering evidence where available;
- gossip auction: auction-status and replica/node evidence where available;
- priority rule: official versioned documentation.

If only ordinary fills exist:

- IOC priority cost may be partially observable;
- ALO placement costs and same-level queue reordering can remain incomplete;
- missing placement evidence becomes `PRIORITY_PLACEMENT_UNMEASURABLE`, never zero.

### Priority competition as a target-gap diagnostic

Priority fees can consume a large fraction of tiny latency-sensitive alpha.

For every priority-sensitive sleeve report:

- gross edge before priority;
- priority rate;
- priority cost;
- estimated latency/queue benefit;
- post-priority edge;
- break-even priority rate;
- fraction of gross edge transferred to priority cost;
- whether a no-priority slower route dominates.

This is especially important for:

- Lead-Lag;
- taker Cross-Venue;
- XEMM hedge urgency;
- HIP-3 short-horizon dislocations;
- queue-sensitive maker alpha.

If competitive priority cost absorbs the edge, that is a valid `KILL` reason.

### V6.20 source reconciliation rule

When two official renderings/snippets appear inconsistent:

1. fetch the current Markdown page where possible;
2. preserve publication/revision timing;
3. compare first-party SDK/examples if relevant;
4. distinguish current rule from historical rule;
5. use `RULE_VERSION_UNCERTAIN` when the applicable historical semantics cannot be pinned.

In this pass, the current Markdown priority page resolves the apparent HTML/snippet discrepancy and explicitly documents both IOC and ALO priority families.

### V6.20 official-source basis

Verified on 2026-09-26 against:

- Hyperliquid official Priority Fees Markdown;
- Hyperliquid official Optimizing Latency documentation;
- Hyperliquid official Nonces and API Wallets documentation;
- Hyperliquid official Self-Trade Prevention / Exchange endpoint / Rate-limit documentation;
- the official Hyperliquid Python SDK market-order helper implementation;
- Parallel Search cross-check of the current official Markdown priority section.

All values remain versioned and may not be back-applied to earlier periods without rule evidence.


### Profitability Convergence V6.21 — frontend analytics non-authority

V6.21 closes the final two pages in the current official Hyperliquid Trading documentation index that had not yet been represented explicitly in Alina: Portfolio graphs and Miscellaneous UI.

The governing rule is:

> **frontend analytics are useful reconciliation views, but they cannot replace event-level ledger truth for proving net PnL, drawdown, capacity or the +4 USD/day milestone.**

### Portfolio-graph sampling contract

Current official Hyperliquid documentation states that portfolio account-value/PnL graphs are sampled:

- on deposits and withdrawals; and
- approximately every 15 minutes.

The documentation explicitly warns that these samples are not recommended for precise accounting because interpolation between samples may fail to reflect actual unrealized-PnL changes.

Therefore:

- graph samples are stored only as coarse reconciliation/checkpoint evidence;
- they are never used as the primary fill/funding/fee/collateral ledger;
- intraperiod extrema cannot be reconstructed from 15-minute graph samples unless stronger event data exists;
- a strategy drawdown, peak equity or daily net PnL cannot be certified from graph interpolation alone;
- missing event-level evidence is not repaired by visually smooth interpolation.

### Portfolio graph PnL provenance

Current official documentation describes the portfolio graph PnL field using its frontend account-value/deposit/withdrawal relationship.

Alina stores the exact venue-reported graph field and its documented definition as a display/reconciliation measure, while the strategy proof ledger remains constructed from:

- fills/trades;
- trading fees and rebates;
- funding transfers;
- collateral/borrow interest;
- deposits/withdrawals/transfers;
- liquidation/backstop/ADL effects;
- settlement/delisting effects;
- point-in-time mark state for unrealized PnL.

Do not silently redefine the venue graph field to make it agree with Alina accounting. Any difference is a reconciliation exception to explain.

### UI maximum-drawdown non-authority

Current official documentation states the portfolio-page max drawdown is a frontend convenience value and does not affect Hyperliquid margining or protocol computations.

The current documented UI formula is the maximum over end > start of:

(pnl(end) - pnl(start)) / account_value(start)

using the account value associated with each candidate start point.

Consequences:

- UI max drawdown is not treated as the canonical risk metric for Alina;
- Alina computes its own drawdown from the certified equity/event ledger at the resolution required by the strategy;
- UI drawdown may be retained as a reconciliation metric;
- a mismatch between UI and Alina DD is investigated rather than averaged;
- sampled UI history cannot prove the absence of a deeper intraperiod drawdown.

### Proof-ledger precedence

For all performance claims, precedence is:

1. certified raw/reconstructed event ledger;
2. reconciled account/collateral/funding state;
3. venue-provided derived analytics;
4. frontend chart/UI samples.

A lower-precedence source cannot overwrite a higher-precedence source merely because it is easier to query.

### V6.21 official-source basis

Verified against the current official Hyperliquid Portfolio graphs and Miscellaneous UI documentation on 2026-09-26.

These rules close documentation coverage; they do not create a new alpha hypothesis.


### Profitability Convergence V6.22 — fill, websocket and reconciliation exactness

V6.22 closes the remaining data-plane details that can silently alter fill count, fee attribution, queue evidence or collector continuity.

The rule is:

> **raw execution evidence is preserved at the finest causally available granularity; aggregation and frontend convenience fields may be derived later, but never replace canonical fills/order state.**

### Canonical fill-granularity rule

Hyperliquid `userFills` and `userFillsByTime` support `aggregateByTime`.

Current official semantics state that when aggregation is enabled:

- a crossing order filled by multiple resting orders can have partial fills combined;
- a resting order filled by multiple crossing orders is aggregated only when those fills are in the same block.

Therefore:

- canonical replay/execution evidence uses **unaggregated fills** whenever available;
- `aggregateByTime=true` is permitted only for derived analytics/compact summaries;
- queue, adverse-selection, partial-fill timing, implementation shortfall and maker/taker attribution cannot be certified from an aggregated stream when the aggregation destroys required detail;
- if only aggregated history exists for a period, mark execution granularity `AGGREGATED_FILL_EVIDENCE` and downgrade claims accordingly.

### Fill identity and deduplication

Current `WsFill` exposes fields including:

- `tid`: unique trade id;
- `oid`: order id;
- L1 transaction `hash`;
- timestamp;
- coin;
- side;
- price;
- size;
- `crossed`;
- fee;
- fee token;
- optional builder fee;
- liquidation metadata where applicable.

Use source-native `tid` as the primary trade identity where present.

A robust dedup key may include source/DEX + `tid`, with hash/oid/time used for reconciliation and corruption detection.

Do not use timestamp+price+size alone as a unique fill key.

### Fee-field anti-double-counting

Current official fill schema states:

> `builderFee` is already included in `fee`.

Therefore:

- canonical fill cash flow charges `fee` exactly once;
- `builderFee` is a fee-attribution component, not an additional cost added on top of `fee`;
- negative `fee` remains a rebate and preserves sign;
- `feeToken` is explicit and any conversion to USD/reference value uses point-in-time conversion;
- builder/deployer/referral/priority attribution must reconcile to total fee/cost ledgers without double counting.

A candidate is invalid if its +4 USD/day proof depends on adding or subtracting a component twice.

### Maker/taker truth from fill evidence

Current `WsFill.crossed` identifies whether the order crossed the spread.

Use the venue-native field as first-choice maker/taker evidence when available.

Do not infer maker/taker solely from:

- side;
- order type label;
- whether the submitted limit price was aggressive;
- post-hoc BBO reconstruction.

Those may be cross-checks, not replacements for direct fill evidence.

### Snapshot versus incremental stream semantics

For streaming user endpoints that expose `isSnapshot`:

- the initial snapshot is bootstrap state/history, not a burst of new events;
- subsequent `isSnapshot=false` messages are incremental events;
- reconnect snapshots are deduplicated against committed identities;
- snapshot watermark and reconnect time are persisted;
- a row seen in both a reconnect snapshot and prior committed stream is counted once.

This applies especially to fills and funding streams.

For state-style subscriptions whose first message is a full state and later messages are deltas/changed entities, persist the bootstrap/delta boundary explicitly.

### WebSocket idle timeout / heartbeat exactness

Current Hyperliquid WebSocket documentation states that the server closes a connection if it has not **sent** a message on that connection for 60 seconds.

For quiet subscriptions:

- collector emits documented `{"method":"ping"}` heartbeats before idle timeout;
- `pong` is health evidence, not a market event;
- heartbeat messages are excluded from trading/event counts;
- heartbeat failure promotes connection health to `DEGRADED/STALE`;
- reconnect uses snapshot/reconciliation before returning the feed to `HEALTHY`.

Low-activity markets must not appear to have data gaps simply because no market event occurred for a minute.

### Reconnect repair contract

Official docs state missed data during reconnect can be present in snapshot acknowledgement and can also be repaired through the corresponding info request.

Collector recovery sequence:

1. mark connection degraded;
2. persist last committed source identity/time;
3. reconnect;
4. process bootstrap snapshot as reconciliation evidence;
5. query repair endpoint where needed;
6. deduplicate by source-native identities;
7. verify monotonic continuity / expected coverage;
8. only then return to healthy incremental mode.

A reconnect is not considered repaired merely because the socket reopened.

### CLOID / OID reconciliation

Hyperliquid supports:

- venue order id `oid`;
- optional client order id `cloid`;
- current CLOID format as a 128-bit hex identifier;
- status query by either oid or cloid;
- cancel-by-cloid where applicable.

Paper/replay ledgers therefore retain both when present.

Rules:

- never replace the venue oid with cloid;
- cloid is provenance/reconciliation identity, not trade identity;
- status lookup result `unknownOid` is not interpreted as proof that an order never existed without checking collection gaps/account scope;
- modify/cancel history preserves old/new identity relationships;
- client-generated identifiers cannot collide across simulated strategies without a namespace policy.

### Account / DEX scope exactness

Read-only queries are account- and sometimes DEX-scoped.

Current official `openOrders` semantics default to the first perp DEX when DEX is omitted; spot open orders are included with the first perp DEX.

Therefore:

- multi-DEX collectors specify and store DEX scope explicitly;
- absence from a query with the wrong/default DEX is not evidence of no order;
- account address used for state lookup is stored separately from any hypothetical signer/agent identity;
- no API-wallet address is used as a substitute for the master/subaccount state address.

This is a read-model rule only; Alina still operates without signing wallets.

### OrderUpdates versus OpenOrders role separation

Use:

- `openOrders` / `frontendOpenOrders` as point-in-time state/bootstrap;
- `orderUpdates` as lifecycle change evidence;
- fills as execution evidence;
- historical/order-status queries as reconciliation/backfill.

No one source alone is assumed complete for every lifecycle transition.

Especially:

- STP cancel can occur without a trade print;
- trigger state can change before fill;
- liquidation/delisting/scheduled-cancel states can terminate orders outside ordinary user cancel flow.

### Frontend metadata boundary

`frontendOpenOrders` and `FrontendMarket` expose useful UI/order semantics.

Use them for:

- trigger classification;
- frontend-origin/order-type provenance;
- TP/SL interpretation;
- builder/flow-provenance research.

Do not infer a fundamentally different matching engine from a frontend label unless the protocol rule actually differs.

### Scale-order classification

Current official order-type documentation describes `Scale` as multiple limit orders distributed over a price range.

Until a stronger source defines a server-native parent lifecycle:

- treat Scale as an **execution decomposition/controller**, not a unique alpha source;
- retain child limit orders as the canonical executable units;
- charge every child fee/queue/latency effect;
- do not award a fictional atomic parent fill;
- compare Scale only against simpler passive ladder / adaptive execution baselines.

### Feed-rate and subscription feasibility

Current documented WebSocket limits remain feasibility inputs, including current maxima for:

- connections;
- new connections/minute;
- subscriptions;
- unique users on user-specific streams;
- sent messages/minute;
- simultaneous inflight WS post requests.

A broad Copy-Vault/trigger-map design that exceeds these public-interface limits must:

- shard within allowed hosted resources;
- reduce/rotate coverage;
- use archive/batch sources;
- or report coverage as constrained.

It cannot silently assume unlimited per-wallet streaming.

### V6.22 source basis

Verified on 2026-09-26 against current official Hyperliquid:

- Info endpoint;
- WebSocket subscriptions;
- WebSocket timeout/heartbeat docs;
- Exchange endpoint;
- L1 data schema;
- Builder Codes docs;
- Rate limits/user limits;
- order types.

All semantics remain versioned.



### Profitability Convergence V6.23 — final market-rule exactness

V6.23 closes the remaining current official Hyperliquid execution/accounting details found during the final X/GitHub corpus and documentation pass.

The rule is:

> **a paper result is invalid if it depends on an order, trigger, funding payment, batch, cancel or TWAP behavior that the venue would not have permitted at that timestamp.**

V6.23 adds no new alpha module. It makes the existing modules and execution layers harder to fool.

### Self-trade prevention — exact expire-maker behavior

Current official Hyperliquid self-trade prevention behaves as **expire maker**:

- when the same address would trade with itself, the resting maker order is canceled instead of filled;
- no trade fee is charged for that prevented self-trade;
- the prevented self-trade does not appear as a normal trade in the trade feed;
- the aggressing order may continue matching liquidity behind the canceled resting order up to its own limit.

Therefore:

- `selfTradeCanceled` is an order-lifecycle event, not a fill;
- Portfolio Intent Netting should reduce avoidable self-crossing before simulated external execution;
- if a simulated aggressing order meets Alina's own resting paper order, cancel the resting order first under the applicable STP rule and continue evaluating remaining external depth;
- never create two fills, two fees or artificial volume from a prevented self-trade;
- STP behavior is versioned and address/account scoped.

### Price/size precision — exact validity

For the current documented Hyperliquid rule:

- price accepts at most **5 significant figures**;
- perp price decimals are additionally bounded by `6 - szDecimals`;
- spot price decimals are additionally bounded by `8 - szDecimals`;
- integer prices remain valid regardless of the five-significant-figure rule;
- size precision is limited to the instrument's `szDecimals`;
- order price/size must satisfy the effective tick/lot rule.

Paper normalization must be side-aware and conservative.

Record:

- requested price;
- requested size;
- normalized protocol-valid price;
- normalized size;
- direction and magnitude of rounding;
- whether normalization changes expected edge;
- reject reason if no valid economically equivalent order remains.

No strategy may receive a more favorable paper fill because an invalid requested price was rounded opportunistically.

### TP/SL trigger and child-lifecycle exactness

Current official semantics include:

- TP/SL is triggered by **mark price**, not last trade or BBO;
- TP/SL market orders currently use a documented slippage tolerance of **10%**;
- TP/SL limit orders may trigger and then remain resting if their limit is not executable;
- position TP/SL can target the entire current position or a configured fixed size depending on placement semantics;
- order-associated child TP/SL lifecycle depends on the parent order.

For parent-associated TP/SL:

1. if the parent fully fills, children become active;
2. if the parent is not fully filled and is normally canceled, its children are canceled;
3. if the parent is partially filled and the user cancels it, the children are fully canceled;
4. current documentation states an important exception: if the parent is partially filled and then canceled because of **insufficient margin**, child TP/SL orders are placed as if the parent had fully filled.

Replay must preserve this exception rather than assuming all partial-parent cancellations behave identically.

Requirements:

- trigger evaluation uses point-in-time mark state;
- trigger timestamp is separate from child-order execution timestamp;
- triggered market/limit behavior follows the child order's actual executable limit/slippage protection;
- sibling-filled cancellation and reduce-only behavior remain explicit lifecycle states;
- position size changes after a fixed-size TP/SL does not silently resize that order unless the documented order type does so.

### Native TWAP execution exactness

Current official Hyperliquid native TWAP behavior includes versioned limits/semantics such as:

- running time currently configurable from **5 minutes to 7 days**;
- child intervals are at least **30 seconds**;
- current minimum total TWAP notional is **$100**;
- child size can be randomized by up to the documented range when randomization is enabled;
- each suborder currently has a maximum slippage constraint of **3%**;
- TWAP maintains an elapsed-time execution target;
- when earlier children underfill, later children may catch up;
- current catch-up child size is capped at **3x the normal child size**;
- the TWAP may still finish with residual unfilled quantity;
- during a network-upgrade post-only period, normal market/TWAP child execution can be temporarily unable to fill;
- trigger/max/min-price controls are mark-price conditioned under the current order-type rules.

Scheduled-Flow research must therefore distinguish:

- parent target schedule;
- child creation schedule;
- child attempted size;
- child filled size;
- catch-up quantity;
- residual completion shortfall;
- trigger/termination condition.

Do not reconstruct a smooth theoretical TWAP path when the actual protocol would have fallen behind or failed to complete.

### Funding formula and cash-flow exactness

For current standard Hyperliquid perps:

```text
FundingRate_8h
= AveragePremiumIndex
  + clamp(interest_rate - AveragePremiumIndex, -0.0005, 0.0005)
```

Current documented details include:

- interest-rate component of **0.01% per 8 hours**;
- premium sampled every **5 seconds** and averaged over the hour;
- hourly funding payment applies **1/8** of the computed 8-hour rate;
- current funding cap is **4% per hour**;
- standard premium uses impact bid/ask versus oracle;
- HIP-3 perps use a different, more responsive premium formulation;
- funding payment uses:
  `position_size * oracle_price * funding_rate`;
- oracle price, not mark price, is the notional conversion reference for that standard funding cash flow.

Therefore:

- funding cash-flow replay uses the actual position held at the settlement boundary;
- a position opened after a settlement does not receive/pay that prior settlement;
- realized funding is ledger cash flow, not price PnL;
- current funding and `predictedFundings` are features, not settled future cash flow;
- `predictedFundings` coverage is only assumed for the venue/DEX scope documented by the endpoint;
- standard-perp and HIP-3 funding formulas remain separate and versioned;
- current rate/cap/formula cannot be back-applied to periods with unknown historical rules.

### Impact-price and premium provenance

When `impactPxs`, premium, mark, oracle and mid are returned together:

- keep the venue fields separately;
- do not reconstruct one from another unless the exact formula/input notional is known for that rule version;
- null `impactPxs` or premium remains missing, not zero;
- impact notional is contract/spec specific and versioned;
- final capacity still uses executable depth rather than assuming the venue-supplied impact field is sufficient.

### Modify / cancel / expiry exactness

Current exchange semantics require explicit treatment of:

- `expiresAfter`;
- normal cancel;
- fast cancel;
- scheduled cancel;
- modify;
- batchModify;
- `always_place`.

Current documented details include:

- stale `expiresAfter` actions can consume **5x** the usual address-based action-rate allowance;
- fast-cancel requests cannot currently be used for trigger orders;
- schedule-cancel time must be at least **5 seconds** in the future;
- current scheduled-cancel trigger count is capped at **10 per day**, resetting at 00:00 UTC;
- with `always_place=true`, the replacement/new order may be placed regardless of whether the cancel succeeded;
- with `always_place=false`, the documented replacement semantics are more restrictive and can force eligible GTC replacement behavior into ALO-style non-executable placement;
- modify is not treated as a timeless atomic CEX edit unless the rule/version explicitly proves atomicity.

Paper execution must model cancel/replace exposure accordingly.

### Batch pre-validation exactness

Hyperliquid batch behavior can fail in two different ways:

1. per-order/per-cancel status vector; or
2. an earlier deterministic **pre-validation failure** that returns one error for the entire batch.

Examples of pre-validation-class failure can include invalid batch structure, invalid TP/SL construction, price/reference constraints or some tick validation failures.

Therefore:

- if historical/current rule implies whole-batch pre-validation failure, every child action in that paper batch is rejected;
- do not selectively fill valid-looking children from a batch that the venue would reject as a whole;
- batch error shape is part of replay evidence;
- batching policy remains part of execution feasibility and priority eligibility.

### Open-order and action-limit exactness

Current documented user limits include:

- default open-order limit of **1000**;
- one additional open order per **5M USDC** of cumulative volume;
- cap of **5000** total open orders;
- when at least 1000 other orders are already open, newly placed reduce-only or trigger orders can be rejected under the current rule.

Current action-rate behavior also includes:

- address-based quota related to cumulative traded notional;
- an initial request buffer;
- larger cancellation allowance than ordinary actions;
- a batched action counts as one request for IP-based limits but as **n actions** for address-based limits when it contains n child orders/cancels;
- during high congestion, block-space use can be constrained by a multiple of the previous day's maker-share allocation, with asset weighting affecting that share under the current rule.

Paper-only Alina does not consume live action quota, but feasibility reports must model whether a hypothetical policy could actually sustain its quote/cancel/order rate.

### Congestion-state execution feasibility

Add execution feasibility state:

`NORMAL / CONGESTED / ACTION_LIMITED / ORDER_LIMITED / UNKNOWN`.

When current/historical congestion or user-limit state is unavailable:

- do not claim high-frequency quote/cancel feasibility as certain;
- stress the strategy under reduced action throughput;
- preserve cancel priority/safety assumptions separately from new-order throughput;
- do not infer profitability from a paper policy requiring impossible refresh frequency.

### Mark/oracle cadence exactness

Current official robust-price documentation states:

- oracle updates occur approximately every **3 seconds**;
- mark is updated with validator oracle publication;
- mark is used for margining, liquidation, TP/SL triggering and unrealized PnL;
- oracle participates in funding and mark construction.

Therefore:

- TP/SL/liquidation state can update discretely with oracle/mark publication rather than on every BBO tick;
- a BBO crossing a trigger level before mark crosses it is not sufficient to trigger a mark-based TP/SL;
- replay stores BBO/event time and mark/oracle update time separately.

### Current-rule versioning firewall

All numerical values in V6.23 are tagged as **current rules verified 2026-09-26**.

Any historical replay must prefer:

1. archived first-party rule/spec evidence for the historical timestamp;
2. contemporaneous metadata/status evidence;
3. explicit rule-version intervals;
4. otherwise `UNMEASURABLE_RULE_VERSION`.

Do not silently apply the 2026 rule to older data.

### V6.23 completion standard

After V6.23, a strategy may not claim executable net PnL unless its paper engine can account for, when relevant:

- valid price/size precision;
- min notional;
- partial fills;
- queue/latency uncertainty;
- STP;
- trigger reference;
- child TP/SL lifecycle;
- native TWAP catch-up/residual behavior;
- exact funding cash flow;
- modify/cancel races;
- batch rejection;
- action/open-order feasibility;
- priority/fee state;
- mark/oracle timing;
- venue health.

Missing evidence remains `UNMEASURABLE`, never converted into a favorable default.

### V6.23 official-source basis

Verified on 2026-09-26 against current official Hyperliquid documentation covering:

- Funding;
- Robust price indices;
- Take profit and stop loss;
- Order types;
- Self-trade prevention;
- Exchange endpoint;
- Error responses;
- Tick and lot size;
- Rate limits and user limits;
- Perpetual metadata/info endpoints.

Parallel Search was used as a cross-check; official Hyperliquid documentation remains authoritative for protocol semantics.


### Canonical rule provenance and serialization closure

This section closes remaining specification-level ambiguity left by the historical research tranches.

It adds no new strategy family. Its job is to make protocol semantics, identifiers, units, signs, serialization and acceptance IDs machine-auditable so that a few basis points cannot be created by representation drift.

> **Every market rule used in proof must be attributable to an exact source/version, every value must have explicit units/sign/time semantics, and every acceptance criterion must have one unique canonical ID.**

### Canonical acceptance-ID contract

The acceptance catalog is a machine-addressable interface.

Requirements:

- every canonical acceptance criterion has one unique integer ID;
- IDs are strictly increasing for newly appended criteria;
- a spec validation test rejects duplicate IDs;
- renumbering requires an explicit migration map rather than silent reuse;
- implementation tests may reference the stable acceptance ID plus a short semantic slug;
- headings/list numbering elsewhere in the document are not interpreted as acceptance IDs unless they are inside the canonical acceptance section.

### Protocol rule provenance manifest

Every venue rule that can affect PnL, admissibility, fill state, margin, liquidation, funding, queue priority, fees or capacity is represented by a versioned manifest row with, where available:

- venue;
- DEX/deployer scope;
- instrument class;
- rule family;
- official source URL/path;
- source publication/revision date;
- collection timestamp;
- source-content hash or immutable revision identifier;
- effective-from timestamp;
- effective-until timestamp;
- confidence in historical applicability;
- parser/extractor version;
- normalized value plus unit;
- raw source excerpt/reference retained outside hot-path decision state.

Rule applicability states include:

- CERTIFIED_CURRENT;
- CERTIFIED_HISTORICAL;
- BOUNDED_BY_KNOWN_CHANGE;
- RULE_VERSION_UNCERTAIN;
- UNMEASURABLE.

Current documentation is never silently treated as historical truth.

### Official-source conflict resolution

When official docs, SDK behavior, API schema or first-party examples disagree:

1. preserve each conflicting source;
2. prefer the most recent controlling protocol documentation/runtime evidence for current semantics;
3. do not average contradictory rules;
4. create separate historical rule versions when activation boundaries are known;
5. use conservative sensitivity or UNMEASURABLE when the historical boundary cannot be certified.

A public third-party wrapper cannot override first-party protocol semantics merely because it is easier to query.

### Canonical instrument identity

A symbol string alone is never sufficient instrument identity.

Every normalized instrument key includes enough point-in-time namespace information to distinguish:

- venue;
- DEX/deployer;
- asset/instrument type;
- venue-native asset identifier/index when available;
- canonical coin/symbol label;
- collateral/quote token;
- oracle/reference family;
- contract/payoff version;
- metadata revision/effective interval.

Rules:

- same ticker across different DEXs/deployers is not automatically the same instrument;
- spot, standard perp, HIP-3, Hyperp, formula/index perp, AMM-oracle perp and HIP-4 outcome remain distinct identity classes;
- asset-index mappings are resolved from point-in-time metadata rather than hard-coded forever;
- identifier reuse after delisting/migration cannot silently join two economically different histories.

### Canonical time contract

Every timestamp field carries an explicit semantic and unit.

At minimum distinguish:

- exchange event time;
- block/sequence time where applicable;
- collector receive time;
- local monotonic ordering time where available;
- decision time;
- modeled send/arrival/ack/fill/cancel-effective time;
- publication time;
- first-observed time;
- settlement/effective time.

Requirements:

- epoch unit is explicit, normally milliseconds where the source uses milliseconds;
- all wall-clock values normalize to UTC without losing the raw source representation;
- timezone/session calendars remain versioned for HIP-3/RWA/event research;
- equal timestamps use stable sequence/tie-break evidence rather than arbitrary dataframe row order;
- conversion between seconds/milliseconds/microseconds is tested with boundary fixtures.

### Canonical numeric/unit contract

Every economically relevant numeric field carries an explicit unit and scale.

Examples include:

- price currency;
- size in base units/contracts;
- notional in quote/reference currency;
- fee/funding rates in decimal versus bps;
- priority rate encoding versus economic bps;
- percentage versus fraction;
- leverage multiplier;
- latency unit;
- volume/notional bucket unit;
- oracle/mark conversion currency.

Rules:

- internal math uses Decimal/fixed-point or equivalent deterministic representation where precision affects order validity/accounting;
- binary float formatting cannot change tick validity, minimum notional, fee amount or fill eligibility;
- bps-to-decimal conversions are centralized and tested;
- negative fee/rebate/funding signs are preserved rather than absolute-valued.

### Canonical cash-flow sign contract

Every ledger entry is normalized to one account-value sign convention.

Store separately:

- trade cash flow;
- realized PnL;
- unrealized PnL;
- trading fee;
- rebate;
- builder/deployer/priority attribution;
- funding payment/receipt;
- borrow interest;
- collateral FX change;
- liquidation/backstop/ADL transfer;
- settlement/delisting cash flow;
- deposit/withdrawal/transfer.

Do not infer sign from UI color, string formatting or field name alone. Reconciliation fixtures must include both positive and negative examples.

### Exact optional-field serialization semantics

Paper Alina never signs actions, but feasibility fixtures preserve protocol serialization rules that can determine whether a hypothetical payload would be accepted.

Where current protocol encoding requires an optional boolean/field to be omitted rather than encoded as explicit false/null, fixtures model the omission semantics exactly.

This includes versioned handling for fields such as fast-cancel and always-place where applicable.

Serialization feasibility is never permission to generate keys, signatures or live actions.

### Order/status enum forward-compatibility

Known order/status/rejection values are mapped explicitly, but the parser must preserve unknown future enum values losslessly.

Unknown statuses:

- are stored raw;
- do not default to filled/canceled/rejected;
- block only dependent exactness paths;
- trigger schema-drift alert/review;
- remain replayable after the parser is upgraded.

### Schema-drift and metadata-drift detection

For every critical API/WS/archive schema track:

- field set;
- nullable/non-nullable behavior;
- enum set;
- numeric/string representation;
- timestamp units;
- pagination/cursor behavior;
- snapshot/incremental semantics;
- DEX/account scope.

A compatible additive field does not break collection, while a semantic change to an existing field creates a new schema/rule version.

### Completeness matrix as release gate

The specification-completeness matrix covers at minimum:

- instrument identity and metadata;
- tick/lot/precision/min-notional;
- source tier BBO/L2/L3/L4;
- sequence/gap/reconnect/snapshot semantics;
- queue/fill/partial-fill lifecycle;
- latency decomposition;
- cancel/modify/batch/STP;
- trigger/TP-SL/TWAP/Chase/Scale;
- fees/rebates/priority/builder/deployer;
- funding/predicted funding;
- oracle/mark/reference state;
- margin/account abstraction/collateral;
- liquidation/backstop/ADL;
- OI caps/halts/delisting/settlement;
- venue health/congestion/action feasibility;
- portfolio netting and attribution;
- UI-derived analytics precedence;
- historical rule provenance;
- safety/read-only/GitHub-hosted constraints.

A missing matrix row propagates a scoped UNMEASURABLE/UNCERTAIN state to consumers rather than being filled with a default.

### Canonical provenance source basis

This canonical provenance layer consolidates the first-party Hyperliquid rule families already rechecked through the historical research tranches and the Exa/Parallel cross-checks performed on 2026-09-26.

This provenance layer adds no new numeric constants; it makes the already verified semantics uniquely identifiable, versionable and testable.

## Latest research integrated into the canonical spec — 2026-09-26

This section integrates the final current-source findings **without creating another spec version**. It is normative and belongs to this canonical design.

### Account-abstraction mode is proof state

Account mode is part of point-in-time account state, not a UI preference.

The current first-party account-abstraction documentation distinguishes:

- `Manual / Standard`: separate spot/perp and per-DEX balances;
- `Unified account`: one balance per asset shared across supported spot/perp uses;
- `Portfolio margin`: one eligible cross-asset portfolio;
- discontinued legacy DEX abstraction, which may still matter to historical state.

Requirements:

- every account-sensitive replay stores the mode known at that timestamp;
- under Unified/Portfolio Margin, balances and holds used for proof come from the spot clearinghouse/account representation documented for those modes; individual perp-DEX user states are not treated as standalone balance truth;
- Standard mode remains per-DEX/per-balance scoped;
- switching modes is never inferred from a later snapshot;
- mode-unknown intervals are `ACCOUNT_MODE_UNMEASURABLE` for margin/capital-efficiency claims;
- the currently documented 50k user-actions/day restriction for Unified and Portfolio Margin is a feasibility input only and is versioned;
- builder-fee accrual eligibility that depends on Standard mode is modeled only when builder economics are relevant.

### Borrow/lend state must not masquerade as trading alpha

Manual borrow and Portfolio Margin auto-borrow can change account equity, available balance, interest and liquidation risk independently of trade edge.

Requirements:

- manual borrow, automatic borrow, supply interest, borrow interest, repayment and borrow-liquidation cash flows are separate ledger classes;
- Copy-Vault/account analytics must not attribute borrow/supply flows or interest accrual to trading PnL;
- Manual/Unified borrowing and Portfolio Margin automatic borrowing are distinct state machines;
- borrow caps, supply caps, utilization and interest state are point-in-time inputs when they affect capacity or liquidation;
- Portfolio Margin liquidation ordering between perp and collateral legs is not assumed deterministic when official rules make it dependent on oracle-update ordering;
- a displayed/estimated borrow or liquidation price is not substituted for the protocol accounting state.

Current first-party pages conflict on some Portfolio Margin constants (for example the account-value ceiling and HYPE LTV shown in different current documentation surfaces). Therefore:

- those disputed values are stored as separate source assertions;
- they are `RULE_SOURCE_CONFLICT` until a controlling current runtime/API rule or an authoritative documentation update resolves them;
- no replay may select the more profitable value.

### Current multi-DEX/user WebSocket state

The current first-party subscription surface includes additional state streams that must be recognized by collection/schema-drift logic, including:

- `webData3`;
- `twapStates` scoped by user and DEX;
- `clearinghouseState` scoped by user and DEX;
- `activeAssetData` for perps;
- `spotState` with Portfolio Margin context;
- `allDexsClearinghouseState`;
- `allDexsAssetCtxs`;
- `outcomeMetaUpdates`;
- `fastAssetCtxs`.

Requirements:

- DEX scope is explicit wherever the feed exposes it;
- all-DEX state cannot be reconstructed by silently reading only the first/default perp DEX;
- `activeAssetData` may inform point-in-time max-trade/available-to-trade feasibility but never creates alpha by itself;
- `twapStates` is lifecycle evidence for native TWAP state and does not replace slice-fill evidence;
- `outcomeMetaUpdates` is metadata/state evidence for outcome markets, not a price/fill feed;
- undocumented fields in `webData3` are not proof-critical dependencies because first-party docs explicitly warn they may be removed;
- `fastAssetCtxs` is decoded as base64 + raw-DEFLATE + UTF-8 JSON according to the documented wire contract;
- the first `fastAssetCtxs` message is a snapshot and later messages are sparse updates; omitted coins/fields are not zeroed or deleted unless the protocol says so;
- sparse-update merging is deterministic and tested.

### Trade identity and deduplication exactness

Current WebSocket documentation states that `tid` is a 50-bit hash of buyer/seller order IDs and identifies the globally unique trade using the tuple:

`(block_time, coin, tid)`

Therefore:

- `tid` alone is not treated as globally unique across all time/assets;
- canonical trade identity preserves block/event time, instrument identity and `tid`;
- order IDs remain order-lifecycle identifiers and are not substituted for trade identity;
- reconnect snapshots and REST reconciliation deduplicate against the canonical composite identity.

### BBO/book/event sparsity semantics

Current WebSocket semantics distinguish snapshots, event-triggered updates and sparse deltas.

Requirements:

- BBO messages that arrive only when BBO changes are not interpreted as proof that the quote was freshly re-observed on every block with no message;
- quote age advances while no new BBO event is received;
- snapshot feeds remain snapshots, not incremental books, unless the specific feed contract says otherwise;
- sparse asset-context updates carry forward only previously certified fields and never fill omitted values with zero;
- source freshness is calculated from the relevant feed's actual update semantics.

### Trailing-stop observation semantics

Current first-party support documentation describes trailing stops in terms of mark-price activation, a running watermark and a fixed-distance or percentage retracement that ultimately submits a market order.

For observation/replay:

- activation, watermark, retracement and trigger time are distinct states;
- the reference is mark price when the documented feature uses mark price;
- a later fill must not be backdated to the first time BBO/last trade touched the eventual trigger;
- if the public protocol/API evidence does not expose the complete hidden trailing-stop lifecycle historically, reconstruct only what is observable and label the hidden pre-trigger state `TRAILING_STOP_STATE_UNOBSERVABLE`;
- do not invent a server-native order lifecycle from frontend/support wording alone;
- Copy-Vault leader-exit analysis may use a trailing-stop classification only when causal evidence supports it.

### Action-budget and in-flight-cancel feasibility

Current first-party exchange documentation exposes signed mechanisms such as reserving additional address action weight and a nonce-invalidating no-op that can affect in-flight action handling.

Alina remains paper/read-only and **must not implement or invoke these signed actions**.

For hypothetical execution feasibility only:

- extra action weight has an explicit monetary cost and cannot be treated as free throughput;
- current documented reserve-request cost is versioned rather than timeless;
- nonce invalidation/no-op semantics may affect modeled cancellation races only when the applicable rule version is known;
- feasibility modeling of these mechanisms must never introduce signing, private keys, API-wallet operation or `/exchange` calls.

### Venue/account status as evidence

Where available, lightweight status/state endpoints such as `exchangeStatus`, spot clearinghouse state and active-asset data are collected as control-plane evidence.

They are used to distinguish:

- venue unavailable;
- account unavailable;
- instrument unavailable;
- capacity/margin constrained;
- collector failure.

They are not alpha signals by default.

### Latest-source basis

Cross-checked on 2026-09-26 with first-party Hyperliquid documentation for:

- Account abstraction modes;
- Portfolio margin;
- Manual borrows;
- Trailing stops;
- WebSocket subscriptions;
- Perpetual info/account endpoints;
- Exchange endpoint;
- Rate limits and user limits.

Exa and Parallel Search were used for retrieval/cross-checking; first-party Hyperliquid documentation remains authoritative.

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


## Agent Skills and quota-minimal execution

Alina uses **one LLM controller by default**. Agent Skills are reusable procedures for that controller; they are not additional agents, do not create a swarm, and do not authorize hidden delegation. No LLM subagent, nested agent, second coding agent, debate team, or multi-agent fan-out is started unless the user explicitly changes this policy in a future request.

Repository-scoped skills live under `.agents/skills/<skill-name>/SKILL.md`. They follow progressive disclosure: keep the skill description short and specific, load the full workflow only when the task matches, and load supporting references/scripts only when required. Skills must point back to this canonical spec for project truth rather than cloning large chunks of it.

### Initial Alina skill library

The intended initial library is deliberately small and specialized:

- `alina-quant-research`: quantitative discovery, falsification, OOS/forward research, and challenger logic;
- `alina-completion-discipline`: finish multi-step work without premature stopping, looping, or false completion;
- `alina-github-safety`: safe GitHub writes, real-diff verification, commit/tree validation, and main-branch discipline;
- `alina-quota-minimal`: one-controller, minimal-model-turn, deterministic-compute-first execution policy;
- `alina-data-quality`: replay-grade data integrity, timing, gaps, provenance, and quarantine;
- `alina-copy-vault`: Copy-Vault-specific evidence and lifecycle checks;
- `alina-lead-lag`: Lead-Lag timing, causality, clock-domain, and anti-lookahead checks;
- `alina-cross-venue`: executable Cross-Venue spread, depth, cost, freshness, and capacity checks;
- `alina-replay-validation`: deterministic replay construction and certification;
- `alina-economic-proof`: final net-PnL, cost, OOS/forward, capacity, and fail-closed proof;
- `alina-spec-maintenance`: update this canonical spec in place without spawning duplicate version files or research tranches.

Do not install or create a large skill collection merely because it exists. A new skill requires a distinct recurring job, non-overlapping trigger conditions, and a measurable reduction in repeated instructions or execution errors. Merge or remove overlapping skills instead of letting descriptions compete.

### Quota-minimal operating policy

Model turns are scarce; deterministic compute is not model quota. Prefer:

`1 model decision -> largest safe deterministic batch -> compact machine-readable summary -> next model decision`.

Rules:

- never spawn another LLM agent merely to save time;
- avoid repeated whole-repository scans, giant logs, or re-reading unchanged context;
- inspect deltas, manifests, compact summaries, and exact files relevant to the active task;
- when the user has explicitly started a local Codex/agent session, run the broadest practical deterministic tests, replays, backtests, linting, static analysis, profiling, and numerical checks locally;
- local execution must remain user-initiated; ChatGPT/GitHub automation may never wake or remotely consume the user's PC and may never introduce a self-hosted runner;
- GitHub Actions should be reserved for collection/orchestration that genuinely belongs in the cloud, essential integration/compatibility checks, release gates, or checks that cannot be established from the active local checkout;
- do not burn GitHub-hosted minutes or model turns on duplicated validation that has already been deterministically established for the exact same tree unless an independent gate is materially useful;
- prefer scripts and fixtures for deterministic behavior; use model reasoning for decomposition, diagnosis, synthesis, and genuinely ambiguous decisions.

### Completion discipline

Long tasks must use an explicit bounded completion loop.

Before implementation, derive a compact done-contract and unfinished-work ledger from the user's request and the canonical spec. Then repeatedly select the highest-priority unfinished item, execute it, verify it, record the result, and continue without asking for confirmation merely because an intermediate milestone completed.

The controller must not:

- stop after planning when implementation was requested;
- stop after one successful subtask while independent requested work remains;
- repeat the same failing command/action indefinitely;
- create empty commits as progress markers;
- announce completion before the requested artifacts and verification exist;
- promise background work or future completion that is not actually scheduled.

Failure handling is bounded. After two materially identical failures, change method or reduce scope to isolate the fault. After a third materially equivalent failure, record the exact blocker, preserve all valid work, continue any independent remaining work, and report the blocker rather than looping.

For GitHub-changing work, a completion claim requires checking the final branch HEAD and, when a content change was expected, verifying that the final commit has a real diff and a tree different from its parent. If no content change is legitimately required, say so instead of manufacturing an empty commit.

This discipline improves persistence but cannot override platform termination, unavailable credentials, hard tool limits, safety constraints, or external service outages. In those cases the durable checkpoint and exact remaining work are the continuation contract.

### ChatGPT and Codex conversational continuation

These completion rules also apply to interactive Alina work performed inside ChatGPT, Codex, or another coding-agent conversation.

When the user gives a long-running instruction such as `continue`, `finish everything`, `implement the remaining work`, or an equivalent directive, the controller must continue through all currently feasible requested work in the same active turn/session rather than treating planning, one tool call, one file edit, one test, one commit, or one successful subtask as a natural stopping point.

Conversation-level rules:

- maintain a compact internal ledger of completed, in-progress, blocked, and remaining requested work;
- after each intermediate success, immediately select and execute the next feasible unfinished item;
- do not ask for confirmation merely to continue work already authorized by the user;
- do not stop because a partial result is present if additional requested work is still feasible with available tools and context;
- if the same action fails twice materially unchanged, alter the method instead of retrying blindly;
- if a materially equivalent failure occurs a third time, checkpoint the exact blocker and continue any independent work that remains;
- do not claim that work will continue in the background unless an actual scheduled automation has been created;
- if a real platform interruption, context/tool limit, credential problem, safety constraint, or external outage prevents completion, leave a concise durable checkpoint containing the last verified repository HEAD/state, completed work, exact remaining work, and the next safe action;
- conversational persistence must not increase model quota by spawning additional agents: the single-controller and quota-minimal policies still apply.


## Canonical PnL truth — Anti-False-PnL gate

A positive number is **not** proof of profit merely because a strategy report, dashboard, replay, helper, or model labels it `pnl`. Alina may certify PnL only when the complete economic result is reconstructible from causal, immutable, deduplicated accounting evidence.

The anti-false-PnL invariant is:

> if any material component needed to explain the change in paper equity is missing, ambiguous, stale, duplicated, inferred from a favorable fallback, or classified incorrectly, the result is `UNMEASURABLE_PNL` / `INVALID_PNL`, never zero-cost and never certified profit.

### Current repository audit findings

The 2026-09-26 audit of the current repository confirms that the modern final economic-certification path contains strong reconciliation, trade-identity, cost-completeness, OOS/forward and fail-closed controls. However, alternate/legacy helpers still exist whose semantics are too permissive to become proof authorities until they are corrected or explicitly isolated as diagnostic-only.

Confirmed examples:

- `src/hl_observer/control_plane/module_pnl_proof.py` currently reads missing `gross_pnl`, `fees`, `slippage`, or `funding_financing` with zero defaults. Missing economic evidence must never become zero in a certifying path.
- `src/hl_observer/backtest/pnl_from_logs.py` can use a non-zero `estimated_net_pnl_usdc` value as a fallback hint that a trade is closed. A non-zero estimate is not lifecycle proof.
- `src/hl_observer/paper_trading/funding_settlement.py` can derive a “settled” portion from a prorated accrued estimate. This can remain diagnostic/migration evidence, but certified funding must come from actual settlement events or an exact point-in-time settlement reconstruction.
- `PaperLedger.mark_to_market()` can retain the last known mark when a fresh mark is missing. That is acceptable for continuity diagnostics, but stale carried-forward marks cannot certify current unrealized or liquidation-equivalent PnL.
- `PaperLedger.apply_funding()` accepts an amount without an explicit settlement identity/idempotency key at that API boundary. Certified accounting requires exactly-once funding identity so replay/reconnect cannot credit or debit the same settlement twice.
- `PaperLedger.open_position()` accepts both requested notional and optional quantity without itself proving `filled_notional == abs(quantity * fill_price)` within tolerance. Certified fees and position economics must be based on actual filled quantity/notional, not inconsistent requested values.
- historical project audits already recorded snapshot/ledger divergence, diagnostics incorrectly resembling accepted trades, missing entry costs, missing funding, and the risk of double-counting spread/slippage. Those failure classes are permanent regression targets.

These findings do not mean every listed helper currently feeds final certification. They mean **no alternate helper may become, directly or indirectly, a proof source unless it satisfies the canonical accounting contract below**.

### One accounting authority

For each certifiable paper campaign there is one canonical append-only accounting ledger and one canonical economic equation. Dashboards, scoreboards, reports, strategy modules, and research helpers consume that authority; they do not maintain independent PnL counters.

Every economic event has a typed cause and a stable identity. At minimum, the ledger distinguishes:

- fills that OPEN / ADD / REDUCE / CLOSE exposure;
- trading fee / maker rebate / builder or deployer fee attribution;
- funding settlement;
- borrow interest / financing / repayment where applicable;
- liquidation or forced-close economics;
- deposits, withdrawals, transfers, vault flows, rewards and other external/non-trading cash flows;
- mark/unrealized updates, which are state observations rather than realized trading profit;
- corrections/adjustments, which require explicit provenance and cannot masquerade as fills.

A diagnostic metric may aggregate these classes, but certified strategy PnL may not silently reclassify one class as another.

### Canonical equations

For a paper account with no external cash flow during the proof interval:

`equity = starting_capital + realized_price_pnl - trading_costs + rebates + settled_funding - financing_costs + unrealized_pnl`

where every term is derived from the same canonical ledger and sign convention.

For any interval that includes external cash flows, strategy PnL must be normalized for them explicitly:

`strategy_pnl = ending_equity - starting_equity - net_external_contributions`

with deposits, withdrawals, transfers, vault flows, rewards, account-class transfers and similar non-strategy flows separately reconciled. External contributions can change equity but cannot create strategy profit.

Final economic proof must not rely on open unrealized profit. At the proof cutoff, every strategy position is either fully closed with executable exit economics or valued under an explicitly certified liquidation-equivalent close model including depth, fees, slippage, latency, funding/financing and all leg costs. The ordinary canonical target remains fully closed positions.

### Realized PnL requires lifecycle proof

A row is not a realized trade merely because:

- a PnL field is non-zero;
- its label contains `EXIT`, `CLOSE`, `REDUCE`, or `PAPER_ORDER_ACCEPTED`;
- a dashboard/report says “trade”;
- a position snapshot disappeared;
- an estimate changed sign.

Realized PnL requires a valid position identity and a causally consistent OPEN/ADD/REDUCE/CLOSE chain. Reductions cannot exceed open quantity, duplicate fills cannot increase realized PnL, and over-close cannot be silently clipped into a plausible result for certification.

Every fill used in proof must preserve actual filled quantity, actual fill price, actual filled notional and execution identity. For linear contracts, filled notional and `abs(quantity * fill_price)` must reconcile within the contract's documented unit/rounding tolerance. Fee computation uses the economically applicable filled amount, not requested notional.

### Exactly-once economic events

Trade fills, funding settlements, fee/rebate events, liquidation events and non-funding ledger updates require stable deduplication identities across:

- REST snapshots;
- WebSocket snapshots;
- streaming updates;
- reconnect overlap;
- historical backfill;
- archive repair;
- replay restarts.

Snapshot replay is not new economic activity. The same source event may be observed many times but affects canonical PnL exactly once.

For Hyperliquid, preserve source-native identities/provenance such as trade identity, event/block time, instrument identity and ledger-update hash where available. A funding settlement must have enough identity/provenance to prove that the same hourly payment cannot be applied twice.

### Funding truth

Hyperliquid official semantics are hourly settlements. Certified funding uses either:

1. the actual `userFunding` / `userFundings` settlement record; or
2. an exact historical reconstruction at each settlement boundary using the point-in-time position size, oracle price and applicable funding rate/rule.

The documented standard-perp payment uses position size × **oracle price** × funding rate. Mark price is not substituted for oracle price.

A continuously prorated funding accrual, forecast, predicted next funding, or proportionally split historical estimate is **not settled funding** and cannot enter certified realized/net PnL. It may be shown separately as an estimate.

### Non-funding ledger truth

Hyperliquid `userNonFundingLedgerUpdates` / `WsUserNonFundingLedgerUpdates` include non-trading balance changes such as deposits, withdrawals, transfers and liquidations. Those events are accounting evidence, not alpha.

Account-value changes must be reconcilable against these flows. A deposit, transfer, rewards claim, vault distribution/withdrawal or account-class movement cannot be credited as strategy PnL. A withdrawal fee, liquidation closing cost, borrow interest or other real economic debit cannot disappear because it is outside the fill stream.

Account-abstraction mode remains part of the reconciliation contract: Standard, Unified and Portfolio Margin use the correct point-in-time balance authority already specified elsewhere in this document.

### Mark and unrealized truth

Mark/unrealized PnL is distinct from realized PnL.

- every mark used for a proof-critical equity point stores source timestamp, receive timestamp, price type and freshness;
- carrying forward a previous mark is allowed only as explicitly stale diagnostic state;
- a stale/unknown mark cannot become a fresh proof point;
- mark price, oracle price, midpoint, last trade and executable liquidation/exit price are distinct semantics;
- a dashboard/frontend PnL graph is reconciliation context only, never the primary accounting ledger;
- Hyperliquid's own portfolio-graph documentation warns that sampled/interpolated graph data is not appropriate for precise accounting.

### Cost truth and double-count firewall

Every cost/rebate component has exactly one accounting location.

If spread/slippage/latency is embedded into the simulated fill price, it is not subtracted a second time as a separate cash cost. If it is represented as a separate explicit cost, the fill price must not already include the same component. The same rule applies to fees, builder/deployer fees, rebates, priority costs and funding.

Missing cost evidence is `UNKNOWN`, not `0`. Zero is valid only when the applicable venue/rule/account evidence explicitly proves zero.

A constant-price round trip with non-zero costs must lose exactly those costs within tolerance. It may never show profit. A zero-cost constant-price round trip must produce zero PnL.

### Cross-venue and multi-leg truth

A multi-leg strategy cannot certify the favorable leg while ignoring a rejected, partial, stale or delayed hedge leg.

Certified multi-leg PnL requires:

- each leg's actual simulated fill quantity and price;
- fill-ratio/partial-fill state;
- fees and slippage per leg;
- funding/financing/collateral cost where applicable;
- residual inventory after unequal fills;
- entry and exit economics for every leg;
- explicit handling of one-filled/one-rejected and cancel/fill races.

Internal netting may reduce external costs only when the portfolio-netting rules permit it, and the saving is portfolio execution value rather than invented strategy alpha.

### Independent reconciliation views

Before PnL can support promotion/certification, the same interval must reconcile across independent views within a strict documented tolerance:

1. canonical event-ledger sum;
2. position-lifecycle reconstruction;
3. cash/equity equation;
4. campaign/raw-trade aggregate;
5. published scoreboard/report.

A mismatch is not averaged or “best effort”. It yields `PNL_RECONCILIATION_MISMATCH` and blocks certification until explained by typed events.

The tolerance exists only for deterministic numerical representation/rounding; it cannot absorb a missing fee, missing funding event, duplicated fill, stale mark, cash flow, or lifecycle mismatch.

### Anti-false-PnL regression suite

The implementation must include deterministic regression/metamorphic tests that prove at least:

- missing fee/slippage/funding/financing evidence cannot default to zero in a certifying path;
- a non-zero estimated PnL without a valid close lifecycle cannot become realized PnL;
- duplicate fill/reconnect/backfill events do not change PnL;
- duplicate funding settlement does not change PnL after the first application;
- deposits/transfers increase account equity but not strategy PnL;
- withdrawals/transfer fees do not masquerade as trading loss or disappear from reconciliation;
- stale marks cannot certify unrealized/equity proof;
- partial close allocates quantity and costs exactly once;
- over-close/overfill fails closed instead of silently clipping certified economics;
- requested notional differing from actual filled quantity × price cannot alter fees/PnL favorably;
- LONG/SHORT sign symmetry holds under mirrored prices;
- constant-price round trip equals exactly negative all-in costs;
- zero-cost constant-price round trip equals zero;
- embedded spread/slippage plus separate spread/slippage is detected as double counting;
- actual Hyperliquid hourly funding records and exact settlement reconstruction agree on controlled fixtures;
- prorated/forecast funding cannot enter settled PnL;
- all positions required by a proof interval are closed or explicitly non-certifiable;
- any disagreement among ledger, lifecycle, equity, raw aggregate and scoreboard blocks certification.
- malformed or truncated proof-critical ledger records quarantine/fail the affected certification scope rather than being silently skipped;
- independent PnL reconstruction must derive from raw/typed events and lifecycle state and must not reuse the published/final aggregate PnL field as an input;
- deleting any proof-critical fee, funding, fill or cash-flow event from a controlled fixture must make the result fail/UNMEASURABLE rather than improve certifiable PnL.

### Simulation PnL display contract

The simulation UI is a consumer of canonical accounting truth, never an independent PnL calculator.

A numeric PnL may be displayed only when the exact displayed scope has a valid accounting status. If the required ledger/lifecycle/cost/funding/fill/mark reconciliation is missing, stale, contradictory, incomplete, or invalid, the UI must display the explicit status (`UNMEASURABLE_PNL`, `INVALID_PNL`, `PNL_RECONCILIATION_MISMATCH`, or the scoped equivalent) instead of a numeric PnL.

Display rules:

- no fallback to `0`, last-known PnL, cached PnL, estimated PnL, gross PnL, midpoint markout, or another strategy/module's PnL when canonical net PnL is unavailable;
- an invalid/unmeasurable numeric value must be removed from cards, charts, totals, ROI, profit factor, daily target progress, leaderboards, badges, colors, alerts and API/UI summaries that could make it look economically valid;
- realized, unrealized, estimated and diagnostic values must be visually and structurally distinct and can never share a label that implies interchangeable PnL truth;
- stale unrealized state must be labeled stale and must not continue moving or appearing as current verified PnL;
- dashboards and APIs must carry the PnL validity/status field together with the value so a frontend cannot discard the qualification;
- aggregation is deny-by-default: if a material child component is invalid/unmeasurable, the parent total cannot silently sum only the known favorable children and display a partial PnL as complete;
- after restart, reconnect, replay resume, dataset repair or ledger rebuild, the UI must not restore a previously cached numeric PnL until canonical reconciliation has completed again;
- a disagreement between two UI/report surfaces is itself a reconciliation failure and numeric PnL display is suppressed for the affected scope until resolved.

The user-facing rule is absolute: **Alina must never show a number as simulation PnL unless that number is currently supported by the canonical accounting evidence for that exact scope. Better no number than a false number.**

### First-party source basis

The current Hyperliquid documentation establishes the source semantics used by this gate:

- `userFills` / `WsUserFills` provide fills, fee fields, execution identity and closed-PnL/frontend context;
- `userFundings` provides hourly funding-payment events;
- `userNonFundingLedgerUpdates` provides deposits, withdrawals, transfers, liquidations and other non-funding ledger changes;
- `clearinghouseState` provides account/position state and unrealized-PnL context;
- under Unified/Portfolio Margin, spot clearinghouse state is the documented balance source of truth;
- the official “Entry price and pnl” page states that entry price, unrealized PnL and closed PnL are frontend convenience components while fundamental accounting is based on margin/balance and trades;
- the official portfolio-graph page explicitly warns that its sampled/interpolated graph is not suitable for precise accounting;
- standard Hyperliquid funding is settled hourly and uses oracle price in the payment notional.

The canonical implementation should prefer these first-party records and immutable raw evidence over derived frontend/account snapshots whenever the two differ.

## Simulation-to-live behavioral parity contract

The simulation target is **behavioral parity with the future real execution path**, not merely similar aggregate PnL.

Because some live matching-engine state can be unobservable from public L2/API evidence, "exact" means:

1. reproduce exactly every venue behavior for which point-in-time evidence and rules are observable;
2. preserve explicit uncertainty for hidden state;
3. use conservative bounded outcomes where exact state cannot be reconstructed;
4. never convert hidden state into a favorable synthetic fill;
5. block economic certification and any future live-readiness claim when a material execution behavior is unsupported or unvalidated.

Current Alina remains strictly paper/read-only. This section defines the simulation and future-readiness contract; it does not authorize signing, API wallets, private keys, testnet trading, mainnet trading, or real orders.

### 2026-09-26 current-code audit findings

The repository contains many strong realism components, but the audit found several gaps between those components and a venue-faithful canonical simulation:

- `src/hl_observer/audit/simulation_realism_audit.py` currently checks ledger fields, numeric types and PnL reconciliation, but does not prove order-lifecycle, latency, queue, rejection, margin, funding, liquidation or venue-state parity;
- `tests/test_runtime_replay_paper_parity.py` proves deterministic equality for a legacy `hyper_smart_observer` path and only compares entry price, size and entry fee; it is not a complete parity test for the canonical `src/hl_observer` execution path;
- `ExecModelConfig(latency_mode="CAUSAL")` suppresses the scalar latency surcharge when an `ExecutionTruth` exists, but `execute_paper_intent()` itself consumes one supplied book and does not prove that this book is the first causal executable state at `decision_time + actual_order_arrival_delay`; this wiring must be proven end-to-end;
- the canonical execution model currently creates an "all-in" effective fill price by folding fee and, in some branches, latency/adverse-selection adjustments into price, while `PaperEngine` records zero separate ledger fee for those fills; this can preserve some round-trip arithmetic while still differing from real venue cash, entry-price, margin and liquidation timing;
- adverse selection is currently allowed to modify a simulated maker fill price; in live trading adverse selection is a post-fill market outcome/markout, not a fee that changes the venue execution price;
- `src/hl_observer/paper_trading/order_types.py` exposes only MARKET/LIMIT/POST_ONLY abstractions, while Hyperliquid live semantics distinguish GTC/IOC/ALO, reduce-only, trigger orders, TP/SL, parent-child grouping, Scale, TWAP, Chase and venue-specific cancellation/modify behavior;
- the canonical one-shot execution API does not by itself model the full persistent lifecycle of a resting GTC/ALO order, partial fills across blocks, cancel/modify races, trigger activation, or eventual residual cancellation;
- maker fills may consume externally supplied queue-ahead/depletion evidence, but public aggregate L2 alone cannot prove exact price-time queue position;
- the default `max_execution_book_age_ms=5000` is a compatibility bound, not a universal proof-quality freshness threshold for short-horizon strategies;
- `PaperEngine` still has simple paper margin/exposure caps that are not themselves the full point-in-time Hyperliquid clearinghouse, margin-tier, account-mode and match-time margin state machine;
- legacy/simple funding helpers exist that multiply rate × notional × interval; certified simulation funding must instead use actual settlement events or exact point-in-time hourly settlement reconstruction;
- several older helper/test surfaces remain useful diagnostics but are not sufficient evidence that the canonical simulator would have received the same acceptance, fill, fee, order-state and account-state outcome as a real Hyperliquid action.

These are implementation gaps, not permission to add a live executor. Until closed, the corresponding capability remains simulation-only and non-live-eligible.

### Event-native execution accounting

A real venue does not charge a trading fee by changing the trade's execution price. Therefore the canonical simulator must preserve the same event categories as the venue:

- `raw_fill_price`: volume-weighted actual simulated match price from executable book/order evidence;
- `filled_quantity` and `filled_notional`: only actually matched quantity;
- `spread/slippage`: emerges from the difference between decision/reference price and raw executable match prices;
- `trading_fee` / maker rebate / builder or deployer fee / priority fee: separate signed cash-flow events;
- `funding`, borrow interest and liquidation economics: separate signed ledger events;
- `latency`: changes which future market/order-book state the order reaches; it is not an arbitrary additive price surcharge in the certifying path;
- `adverse_selection`: post-fill markout/outcome measured after execution; it is never folded into the raw fill price.

Effective/all-in prices may exist for diagnostics, but canonical entry price, position cost, margin, equity, liquidation and reconciliation use raw venue-equivalent fill events plus separately typed costs.

### Causal end-to-end latency

Every simulated action carries a causal latency trace:

`source_event -> local receive -> normalization -> signal -> decision -> risk -> order-intent creation -> serialization/signing-equivalent budget -> outbound network -> API/mempool/consensus -> execution eligibility -> execution result receive`.

In the current read-only architecture, unavailable future signed-write components are measured where possible and otherwise explicitly versioned assumptions/stress ranges. They are never silently set to zero for proof.

For a taker/IOC-style paper action, the execution book must be the first admissible causal market state at or after the simulated matching-engine arrival time. A book observed at the decision time cannot be reused as the execution book merely because it is fresh.

For a resting order, order insertion time determines initial queue state. Subsequent fills/cancels/modifies are driven by later causal market/order events.

Hyperliquid's current first-party documentation states that end-to-end write latency includes API transit, mempool inclusion and commit, and that transaction ordering distinguishes cancels/ALO from IOC/GTC. Current empirical latency figures are versioned observations, never timeless constants.

### Venue-native order state machine

Every paper order intended to represent an actionable future live order carries the same material fields as the target Hyperliquid action: instrument identity, side, raw size, raw/rounded limit price, reduce-only, TIF, trigger configuration, grouping/parent-child relationship, optional client identity, and rule-version provenance.

The simulator models at least these states where applicable:

`CREATED -> PREVALIDATED -> SUBMITTED_SIM -> ACCEPTED -> RESTING/PARTIALLY_FILLED/TRIGGER_PENDING -> FILLED/CANCELED/REJECTED/EXPIRED`.

Modify and cancel are state transitions with races, not instantaneous rewrites of history.

TIF semantics are exact:

- ALO that would immediately match is canceled/rejected rather than becoming taker;
- IOC matches only immediately available eligible liquidity and cancels the residual;
- GTC residual quantity rests until later fill/cancel/expiry;
- reduce-only cannot increase or flip exposure;
- trigger orders remain inactive until the applicable mark-price trigger condition is met;
- TP/SL activation and parent-child behavior follow the point-in-time documented rule;
- unsupported order types or undocumented lifecycle state return `UNSUPPORTED_SIMULATION_SEMANTICS` and cannot be economically certified.

Market helpers are modeled as protected aggressive IOC/limit behavior when that is what the client/API actually sends; no infinite-liquidity "market" primitive is invented.

### Exact pre-validation and venue rejection parity

Before a simulated action can reach matching, the simulator applies the point-in-time venue rule set. Deterministic rejections include, where applicable:

- invalid tick/price precision;
- invalid lot/size precision;
- minimum notional;
- insufficient margin;
- reduce-only violation;
- ALO price that would immediately match;
- IOC with no immediately matchable liquidity;
- invalid trigger price/type;
- no market liquidity;
- open-interest cap / too-aggressive-at-cap / position-flip-at-cap;
- oracle/reference-price bounds;
- maximum position/margin-tier limit;
- batch-level pre-validation failure;
- open-order/action/rate-limit constraints;
- stale `expiresAfter` and other applicable request validity rules.

A simulation that would have been rejected live records a rejection with the corresponding rule/version and creates no fill/PnL.

### Taker / aggressive execution

Aggressive fills walk the side-correct executable book at **arrival time**, level by level, after all applicable tick/lot/price-protection rules.

The simulator must:

- consume shared liquidity exactly once across simultaneous paper intents;
- preserve every level fill;
- stop when price protection or available depth ends;
- distinguish full fill, partial fill and no fill;
- cancel residual quantity for IOC;
- preserve residual quantity only for order types that would actually rest;
- never fill beyond observed/reconstructed executable liquidity;
- never use midpoint as an executable price;
- compute fees from actual filled notional under the point-in-time account/asset fee rule.

### Maker / passive execution and queue uncertainty

Hyperliquid matches orders in price-time priority, with additional L1 action-ordering semantics documented for cancels/ALO versus GTC/IOC. Exact maker fill simulation therefore requires evidence sufficient to reconstruct the order's place in the relevant queue and the subsequent executable events.

Aggregate L2 snapshots alone do not identify the exact orders ahead. When exact queue state is unavailable:

- the simulator reports `QUEUE_STATE_UNOBSERVABLE`;
- maker fill results are bounded/conservative scenarios rather than "exact" fills;
- favorable queue assumptions cannot enter certified PnL;
- a fill may be certified only when order-level/raw-diff evidence or another validated causal mechanism establishes that sufficient executable volume reached/passed the simulated order after insertion;
- cancellations ahead may improve queue position only under a validated queue-depletion model; they are not automatically credited favorably;
- priority-fee/ALO queue semantics are versioned and applied only when their required evidence exists.

### Freshness and event ordering

No universal five-second book age is sufficient for all strategies.

Each strategy/action defines a maximum admissible evidence age from measured horizon, alpha half-life and execution latency. Proof-critical events preserve exchange/block time, local receive time, monotonic ordering evidence and source sequence/identity.

Replay has one deterministic total order that preserves the venue's observable sequencing and local receive causality. Ties use explicit deterministic rules rather than input-file accident.

No order may execute against an event that became observable only after its simulated decision/arrival state unless that event is the causal future execution event itself.

### Fees and rebates

Simulation fee truth is point-in-time and account-specific.

The current Hyperliquid fee schedule depends on rolling weighted volume and can also depend on staking/referral state, maker share/rebate tier, aligned quote-asset treatment, HIP-3 growth mode and deployer configuration. Static 4.5/1.5 bps values remain compatibility assumptions only when the exact scenario explicitly targets that tier.

For certification:

- the fee rule/version and account fee state are inputs;
- maker rebates are signed cash flows, not negative slippage;
- builder/deployer/priority fees remain separate components;
- unknown fee tier or applicable multiplier makes exact net PnL unmeasurable unless a preregistered conservative bound is used and labeled as such;
- fee timing follows the fill event so cash/equity/margin evolution matches venue economics.

### Funding and settlement

Certified perp funding follows the point-in-time Hyperliquid rule and account position at each settlement boundary.

For current standard perps, the first-party rule basis is hourly settlement, with payment based on position size × oracle price × applicable funding rate. Forecast, accrued or linearly prorated funding is not settled funding.

Partial position changes around a funding boundary use the actual point-in-time size. Reconnect/backfill duplicate funding events are exactly-once.

### Margin, buying power and liquidation parity

Simulation risk caps are not substitutes for venue margin accounting.

The canonical paper account tracks the selected point-in-time account mode, collateral, cross/isolated state, margin tier, open-order reservations, unrealized PnL, funding/fees, maintenance requirement, withdrawable/available balance and match-time margin checks.

Margin must be re-evaluated when the venue would re-evaluate it, including for the resting side at matching.

Liquidation uses mark-price/account-equity semantics and the applicable rule version. The simulator models book liquidation, partial liquidation rules/cooldowns where applicable, residual position/account state, and backstop/ADL behavior to the extent required by the tested account mode. Missing liquidation-rule evidence blocks liquidation-sensitive PnL certification.

### TP/SL, triggers and advanced order behavior

Trigger conditions use the venue's documented trigger price source, not last trade/BBO by convenience.

Market TP/SL and limit TP/SL preserve their actual price-protection/fill semantics. Trigger activation does not guarantee execution.

Parent-linked TP/SL, OCO-style lifecycle, Scale, TWAP and Chase are modeled only when the strategy actually uses them and enough evidence exists. Otherwise they are explicitly unsupported rather than approximated as simple market fills.

### Rate limits, congestion and action feasibility

A strategy that is profitable only when it can submit an impossible number of actions is not live-feasible.

Simulation maintains point-in-time feasibility for:

- address action budget;
- IP/API request budget;
- open-order limits;
- websocket/user/subscription constraints relevant to the data path;
- batch semantics;
- congestion/maker-share constraints where applicable;
- cancel/modify/trigger restrictions;
- priority-fee requirements for any latency assumption that depends on them.

When the modeled future live action could not legally/operationally be submitted in time, the paper action is delayed/rejected accordingly.

### Reconnect, restart and state recovery

Disconnect/restart is part of execution realism.

On restart/reconnect the simulator rebuilds from durable canonical state, reconciles open positions/orders/fills/funding, deduplicates snapshot acknowledgements/backfills, and cannot assume that a disappeared local order was filled or canceled.

Until order/account state is reconciled, affected actions and numeric PnL remain blocked or explicitly uncertain.

### Cross-venue and multi-leg coordination

Multi-leg strategies preserve independent venue latency, rules, fill states and failure modes for every leg.

No atomicity is assumed unless the real mechanism provides it. The simulation must represent:

- one-filled/one-rejected;
- one-filled/other-delayed;
- unequal partial fills;
- residual inventory;
- hedge chase/cancel logic;
- capital/margin fragmentation;
- venue-specific fees/funding;
- emergency flattening policy and its executable cost.

A paired strategy cannot book the intended spread as PnL before the actual simulated leg states justify it.

### Parity validation and calibration

"Simulation passed tests" is insufficient. The simulator needs an explicit **parity scorecard** against real venue ground truth wherever such ground truth is available.

Deterministic parity fixtures/replays compare at least:

- order acceptance/rejection and exact reason class;
- resting versus immediate-fill outcome;
- order-state transition sequence;
- fill count and partial-fill structure;
- filled quantity and VWAP;
- cancel/modify race outcome;
- fee/rebate/funding cash flows;
- position/equity/margin state after every economic event;
- TP/SL trigger and execution state;
- liquidation transition/state where applicable;
- reconnect/recovery idempotency;
- action feasibility under limits;
- final reconciled PnL.

The same canonical execution/accounting engine is used by replay, forward paper and future live-intent planning; strategy-specific code may not maintain a more favorable private simulator.

Where public/archival Hyperliquid order/fill/book data provides ground truth, replay must match it within exact discrete-state equality and narrowly defined numeric rounding tolerances. Aggregate PnL agreement alone is never sufficient.

### Future real-money readiness gate

Current Alina is not live-enabled. A future user-authorized transition to any signed/testnet/mainnet executor requires a separate explicit change of scope.

Before any future real-money permission can be considered, all of the following must be true:

- every order type the strategy can emit has certified simulation semantics;
- all proof-critical venue rules are current/versioned;
- no approximate/legacy execution path can feed promoted PnL;
- execution/accounting branch coverage satisfies the 100% branch gate;
- parity scorecards pass on representative regimes, volatility, liquidity and failure cases;
- paper/forward behavior remains economically positive under conservative uncertainty bounds;
- restart/reconnect/rate-limit/liquidation/failure drills pass;
- no unresolved `UNMEASURABLE`, `UNSUPPORTED_SIMULATION_SEMANTICS`, queue ambiguity, reconciliation mismatch or material rule conflict remains for the live scope;
- the user separately and explicitly authorizes changing Alina's read-only safety model.

Until then, `LIVE_ELIGIBLE = false`.

### First-party rule basis for this contract

The current first-party Hyperliquid documentation establishes that:

- the order book uses price-time priority;
- ALO/IOC/GTC have distinct matching/resting behavior;
- venue errors include tick, minimum-notional, margin, reduce-only, ALO-cross, IOC-no-fill, trigger, no-liquidity, open-interest/oracle/max-position failures;
- TP/SL are mark-triggered and trigger activation does not guarantee a fill;
- WebSocket clients must tolerate disconnects and reconcile missed data from reconnect snapshots/info queries;
- funding settles hourly and standard-perp payment uses oracle-price notional;
- margin is checked when opening an order and again for resting-side matching;
- liquidation is mark/equity/maintenance-margin driven and may first use book execution before backstop;
- fees are account/volume/tier dependent rather than one universal constant;
- action, open-order, websocket and request-rate limits can constrain a live strategy;
- write latency includes API transit, mempool inclusion and consensus/commit, and current sequencing treats cancel/ALO behavior differently from IOC/GTC.

All numeric constants from these documents remain versioned point-in-time rules rather than permanent assumptions.

## Test coverage — 100% branch coverage

The implementation target is **100% branch coverage**, not merely 100% line/statement coverage.

This requirement applies to first-party executable Alina code whose behavior can affect collection, normalization, state transitions, replay, backtest, execution simulation, economic accounting, scoring, orchestration, dataset integrity, safety, or promotion/certification decisions.

Rules:

- branch measurement must be explicitly enabled in the coverage tool (for Python, equivalent to `coverage.py --branch` / `pytest-cov --cov-branch`);
- the enforced threshold is 100% for the covered first-party scope; a 99.x% result is a failure rather than rounded to 100%;
- line coverage alone can never satisfy this gate;
- every reachable decision outcome must be exercised, including true/false paths, exception/error paths, fail-closed paths, boundary conditions, empty/null/missing-data paths, retry/reconnect paths, and state-transition branches;
- decision-heavy code that affects PnL, admissibility, no-lookahead, costs, fills, timing, liquidation/margin, dataset integrity, or paper/read-only safety has no coverage exemption;
- `# pragma: no cover`, omit lists, broad exclusions, generated wrappers, defensive `except` blocks, or dead-code declarations may not be used to game the metric;
- an exclusion is allowed only for genuinely non-executable/declarative/generated/third-party/platform glue that cannot affect Alina decisions, and every exclusion must be narrow, documented, reviewable, and absent from economic/safety-critical logic;
- unreachable first-party branches should normally be deleted or refactored rather than excluded;
- branch coverage is measured on the exact candidate tree/commit being validated;
- tests must assert behavior, not merely execute lines to satisfy the counter;
- deterministic local execution is preferred when the user explicitly runs Codex locally; cloud CI may re-run the final coverage gate when an independent integration/release gate is useful;
- a release, certification, or claim that implementation of this specification is complete is blocked while required branch coverage is below 100%.

Coverage is a structural verification gate, not proof of economic correctness. The existing replay, OOS/forward, cost, data-integrity, no-lookahead, and fail-closed acceptance gates remain independently mandatory.

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
310. external papers, third-party APIs and public market studies can generate hypotheses but cannot certify an Alina edge or override paper-only safety;
311. V6.1 research scheduling prioritizes Execution Alpha, Scheduled Flow, Forced Flow, Relative Value and Trend, with Options as a shared context layer, while allowing reprioritization only from measured Alina evidence;
312. research priority distinguishes event frequency, edge amplitude, capacity and falsification speed rather than treating priority as a profitability claim;
313. execution experiments compare route policies on the same causal opportunity state whenever counterfactual evidence permits;
314. maker evaluation includes queue state, fill probability, conditional fill time, adverse-selection markout and non-fill opportunity cost;
315. a maker policy cannot be promoted from fill rate or conditional markout alone;
316. execution research records multi-horizon post-fill markouts and implementation shortfall versus immediate executable taker baseline;
317. Scheduled Flow separates native announced TWAPs, latent reconstructed metaorders and ordinary isolated flow;
318. TWAP research conditions effect size on phase, parent-size normalization, participation rate, volatility regime and same-side dominance;
319. TWAP external effect sizes such as temporary impact or post-completion displacement are priors only and never imported as Alina PnL;
320. Scheduled-Flow promotion requires incremental OOS value versus the same base strategy without TWAP state;
321. Forced-Flow distinguishes endogenous buildup from exogenous shock events and does not require one universal precursor;
322. forced-flow evidence records OI clearing, impact amplification, depth/recovery state and propagation where measurable;
323. Forced-Flow can remain a risk/regime layer if event frequency or independent sample count is insufficient for a standalone economic sleeve;
324. Relative Value PnL includes margin/liquidation risk, capital fragmentation and capital-time opportunity cost in addition to fees/spread/slippage/funding;
325. every relative-value leg records margin model, liquidation distance, mark-price convention, collateral and settlement/funding convention;
326. statistical residual/cointegration models must beat simpler executable basis baselines on frozen OOS economics;
327. Trend research begins with interpretable low-complexity baselines before CTREND-style or ML ensembles;
328. Trend evaluation includes contemporaneous universe construction, survivorship controls, turnover penalty, capacity and capital-time efficiency;
329. options-derived signals use explicit delta/tenor definitions and carry rolling decay/drift and liquidity-quality metadata;
330. options coefficients or effect sizes from historical research cannot be copied into the live/replay decision function;
331. Options/Volatility Intelligence is retained only for incremental OOS value in another module unless a separately specified options-trading architecture is approved;
332. cross-module ablations attribute incremental value among raw edge, scheduled flow, forced flow, options context, trend/regime and execution policy;
333. a layer that duplicates another feature family without incremental OOS economics is demoted or removed from the HOT path;
334. V6.1 maintains a daily-target research scoreboard with independent events/day, gross edge, cost, fill rate, net USD/day lower confidence bound, capacity, capital-time and evidence state for each lane;
335. missing V6.1 scoreboard inputs remain UNMEASURABLE and are never imputed solely to show progress toward the 4 USD/day milestone;
336. public X/GitHub bot research is a hypothesis-discovery source only and cannot certify profitability;
337. every externally discovered bot idea records source, revision/provenance, license, mechanism, required data, falsification test and Alina disposition;
338. external code is not copied into Alina without license/provenance review, and independent mechanism reimplementation is preferred where practical;
339. XEMM is treated as distinct from both naive market making and taker-taker Cross-Venue because it passively creates a maker opportunity and hedges only after a maker fill;
340. XEMM paper replay prices the hedge only after the simulated maker fill timestamp plus modeled latency and never credits pre-fill future hedge prices;
341. XEMM accounting includes maker fill probability, queue assumptions, hedge fee/slippage, hedge failure, residual inventory and collateral fragmentation;
342. XEMM must beat both taker-taker Cross-Venue and naive passive maker baselines on frozen OOS/forward economics before standalone promotion;
343. Execution Alpha may use volume-clock/VPIN-lite state, but volume imbalance is not promoted as standalone alpha without independent proof;
344. Execution Alpha maintains side-specific toxicity and does not assume bid-side and ask-side adverse selection are symmetric;
345. fill-burst and shock-chain state may widen/reduce/suppress passive exposure or promote an event to Forced-Flow analysis, with every action replayable causally;
346. wall/depth features require persistence/refill/cancel and realized execution evidence and are never treated as support/resistance by inspection alone;
347. passive/XEMM sleeves report inventory half-life and capital-time consumed by residual inventory;
348. optional API/data budget is allocated by marginal value while preserving Tier-A raw evidence, safety and reconciliation before research breadth;
349. HIP-3/RWA instruments carry a versioned session contract distinguishing external-reference-active, closure transition, internal price discovery, reopen approach and reopen states;
350. HIP-3 research never treats a closed external reference market as executable;
351. HIP-3 session calendars, holidays, oracle/deployer specifications and price/bounding constraints are versioned inputs rather than permanent hard-coded assumptions;
352. HIP-3 off-hours/reopen hypotheses are evaluated against simpler Friday-close/session/placebo baselines and actual executable books;
353. cross-deployer same-underlying analysis uses an explicit compatibility graph and does not infer economic equivalence from ticker text alone;
354. builder/front-end/order metadata may create probabilistic participant-flow labels only with confidence/evidence and an explicit UNCLASSIFIED state;
355. flow-provenance research does not deanonymize wallets or infer real-world personal identity;
356. builder route, direct API, IOC or FrontendMarket metadata are features, not definitive trader-quality labels;
357. participant-flow classifiers are frozen before OOS evaluation and must demonstrate incremental calibration or economic value over simpler features;
358. Hyperp/pre-launch instruments are treated as a distinct instrument class with their reference mechanism, bounds, settlement/listing uncertainty and external contract semantics preserved;
359. Hyperp/pre-launch relative value requires payoff/contract equivalence and cannot infer convergence from same ticker alone;
360. rumor-derived listing dates are never treated as known event timestamps in causal replay;
361. naive grid, martingale/DCA, generic technical indicators, generic AI trading, social sentiment, fee-only market making and unproven Kelly sizing do not become modules merely because public bots implement them;
362. public strategy-sweep findings are used only as turnover/friction priors; no public APR/PnL figure is imported into Alina evidence;
363. every candidate reports edge-to-friction sensitivity, including break-even cost and stressed cost scenarios;
364. V6.2 research ordering adds XEMM and HIP-3/session research while preserving the rule that priority is not a profitability ranking;
365. V6.2 scoreboard reports XEMM maker fills/hedges/adverse markout, HIP-3 session/reopen metrics, flow-provenance coverage and Hyperp relative-value evidence;
366. all V6.2 additions remain paper/read-only and cannot introduce private keys, signed trading actions or real-order execution into the Alina research path;
367. V6.3 preserves separate exchange, received/local, decision, send/arrival, fill/cancel-effective and deterministic simulation timestamps where the source permits;
368. causal decisions cannot observe events whose first-observable timestamp is after the decision timestamp;
369. equal-timestamp events use a documented deterministic tie-break/sequence rule;
370. order lifecycle explicitly models pending-new, open, partial-fill, pending-cancel/replace and terminal states;
371. every partial fill immediately updates position, fees, inventory and hedge requirement and cannot be overwritten by a later fill chunk;
372. fills occurring during cancel/replace latency remain valid when consistent with venue semantics;
373. IOC unfilled remainder, post-only crossing/rejection and batch rejection semantics are modeled rather than optimistically filled;
374. L2-only replay represents queue position as uncertain and cannot claim exact FIFO position;
375. maker/XEMM proof reports results across risk-averse, probabilistic and priority-aware queue models, with L3 FIFO used only when order-level evidence exists;
376. strategies whose PnL sign is unstable under plausible queue models are labeled QUEUE_UNCERTAIN rather than promoted;
377. feed, processing, decision, order-arrival, venue-processing and hedge latency are measured/modelled separately;
378. latency sensitivity includes baseline, stressed and tail-latency scenarios;
379. Hyperliquid priority-fee semantics are historically versioned and priority fees are charged in net PnL when used in paper scenarios;
380. priority-fee optimization compares alpha preserved and fill improvement against the explicit fee and adverse-selection cost;
381. current documented IOC ms-per-bp and ALO priority-window behavior are versioned priors, not timeless constants;
382. read/gossip priority and order/write priority are represented separately;
383. Dynamic Venue Economics versions maker/taker fees, rebates, fee tiers, discounts, builder/deployer fees, growth mode, funding and priority fees;
384. proof cannot credit an unavailable hypothetical fee tier/rebate/discount to establish the +4 USD/day milestone;
385. historical cost-rule unknowns remain UNMEASURABLE rather than silently using current rules;
386. each venue/instrument has point-in-time HEALTHY/DEGRADED/STALE/HALTED/RECOVERING/UNKNOWN health state;
387. stale/halted/unknown references cannot generate ordinary Cross-Venue arbitrage admission;
388. venue recovery requires reconciliation/catch-up before normal admission resumes;
389. HIP-3 state includes oracle age, mark/oracle/external divergence, update cadence, OI cap, margin/leverage revision and halt/resume state where observable;
390. HIP-3 stale-oracle, OI-cap, halt/resume and oracle-update hypotheses are separate preregistered lanes rather than assumed arbitrage;
391. collateral and quote currencies are valued explicitly and stable assets are not hard-coded to exactly 1 USD under stress;
392. delta-neutral labels include collateral/quote residual risk and cross-venue collateral mismatch;
393. Forced-Flow classifies market liquidation, backstop absorption, ADL and unknown as distinct routes when public evidence supports classification;
394. liquidation-route transition timing and route-specific markout/OI/depth/recovery are reported separately;
395. a BOOK_ABSORBS -> BACKSTOP_NEEDED -> ADL_NEEDED ladder is observational state only and not a universal causal predictor;
396. liquidity-fragility research uses executable slippage surfaces across notionals and cannot invent provider concentration from anonymous aggregate L2;
397. capacity/XEMM/Forced-Flow sizing incorporates stressed depth and tail-slippage state;
398. every OOS-valid strategy passes a lookahead perturbation test designed to reveal future-data dependence;
399. recursive/startup-history sensitivity is measured for stateful indicators/features and material instability blocks promotion until resolved;
400. bar-derived features store finalization/first-knowable time and use closed bars unless an intrabar design is explicitly specified and tested;
401. causal features pass dataset-slice/replay invariance within documented numerical tolerance;
402. stochastic queue/latency simulation records model version, parameters, seed and distributional outcomes rather than reporting only a favorable seed;
403. XEMM evaluates immediate, bounded-delayed, split and defensible synthetic hedge policies plus NO_NEW_QUOTE;
404. delayed hedge is accounted as temporary directional exposure and cannot use favorable future hedge prices with lookahead;
405. split/synthetic hedge policies include basis, collateral, margin, venue-health and hedge-error costs;
406. funding research separates expected from finally realized funding and versions settlement timing/convention per venue;
407. funding/premium forecasts must add OOS value beyond simpler executable basis baselines;
408. listing/delisting/contract-change events are stored with publication and first-observed timestamps and cannot create impossible pre-announcement fills;
409. GitHub-hosted Alina does not assume it can win sub-second listing/announcement latency races and uses those events primarily for causal conditioning/research;
410. Public Bot Intelligence records batch-level reviewed/unique/high-signal/new-mechanism/duplicate/rejected counts and uses declining novel-mechanism yield as a temporary saturation signal;
411. none of the V6.3 execution models authorize private keys, real probe orders, signed actions or live execution; calibration must remain compatible with the paper/read-only safety boundary;
412. V6.4 preserves separate standalone-module and combined-portfolio execution ledgers so portfolio netting cannot hide weak standalone economics;
413. compatible cross-module intents may be netted before simulated external execution only when instrument semantics, urgency, execution constraints and hedge obligations are compatible;
414. hedge obligations and risk-reduction intents cannot be canceled by unrelated speculative intents merely to save fees;
415. portfolio netting reports gross intended turnover, external turnover, avoided costs, missed-alpha cost and residual inventory;
416. portfolio netting savings are portfolio execution value and cannot be attributed to one module's signal alpha;
417. internal paper crossing never invents maker rebates, external fills or self-impact benefits beyond explicitly modeled avoided turnover;
418. tracked-wallet trigger maps store source-wallet coverage and are labeled as sampled coverage unless market-complete evidence is certified;
419. public trigger-order fields are used only from point-in-time read-only evidence with provenance and freshness;
420. trigger clusters distinguish stop-loss, take-profit, reduce-only and unknown semantics where observable and never treat all triggers as forced liquidation;
421. trigger-map hypotheses require incremental frozen-OOS value over equivalent models without trigger state;
422. L2 replenishment/absorption features are probabilistic evidence and never claim exact hidden iceberg quantity;
423. spoofing, iceberg and hidden-liquidity labels remain probabilistic unless direct order-level evidence proves the underlying lifecycle;
424. absorption intelligence records aggressive flow, depletion, refill, refill latency, persistence, cancellation and price response where feed resolution permits;
425. microstructure metrics such as realized/effective spread, impact coefficients or VPIN-like state require explicit construction and must beat simpler features before HOT-path retention;
426. adaptive execution slicing activates only when notional/depth or notional/volume makes self-impact or timing risk economically material;
427. POV/VWAP/TWAP/implementation-shortfall challengers report arrival-price shortfall, participation, completion, alpha decay and residual quantity;
428. complex adaptive execution must beat simple one-shot/TWAP/VWAP baselines on frozen OOS economics;
429. funding records distinguish published-current, exchange-predicted/next and Alina-forecast values;
430. Alina funding forecasts cannot use finally realized funding before settlement and must beat persistence/exchange-predicted/simple-consensus baselines economically OOS;
431. venue parameter changes including fees, rebates, priority rules, margin tiers, OI caps, growth/deployer settings, oracle specs and tick/lot rules are versioned events;
432. historical replay uses the venue-rule state valid at the decision timestamp rather than current settings;
433. V6.4 research ordering adds cross-module intent netting and latent-flow context without treating priority as a profitability ranking;
434. the public-bot corpus convergence rule prevents a new first-class module unless it adds a new economic mechanism, new public data family, material execution-economics change, proof-quality improvement or independent opportunity class;
435. public ideas that fail the V6.4 novelty bar are classified as feature, baseline, execution policy, risk control, duplicate, watchlist or noise rather than expanding architecture;
436. all V6.4 additions remain paper/read-only and cannot introduce signed trading actions, private keys or live probing;
437. every venue/instrument declares a versioned microstructure class before its book can support economic proof;
438. displayed L2 is not assumed to equal total executable liquidity on hidden-order venues;
439. RFQ indicative and executable real books are distinct evidence families;
440. venue capability contracts record public data, sequencing, archive, fees, account/latency tiers, collateral, visibility and order-type semantics;
441. new venues start DISCOVERY_ONLY/MEASURE_ONLY and become REPLAY_GRADE only after quality certification;
442. fee-free/low-fee routes are evaluated jointly with latency and alpha half-life;
443. account/fee/latency tier is part of route identity and cannot change silently in replay;
444. Lighter research models documented fee/latency tier differences and nonce continuity semantics;
445. Lighter zero-fee assumptions cannot prove economics for another tier/class;
446. edgeX forecast/predicted funding is timestamped feature state and not realized settlement truth;
447. edgeX funding research records premium/impact/next-settlement context where available;
448. Paradex retail/pro fee class is explicit and retail zero-fee economics are not credited to incompatible API/pro flow;
449. GRVT multi-leg research verifies actual TIF/partial-fill/joint execution semantics before claiming legging-risk reduction;
450. Extended RFQ research uses the dedicated real RFQ book for executable resting liquidity;
451. Extended RFQ fee roles are modeled separately from standard CLOB maker/taker semantics;
452. RFQ child-quote timing/count is historically versioned;
453. Aster hidden-order/position capability lowers public depth and wallet-flow completeness confidence;
454. public absence of hidden liquidity/positions is never interpreted as zero hidden liquidity/positions;
455. venue-native order types receive no alpha credit without replayable measurable execution benefit;
456. Cross-Venue Route Graph V2 includes microstructure, fee/latency tier, collateral, session, health, visibility, funding and oracle state;
457. RFQ-CLOB and native-multileg routes are distinct from ordinary taker-taker routes;
458. Lighter and edgeX enter Stage-A collection research because they add economic/data families absent from the current repository;
459. GRVT, Extended and Paradex enter Stage-B subject to replay-grade data certification;
460. Aster and other hidden/private venues enter Stage-C unless public evidence can quantify completeness;
461. new-venue promotion depends on independent opportunity gain and data quality rather than popularity alone;
462. venue-provided funding forecasts preserve their historical timestamp and never receive future settled values at decision time;
463. funding forecast intelligence must beat persistence/current-rate/simple-consensus baselines OOS;
464. route reports include committed capital, margin, idle prefunding and capital-time;
465. independent venues are never treated as cross-margined/netted for liquidation risk unless actual venue semantics support it;
466. RWA/non-24-7 venue session/market-status fields remain point-in-time economic state;
467. V6.5 venue expansion remains GitHub-hosted/read-only and cannot add signed trading paths;
468. V6.6 uses order-level/L4 evidence selectively for high-value windows rather than requiring full-history L4 collection;
469. raw book diffs are never treated as a complete book without a known initial state/snapshot and gap reconciliation;
470. per-order reconstruction keys include coin plus order id and preserve the source's canonical ordering;
471. L4 queue claims degrade to interval/uncertain state when priority/reordering or sequence evidence is incomplete;
472. public order-owner addresses from L4 are market-structure provenance only and cannot be deanonymized;
473. third-party L4 providers are sampled against official schemas before their data can certify execution evidence;
474. L4 windows calibrate broad L2 queue models using fill, timing, partial-fill, cancel-race and PnL-bias metrics;
475. broad replay cannot silently use exact FIFO assumptions on windows that contain only L2 evidence;
476. queue-sensitive maker/XEMM promotion prefers L2_CALIBRATED_BY_L4 or stronger evidence where feasible;
477. L4 evidence tier is recorded as L2_ONLY, L2_CALIBRATED_BY_L4, L4_WINDOW_RECONSTRUCTED or L4_GAPPED_OR_UNCERTAIN;
478. full raw-node history is not mirrored by default when bounded event windows provide the needed proof;
479. V6.6 cannot require a self-hosted node or user-PC collector;
480. unavailable L4 evidence remains UNMEASURABLE rather than being replaced with optimistic fill assumptions;
481. Forced-Flow tracks verified backstop inventory after absorption when point-in-time public evidence permits;
482. backstop state distinguishes absorption, inventory held, inventory unwind and inventory cleared, with UNKNOWN for incomplete evidence;
483. protocol/backstop actor identity requires official/state/on-chain provenance and cannot be inferred solely from profitable behavior;
484. post-backstop continuation, absorption relief, unwind/reversal and inventory-cleared transition are competing hypotheses;
485. liquidation, backstop absorption, inventory unwind and ADL PnL are attributed separately;
486. backstop/unwind observations from the same parent cascade are dependency-clustered for effective sample counts;
487. size-dependent liquidation fractions/cooldowns and cross/isolated semantics are versioned replay inputs where applicable;
488. current liquidation rules are not back-applied to historical periods without rule-version evidence;
489. portfolio-margin/collateral liquidations are separated from ordinary perp liquidations where public evidence supports the distinction;
490. V6.6 remains a scoped research/certification layer and does not globally block modules that do not depend on queue-exact execution;
491. all V6.6 additions remain paper/read-only and cannot authorize real orders, live queue probes, signed actions or private-key use;
492. HIP-4/outcome instruments are treated as a distinct bounded-payoff class rather than ordinary perps;
493. every outcome candidate stores machine-readable settlement semantics, quote token, fee scale, expiry and specification revision;
494. cross-venue outcome equivalence requires matching underlying, strike, expiry, settlement source/rule, payout and invalid-market semantics;
495. same label or similar question wording is never sufficient to claim outcome equivalence;
496. internal YES/NO parity uses executable prices and all fees/action/capital-time costs;
497. split/merge/negate economics are modeled only when those protocol actions are valid for the contract/version;
498. theoretical complete-set parity cannot be credited when liquidity or protocol actions cannot realize it;
499. multi-outcome/question arbitrage is generated from an explicit payoff matrix and official question metadata;
500. cross-venue outcome arbitrage cannot be labeled risk-free unless payoff equivalence holds in every valid settlement state;
501. outcome↔perp valuation models output probabilities/distributions rather than linear price targets;
502. simple empirical/realized-vol models are frozen baselines before options-implied or ML challengers;
503. options-implied outcome models use point-in-time surfaces and cannot access later IV/skew observations;
504. outcome delta-hedging experiments include hedge turnover, fees, slippage and basis/mark risk;
505. settlement-window research uses the exact contract settlement timestamp/source/interpolation rule;
506. theoretical near-expiry edges that require latency unavailable to GitHub-hosted Alina remain UNEXECUTABLE;
507. HIP-4 fee/deployer-scale/maker-rebate/action rules are versioned and current rules are not back-applied historically;
508. outcome quote/collateral currency conversion and capital lock are explicit economic costs;
509. HIP-4 research reuses shared Venue Health, Execution Truth, Cost State, Options, Lead-Lag and Intent-Netting infrastructure rather than creating duplicate engines;
510. HIP-4 starts DISCOVERY_ONLY/MEASURE_ONLY and cannot become a production/core module without scoped G3/G4, frozen OOS and forward evidence;
511. public HIP-4 bot performance claims remain hypothesis sources only;
512. all V6.7 work remains paper/read-only and cannot introduce signed outcome actions, private keys or live trading;
513. V6.8 validates point-in-time Hyperliquid price significant-figure/decimal and size szDecimals rules before fill simulation;
514. normalization/rounding deltas are recorded and expected edge is recomputed after normalization;
515. invalid tick/lot/notional/margin orders are rejected rather than rounded into favorable paper fills;
516. detailed Hyperliquid cancellation/rejection statuses are preserved as distinct causes rather than generic CANCELED;
517. selfTradeCanceled is excluded from ordinary trade-flow statistics and same-address opposing intents do not become two paper fills;
518. frontendOpenOrders trigger metadata is used only for the queried point-in-time wallet universe with explicit coverage;
519. TP/SL trigger simulation uses mark-price semantics for applicable Hyperliquid rule versions;
520. wallet trigger maps remain lower-bound/sampled maps unless market-complete L4/order evidence is certified;
521. wallet collection respects the documented 10-unique-user user-specific WS limit and records HOT_WS/WARM_REST/COLD_DISCOVERY coverage mode;
522. no report may describe more wallets as live WS tracked than the actually subscribed unique-user set;
523. historicalOrders and user-fill retention limits are treated as possible censoring/truncation rather than complete history;
524. high-activity wallet backfills record coverage bounds, pagination progress and possibly_truncated state;
525. subscription bootstrap snapshots are marked/deduplicated and reconnect streams remain RECOVERING until reconciliation completes;
526. L2 n/order-count metadata may condition queue/replenishment models but cannot imply exact queue-ahead position;
527. predictedFundings snapshots are stored with observation and next-funding timestamps and remain forecast evidence rather than realized funding;
528. missing historical predicted-funding state cannot be reconstructed from future realized funding;
529. impactPxs/premium/oracle/mark/mid/OI/funding context preserves point-in-time nullability and cannot replace certified depth;
530. quote-heavy feasibility reports include simulated open-order counts and action/cancel/modify rates;
531. strategies exceeding plausible point-in-time venue order/action limits are labeled EXECUTION_INFEASIBLE even in paper research;
532. scheduled-cancel/dead-man behavior is treated as safety/feasibility state and never as alpha;
533. account abstraction/margin mode is explicit for Relative Value and capital-efficiency calculations;
534. portfolio-margin benefits cannot be credited to classic-account scenarios and require point-in-time collateral/LTV/borrow semantics;
535. UI ticker text is not a sufficient join key; canonical HyperCore/L1/DEX/economic-underlying mapping is preserved;
536. selective L4 records source class and coverage/retention/schema so official-node, certified-remote and unverified-third-party evidence are not conflated;
537. the standard official historical archive is not treated as proof of complete historical L4 availability;
538. venue-rule changes trigger bounded regression fixtures for normalization, TIF, reduce-only, triggers, OI caps, margin tiers, delisting, self-trade, fees and priority behavior;
539. promoted execution-sensitive lanes report invalid-order rate, normalization loss, unknown status, history truncation, wallet coverage, reconnect repair, predicted-funding coverage, metadata-version coverage and margin mode;
540. material UNKNOWN/truncated rule or coverage state prevents a lane from being labeled fully measured;
541. all V6.8 additions remain GitHub-hosted/read-only and cannot require a user-PC node, signed action, private key or live calibration order;
542. perpsAtOpenInterestCap state is collected point-in-time where relevant and OI-cap constraints are not inferred solely from rejection counts;
543. OI-cap rejection/cancel subtypes remain distinct and may form a constrained-flow hypothesis only after OOS proof;
544. HIP-3 notional/size cap and deployer configuration are versioned by DEX/asset;
545. HIP-3 growth mode, deployer fee scale and aligned-collateral effects are included in fee economics;
546. venue order-value caps participate in capacity calculations before paper orders are admitted;
547. oversized candidate orders are split only when timing, action-limit and alpha-half-life constraints permit;
548. funding replay versions formula, sampling cadence, cap, interest component, impact notional and settlement timing;
549. funding payments use the correct point-in-time oracle/notional convention rather than mark-price substitution;
550. standard-perp and HIP-3 funding-premium formulas are not silently interchanged;
551. USDT-referenced oracle and USDC collateral/PnL basis are treated as residual stablecoin risk where applicable;
552. liquidation replay versions large-position partial-liquidation thresholds/fractions and cooldown rules;
553. cross, isolated and portfolio-margin liquidation mechanics are not collapsed into one liquidation-price model;
554. margin-tier-dependent maintenance requirements are used for large positions where applicable;
555. ADL is modeled as a distinct forced execution/risk route and not merged with book liquidation/backstop fills;
556. unavailable ADL-rank inputs remain UNKNOWN rather than assigning synthetic exact queue rank;
557. portfolio-margin simulations version LTV, liquidation threshold, borrow/supply caps, borrow oracle and margin-ratio mechanics where relevant;
558. portfolio-margin liquidation order across components is not assumed deterministic when protocol/oracle sequencing makes it path dependent;
559. current native TWAP duration, child interval, randomization, slippage, trigger and max/min stop mechanics are versioned where observable;
560. unexposed TWAP parent constraints are not inferred from slice fills alone;
561. Chase orders are treated as execution/provenance behavior and never receive standalone alpha status without separately proven economics;
562. protocol-change ledger includes OI-cap, margin, leverage, growth-mode, deployer-fee, funding, order-cap, PM and order-type revisions;
563. V6.9 reports constraint occupancy/binding and rule-version coverage alongside PnL so improvements caused only by an unavailable rule regime cannot be claimed;
564. all V6.9 additions remain paper/read-only and cannot authorize signed actions, live Chase/TWAP orders, private keys or user-PC services;
565. V6.10 treats direct options-volatility relative value as a distinct candidate family from options-as-context;
566. every option candidate uses point-in-time instrument metadata, executable quotes, settlement semantics, fee state and margin/account model;
567. option mark prices and mark IV cannot substitute for executable bid/ask PnL;
568. options collection uses COLD/WARM/HOT tiers and full depth is reserved for economically relevant candidate legs;
569. volatility-surface evidence stores fit quality, quote width, freshness and calibration universe;
570. arbitrage-free surface claims require explicit relevant no-butterfly/calendar checks;
571. IV-versus-RV candidates cannot assume a persistent positive volatility risk premium guarantees profitable short volatility;
572. short-vol candidates include explicit jump/tail, liquidity and hedge/funding stress;
573. calendar/skew/butterfly candidates account for every executable leg and residual greek exposure;
574. delta-hedging research compares clock-based and transaction-cost-aware hedge-band baselines;
575. option hedge PnL includes spread, slippage, fees, funding/basis and residual-delta risk;
576. option PnL attribution separates premium, delta hedge, gamma, theta, vega/surface, fees/funding and directional residual;
577. a volatility edge is rejected when profitability is primarily unintended directional exposure;
578. options margin/capacity uses historical venue/account rules when available or conservative scenario margin labeled uncertain;
579. current portfolio-margin benefits cannot be back-applied to unavailable historical/account states;
580. option/HIP-4/perp relative value requires exact underlying, threshold, expiry and settlement-rule alignment;
581. options-implied HIP-4 probabilities use only point-in-time option surfaces available before the decision;
582. executable surface-arbitrage claims require a realizable multi-leg portfolio after bid/ask, fees, margin, settlement basis and legging risk;
583. Chase economic research compares static ALO, timeout/cancel-replace, Chase/CHASE_LIKE, IOC/taker and NO_TRADE on equivalent causal opportunities;
584. Chase benchmark reports fill probability, repricing/queue uncertainty, completion, partial fills, adverse markout and missed-alpha cost;
585. insufficient historical Chase repricing/queue evidence produces UNMEASURABLE rather than optimistic maker certification;
586. triangular/graph arbitrage remains inside the route graph/Relative Value architecture unless a new independent economic mechanism is proven;
587. stablecoin quote-basis remains within Collateral Risk/Relative Value unless independent evidence justifies separation;
588. HLP/vault-flow observations remain Copy-Vault/Backstop context until they demonstrate incremental OOS predictive value;
589. public generic AI, sentiment, grid, martingale, indicator and Kelly implementations do not become first-class edge modules merely through prevalence;
590. V6.10 records corpus saturation as declining novel-mechanism yield rather than claiming exhaustive coverage of all public bots;
591. all V6.10 additions remain paper/read-only and cannot introduce live option orders, signed Chase actions, private keys or user-PC services;
592. liquidation-conditioned market making is evaluated as Forced-Flow-conditioned Execution Alpha rather than a duplicate standalone module;
593. Hawkes/event-intensity, basket-dispersion and on-chain flow findings enter existing feature/relative-value layers unless independent OOS economics prove a new mechanism;
594. on-chain exchange/bridge-flow features record source-label uncertainty and observation latency before Lead-Lag use;
595. pre-execution/split-client-block information remains WATCHLIST/UNMEASURABLE while it requires infrastructure incompatible with the GitHub-only/no-user-PC constraint;
596. future cloud-accessible pre-execution evidence may enter research only as read-only replayable data and must pass causality, latency and cost gates before promotion;
597. V6.11 preserves source-native event identity and provenance before normalization;
598. aggregate trades, raw trades and child fills cannot be double-counted as independent notional/events;
599. Binance-style aggregate trade first/last raw trade ids and aggregate id are retained where available;
600. Hawkes/event-intensity research compares sweep-defragmented event streams against raw-row baselines and reports fit sensitivity;
601. aggressor side, maker side and user order side are distinct canonical fields with venue-specific source semantics;
602. unknown aggressor side remains UNKNOWN and is never guessed from price direction;
603. every fill/trade family has a durable idempotency key and duplicate ingestion cannot create duplicate PnL/volume;
604. backfill/repair/live/archive records share normalization while retaining provenance;
605. stream gaps quarantine dependent state until compatible repair and invariant checks complete;
606. each venue uses its documented snapshot/delta/sequence/checksum contract rather than one generic book rule;
607. book-dependent signals require LIVE certified book state and cannot use a plausible-looking post-gap cache;
608. reconnect/new-stream epochs are explicit and native sequence ids are not compared across epochs without documented continuity;
609. impossible/crossed/negative/unsorted/checksum-invalid books are quarantined according to venue semantics;
610. timing-sensitive cross-venue claims include exchange timestamp resolution, local monotonic receive time and timing uncertainty;
611. measured lead not exceeding combined timing uncertainty is TIMING_UNRESOLVED;
612. cross-venue instrument equivalence includes linear/inverse/quanto payoff, multiplier, quote/settlement/collateral and notional conversion;
613. raw ticker equality cannot establish economic equivalence;
614. fill-level fee accounting preserves fee currency, maker/taker role and negative rebates;
615. non-reporting-currency fees use point-in-time conversion for PnL;
616. exact decimal/fixed-point values are authoritative for order validity, ledger and fill notional;
617. fill-derived positions are reconciled against account/clearinghouse state without fabricating missing fills;
618. liquidation/ADL/system ledger events are recognized as possible position changes outside ordinary order-fill streams;
619. historical archive retrievals carry checksum/revision/schema manifests and upstream corrections create new dataset versions rather than silent mutation;
620. effective sample counts cluster child fills/deltas/venue echoes into parent economic events where appropriate;
621. native collector/normalizer golden fixtures include duplicate, gap/repair, reconnect, side semantics, aggregate sweep, partial fill, rebate and contract-normalization edge cases;
622. collector changes that alter normalized scientific output trigger targeted evidence invalidation/rebuild;
623. V6.11 reports raw rows versus unique/sweep/independent events, duplicate/gap rates, LIVE-book coverage, unknown-side/timing-unresolved and reconciliation gaps;
624. all V6.11 additions remain read-only/paper and cannot introduce signed actions, private keys, user-PC services or live calibration orders;
625. V6.12 treats RWA corporate-action handling as market-specific unless the instrument/deployer specification defines it;
626. dividends, splits, mergers, spinoffs and symbol changes cannot be silently imported from cash-equity conventions into HIP-3 perp PnL;
627. non-24/7 reference sessions use versioned timezone/holiday/early-close/DST calendars rather than fixed UTC assumptions;
628. HIP-3 external-reference source switches are point-in-time regime events and unknown source logic remains UNKNOWN;
629. haltTrading settlement/recycle events create instrument lifecycle boundaries and cannot be modeled as ordinary session closes;
630. a recycled/redefined HIP-3 asset is not concatenated with prior history without contract-spec continuity proof;
631. dated-future research stores exact expiry, last trade, settlement reference/window, multiplier and settlement semantics;
632. continuous/back-adjusted futures prices cannot serve as executable fills;
633. roll research preserves actual contract mapping and charges both roll legs plus legging risk;
634. funding-boundary-sensitive strategies require documented position/settlement timing or are labeled FUNDING_BOUNDARY_UNCERTAIN;
635. funding cannot be credited from an assumed infinitesimal boundary timing unsupported by venue evidence;
636. subaccount/vault lineage uses explicit public protocol relationships and preserves separate execution/risk identities;
637. portfolio margin never implicitly merges separate subaccounts in Alina accounting;
638. Copy-Vault may cluster explicit linked subaccounts statistically while retaining address-level fills and observation latency;
639. wallet deposit/withdraw/transfer pre-positioning remains a WATCH/FEATURE hypothesis until matched-control OOS evidence exists;
640. instrument lineage versions listing, delisting, redenomination, migration, multiplier, collateral, oracle, recycle, corporate action and expiry/roll changes;
641. same/similar ticker across lineage breaks cannot be merged without economic-equivalence proof;
642. V6.12 proof reports calendar, corporate-action, reference-source, settlement/roll, funding-boundary and account-lineage coverage;
643. all V6.12 additions remain GitHub-hosted/read-only and cannot introduce signed actions, private keys, user-PC services or live calibration orders;
644. V6.13 models Hyperliquid self-trade prevention as expire-maker, preserving aggressor continuation through eligible external liquidity;
645. selfTradeCanceled creates no ordinary trade/fee and is excluded from market trade-volume features;
646. TP/SL replay uses mark-price trigger semantics and distinguishes trigger activation, child placement and child execution;
647. parent-attached TP/SL replay versions full-fill, manual partial-parent cancellation, insufficient-margin cancellation and sibling-cancel semantics;
648. current TP/SL market slippage bounds are versioned and not back-applied historically;
649. native TWAP replay tracks target execution, realized execution, catch-up and residual quantity rather than imposing a uniform path;
650. current native TWAP child slippage and catch-up-size limits are versioned rule inputs;
651. expiresAfter deadlines are enforced before paper matching and stale-expiry action-cost effects enter feasibility when applicable;
652. modify/batchModify preserves always_place, cancel outcome, replacement outcome, TIF transformation and queue consequence;
653. a payload-level batch pre-validation rejection rejects every child action and cannot be replaced by per-child optimistic execution;
654. fast-cancel eligibility/effect is versioned and no future priority behavior is back-applied to earlier periods;
655. schedule-cancel lead time and daily trigger-count limits are modeled as safety/feasibility constraints;
656. paper quote feasibility includes open-order limits, action budget, cancel allowance, batch counting and congestion-state constraints;
657. high-congestion maker-share restrictions are measured when available and otherwise produce conservative stress/CONGESTION_LIMIT_UNKNOWN;
658. paper market orders respect IOC/price-protection/no-liquidity semantics and cannot consume unlimited depth;
659. mark/oracle timestamps are separated from raw trade/BBO timestamps for TP/SL, liquidation, margin and unrealized-PnL transitions;
660. funding evidence distinguishes premium samples, running estimates, exchange predictions, final settled rate and realized payment;
661. no decision can access a final funding rate before it is point-in-time knowable;
662. standard-perp, HIP-3 and Hyperp funding formulas remain separate versioned families;
663. funding reconstruction versions impact notional, formula, clamp, cap, interest component, multiplier and settlement cadence;
664. maximum market/limit order-value caps participate in capacity before paper admission;
665. order splitting above a venue cap charges extra timing/action/fee/impact cost and is rejected when alpha half-life cannot support it;
666. precision fixtures cover significant figures, integer exceptions, szDecimals, min notional and edge-flipping normalization;
667. disappearance from a reconnect/open-order snapshot cannot by itself create a paper fill;
668. every execution-sensitive proof emits a point-in-time market-rule manifest and missing PnL-critical rules remain RULE_UNKNOWN;
669. V6.13 can increase proof quality by invalidating false-positive fills even when it creates no new alpha;
670. all V6.13 additions remain GitHub-hosted/read-only/paper and cannot introduce signed actions, private keys, user-PC services, self-hosted nodes or live calibration orders;
671. V6.14 versions IOC/write priority, ALO queue priority and gossip/read priority as distinct mechanisms;
672. ALO priority cost is charged according to the historical placement rule even when the order never fills, rather than only on fills;
673. repeated ALO cancel/reprice cycles include cumulative priority-placement cost and cannot appear free when unfilled;
674. priority-fee eligibility, max/useful range, charge basis and recent-order queue window are versioned rather than treated as timeless;
675. priority-cost-unavailable historical periods are PRIORITY_COST_UNMEASURABLE rather than zero-cost;
676. paper fee state uses point-in-time achievable user/account economics rather than a repository-wide constant whenever evidence exists;
677. rolling weighted volume, master/sub-account aggregation, vault separation, VIP/MM tiers, rebates, referral/staking discounts, builder/deployer/growth-mode fees are individually attributable when relevant;
678. future-earned fee tiers or discounts cannot leak backward into historical proof;
679. all normalized midpoint values carry provenance distinguishing executable BBO midpoint from last-trade/other fallback;
680. an allMids last-trade fallback caused by an empty book cannot certify executable Cross-Venue or Lead-Lag dislocation;
681. standard-perp funding reconstruction uses the point-in-time formula family, premium sample cadence, impact notional, clamp/cap, interest component and hourly settlement rule;
682. realized standard funding cash flow uses the documented oracle-price notional rather than substituting mark price;
683. funding evidence distinguishes raw premium inputs, running estimate, exchange prediction, Alina forecast, final rate and realized payment;
684. predictedFundings coverage remains limited to the DEX/venues actually returned at that timestamp and cannot be extrapolated to unsupported HIP-3 DEXs;
685. mark, oracle, BBO/mid and last-trade timestamps are separate evidence streams and cannot be interchanged for trigger/liquidation/funding semantics;
686. quanto/quote-currency normalization records oracle/reference denomination, collateral denomination and residual stablecoin basis exposure;
687. TP/SL replay preserves mark-trigger, bounded-slippage, parent-child, partial-parent and sibling-cancel rule versions;
688. native TWAP replay versions child slippage, catch-up multiplier, underfill/residual state and exposed randomization/configuration;
689. self-trade prevention is modeled as expire-maker with aggressor continuation, no prevented-match fill and no ordinary trade-volume print;
690. expiresAfter, fast-cancel, scheduled-cancel, always_place and batch pre-validation rules are represented at action/batch level;
691. payload-level batch rejection cannot be transformed into per-child fills;
692. quote-heavy feasibility includes open-order count, action/cancel/modify budgets and congestion maker-share constraints where applicable;
693. maximum market/limit order-value caps constrain capacity before execution admission;
694. capacity splitting above venue order caps adds child-order latency, impact and action cost before edge is re-evaluated;
695. FrontendMarket/UI-origin order provenance is retained when available and cannot be normalized blindly to infinite-depth market execution;
696. exact fill/fee/funding/account ledgers remain authoritative over convenience-derived entry-price or displayed PnL fields;
697. opening/closing/mark-price PnL accounting is covered by golden fixtures against official rule examples;
698. conflicting official rule generations create separate versioned semantics or RULE_VERSION_UNCERTAIN rather than a blended rule;
699. V6.14 can invalidate a candidate solely because exact costs/reference semantics remove its net edge, which is considered successful proof-quality improvement;
700. all V6.14 additions remain GitHub-hosted, read-only and paper-only, with no signed actions, private keys, user-PC execution, self-hosted node or live calibration order;
701. V6.15 stores current numeric protocol constants in a versioned manifest and never treats them as timeless historical truth;
702. standard-perp funding impact notional is currently represented as 20,000 USDC for BTC/ETH and 6,000 USDC for other standard assets, subject to rule version;
703. standard-perp current maximum market-order notional follows the documented leverage buckets and maximum limit-order notional is 10x the applicable market-order cap;
704. funding replay versions the current 0.01%/8h interest component, 5-second premium sampling, clamp parameters, hourly conversion and current 4%/hour cap;
705. standard funding cash flow uses position size times oracle price times funding rate under the current documented rule rather than mark-price notional;
706. ordinary-perp oracle replay preserves the documented spot-source set/weights and validator stake-weighted aggregation where the historical rule is known;
707. ordinary-perp mark replay preserves the documented three-component median, 150-second EMA term and conditional 30-second EMA fallback where historically applicable;
708. mark/oracle update cadence is treated as event state and current roughly-3-second cadence is not back-applied without rule evidence;
709. TP/SL, liquidation, margin and unrealized-PnL mechanics use mark rather than last trade or raw mid when the protocol rule requires mark;
710. margin-tier replay applies the maintenance-deduction continuity formula and cannot reduce tiered margining to one leverage scalar;
711. current large-liquidation 100k-USDC threshold, initial 20% book fraction and 30-second cooldown are versioned rather than timeless;
712. current address-level action feasibility models one request per cumulative USDC traded, 10,000-request initial buffer and one-request-per-10-second behavior after rate limiting;
713. current cancel action allowance uses the documented min(limit + 100000, limit * 2) rule where historically applicable;
714. current open-order capacity models 1000 base slots, +1 per 5M USDC volume, 5000 cap and special trigger/reduce-only rejection behavior at the documented threshold;
715. batched execution feasibility counts one IP request but n address-level requests for n batched actions under the current rule;
716. current high-congestion feasibility models the documented 2x prior-day maker-share block-space constraint when the required state is measurable;
717. Chase is represented as a browser/frontend execution controller rather than assumed persistent server-native order state;
718. current Chase replay uses post-only repricing one tick inside the spread where possible and respects the current maximum of five active Chase orders;
719. native TWAP replay versions current 5-minute-to-7-day duration, 30-second minimum interval and 100-USD minimum total size;
720. native TWAP replay versions current 3% child slippage, optional ±20% randomization, mark trigger, max/min termination and 3x catch-up child cap;
721. native TWAP can end with residual unexecuted quantity and cannot be reconstructed as guaranteed full completion;
722. displayed entry price and PnL are treated as derived frontend/accounting views and are reconciled against fills/fees/funding/ledger state;
723. opening trades update entry price by size-weighted average and closing trades preserve remaining-position entry price under the current documented convention;
724. unrealized PnL uses mark price under the current documented convention and fee/funding cash flows remain separately attributable;
725. margin-use replay versions current position-size × mark / leverage initial-margin arithmetic where applicable;
726. margin-removal feasibility includes the current max(initial margin, 10% total position value) transfer-margin requirement where applicable;
727. Hyperp replay uses a separate reference formula and does not reuse the ordinary spot-oracle-perp model;
728. current Hyperp research versions the 8-hour mark-history EMA reference, 3x EMA mark cap, optional 1.5x external-prelaunch median cap and 4x one-month-average oracle cap;
729. Hyperp mark/oracle cap binding state is stored so a cap-induced residual is not mistaken for free convergence alpha;
730. index, Uniswap/AMM, HIP-3, standard, Hyperp and HIP-4 instruments remain distinct reference classes;
731. instrument normalization cannot merge two products whose oracle/reference/collateral/payoff semantics differ even if ticker text matches;
732. PROTOCOL_CONSTANTS_MANIFEST entries include units, effective interval, official source, collected-at timestamp and historical-certification confidence;
733. historical replay fails closed or marks UNMEASURABLE when a required numeric rule cannot be established for that period;
734. tests reject direct hard-coded current constants in historical decision paths when a versioned manifest field exists;
735. all V6.15 work remains GitHub-hosted, read-only and paper-only, with no signed actions, private keys, self-hosted node, user-PC dependency or live calibration order.

736. V6.16 treats public-book liquidation, partial book liquidation, backstop transfer and ADL as distinct lifecycle routes;
737. current-standard backstop eligibility below 2/3 of maintenance margin is versioned and not back-applied without historical rule evidence;
738. successful public-book liquidation may preserve residual trader collateral and replay does not automatically zero the account;
739. cross backstop transfer moves cross positions plus cross margin while preserving unrelated isolated positions under the documented rule;
740. isolated backstop transfer is scoped to the isolated position and isolated margin;
741. the backstop maintenance-margin buffer retained by the liquidator mechanism is accounted separately from ordinary trading fees;
742. liquidation state incorporates funding and other cross-position PnL where those affect account equity;
743. displayed or estimated liquidation price is not authoritative event truth without matching point-in-time account and rule reconstruction;
744. margin mode distinguishes CROSS, ISOLATED, STRICT_ISOLATED, NO_CROSS and applicable unified/portfolio-margin state;
745. strict-isolated margin-removal restrictions and no-cross semantics are preserved in capital and liquidation simulation;
746. cross-DEX margin sharing is credited only when modeled account abstraction and common-collateral rules explicitly allow it;
747. position-associated fixed-size TP/SL does not silently resize after later position changes;
748. order-associated TP/SL children remain unplaced while the parent is not sufficiently activated under the applicable rule;
749. manual cancellation of a partially filled parent cancels its child TP/SL rather than automatically resizing children to the filled quantity;
750. a partially filled parent canceled for insufficient margin follows the current documented exception that places children as if the parent were fully filled;
751. TP/SL trigger activation uses point-in-time mark price and triggered state remains distinct from filled state;
752. current TP/SL-market 10% slippage tolerance is a versioned rule input, not a timeless constant;
753. funding transfer is accounted separately from trading, builder, deployer and priority fees and is not double-counted as a protocol trading fee;
754. positive and negative funding direction is preserved explicitly in long/short cash-flow accounting;
755. native TWAP target schedule is never substituted for realized executed quantity and terminal residual remains unexecuted;
756. self-trade prevention and other order-state transitions that do not print as trades require order-state/fill reconciliation rather than trade-feed-only inference;
757. V6.16 source rules are pinned to the documented protocol version/date and current semantics are not silently back-applied;
758. all V6.16 semantics remain GitHub-hosted, paper/read-only and cannot enable signed actions, private keys, live order placement, self-hosted nodes or user-PC dependencies.

759. every paper account declares point-in-time account abstraction mode rather than assuming one universal margin/balance model;
760. Unified, Portfolio Margin and Standard modes use their documented balance/cross-margin scopes and data-source semantics;
761. current Unified/Portfolio Margin 50k-user-actions-per-day constraint is versioned and included in hypothetical execution feasibility;
762. Standard-mode builder-fee accrual constraints are preserved when builder-flow economics are modeled;
763. Portfolio Margin eligibility is not assumed unless point-in-time account value/volume and protocol rules permit it;
764. current Portfolio Margin global/user supply and borrow caps are versioned per asset and cap exhaustion removes unavailable capital efficiency;
765. current HYPE/BTC LTV values are versioned and cannot be generalized to every collateral asset;
766. Portfolio Margin borrowing records borrow oracle, utilization, LTV, caps, accrued interest and rule version;
767. current stablecoin borrow-interest formula and 10% protocol interest retention are treated as versioned accounting inputs;
768. Portfolio Margin liquidation uses the portfolio-specific health/ratio model and cannot reuse ordinary perp liquidation semantics blindly;
769. current portfolio-margin liquidatable threshold above 0.95 is versioned rather than treated as timeless;
770. current portfolio-margin direct-backstop route is distinguished from ordinary public-book perp liquidation;
771. partial Portfolio Margin takeover in 20% intervals and full takeover are separate states under the applicable rule;
772. asset-specific takeover/slippage width constants are versioned and cannot be generalized across collateral assets;
773. backstop collateral-to-debt conversion TWAP with current 10-minute half-life is modeled as a distinct unwind process where applicable;
774. Portfolio Margin liquidation ordering between perps and spot borrows remains uncertain unless reconstructed from actual oracle/event ordering;
775. validator-operated perp delisting is represented as a dedicated settlement event rather than an ordinary discretionary close;
776. current delisting settlement uses the documented 1-hour time-weighted spot-oracle rule for the applicable version;
777. delisting cancels open orders and forbids post-settlement paper fills;
778. delisting PnL is attributed separately from normal strategy exit PnL;
779. fill, fee, funding, collateral/margin and transfer/borrow ledgers remain accounting authority over frontend-derived PnL displays;
780. perp entry-price display follows weighted-average increase and unchanged remaining-entry behavior only as a reconciliation model;
781. spot displayed cost basis from transfers/legacy balances cannot substitute for actual strategy acquisition cost when attribution is ambiguous;
782. all V6.17 rules remain GitHub-hosted, paper/read-only and cannot introduce signed actions, private keys, live probing, self-hosted nodes or user-PC dependencies.

783. ADL is modeled as a distinct solvency route rather than an ordinary market liquidation;
784. current ADL eligibility starts from negative account value or negative isolated-position value under the documented rule;
785. profitable opposite-side counterparties are ranked using the versioned documented ADL index rather than a generic leverage-only heuristic;
786. ADL execution uses the protocol-defined previous mark price for the applicable rule version rather than ordinary BBO/VWAP pricing;
787. backstop-acquired positions receive no special ADL queue treatment unless a future rule version explicitly introduces one;
788. flat accounts are not assigned socialized-loss/ADL cash flows when the protocol invariant excludes them;
789. ADL observations are dependency-clustered with their parent insolvency/backstop episode for effective-sample accounting;
790. all V6.18 work remains GitHub-hosted, paper/read-only and cannot introduce signed actions, private keys, live probing, self-hosted nodes or user-PC dependencies;
791. every relevant perp records oracle-source class so AMM, formula-index, Hyperp, HIP-3 and ordinary spot-oracle contracts are not normalized as identical;
792. AMM-perp relative-value research uses executable AMM quotes for candidate notional rather than raw pool marginal price alone;
793. AMM-side economics include pool/route fee, price impact, gas, state staleness and timing uncertainty;
794. cross-protocol arbitrage cannot assume instantaneous free capital transfer between AMM and perp venues;
795. Hyperliquid Uniswap-oracle perps preserve isolated-only and margin-removal restrictions for the applicable contract version;
796. Uniswap pool-to-USDT oracle conversion path is recorded and versioned rather than inferred from ticker alone;
797. delta-neutral LP research accounts for dynamic LP inventory/delta rather than using a permanent 1:1 hedge assumption;
798. LP fee income is reported net of LVR/impermanent-loss, gas/rebalance, hedge execution, funding, basis drift and capital-time cost;
799. unhedged LP, static hedge and dynamic hedge are separate frozen baselines;
800. LP hedge rebalance thresholds/frequency are tuned only on TRAIN and turnover cost is explicit;
801. formula/index perps store point-in-time formula, constituent, weight, FX/conversion, announcement/effective and revision state where available;
802. index-rebalance research cannot use future constituents or final weights before their first-observable announcement;
803. independently reconstructed index value and validator-published index value remain separate evidence fields;
804. index-perp residual is not called arbitrage unless an economically executable replicating/hedge route exists;
805. basket replication includes component-level spread/slippage, tracking error, legging risk and capital cost;
806. AMM/index cross-source comparisons preserve block/source timestamps and synchronization uncertainty;
807. V6.19 sleeves begin DISCOVERY_ONLY/MEASURE_ONLY and do not globally block existing modules;
808. all V6.19 work remains GitHub-hosted, paper/read-only and cannot introduce signed swaps/orders, private keys, self-hosted nodes or user-PC dependencies.
809. V6.20 records IOC write priority, ALO queue priority and gossip/read priority as distinct mechanisms with separate charging and ordering semantics;
810. current write-priority grouping requires non-outcome assets and a homogeneous all-IOC or all-non-reduce-only-ALO batch;
811. a mixed or otherwise ineligible priority batch is rejected in feasibility simulation rather than partially credited with priority;
812. current priority rate encoding p/100000000 and the applicable rule version are preserved point-in-time;
813. current IOC priority cost is based on filled notional while current ALO priority cost is based on resting notional at placement;
814. current order-priority payment source, HYPE spot-mark conversion and burn semantics are modeled separately from ordinary trading fees;
815. IOC ordinary temporal-priority benefit is versioned as saturating around 8 bps under the current documented rule, while the parameter range and higher-priority tie-breaking remain distinct concepts;
816. current same-proposer-bucket higher-priority IOC ordering is not converted into additional continuous latency reduction above the saturation region;
817. ALO priority is modeled as a continuous roughly-400-ms same-level queue-tail reorder, not as faster mempool arrival;
818. ALO priority placement cost is charged even for orders that never fill under the current documented rule;
819. older locked queue position cannot be freely overtaken by a later ALO merely because it pays more priority;
820. current cancel/ALO versus IOC/GTC action-class ordering is modeled as venue/version sequencing behavior and not generic CEX packet-arrival FIFO;
821. an IOC priority fee cannot be credited with overtaking a cancel when the applicable venue rule prioritizes cancels first;
822. gossip/read priority is economically distinct from write priority and its auction fee/state cannot be substituted for order priorityGas;
823. current gossip-priority auction count, cadence, minimum bid, IP/path dependence and approximate slot latency effect are versioned inputs;
824. node/split-client-block/gossip advantages unavailable to GitHub-hosted Alina are treated as competitor latency frontier or UNEXECUTABLE_CURRENT_ARCHITECTURE, never silently credited to Alina;
825. absolute end-to-end latency and relative transaction-sequencing latency are separate state variables;
826. SDK-style market helpers are modeled as protected aggressive IOC limits rather than infinite-depth native market orders;
827. the official Python SDK current 5% market-helper slippage default is labeled CLIENT_DEFAULT and cannot be back-applied as a protocol constant or UI default;
828. allMids fallback provenance remains active when an SDK-style protected IOC reference price is reconstructed;
829. hypothetical action batching preserves order-class purity where priority/ordering semantics depend on ALO versus IOC/GTC versus cancel classes;
830. nonce/API-wallet transport rules are retained only for hypothetical feasibility and cannot introduce signing/private-key code into the research path;
831. paper feasibility may reject an action policy that requires incompatible batch composition, impossible throughput or unavailable low-latency transport even if signal PnL is positive;
832. IOC priority evidence prefers node/user-fill priorityGas while ALO placement-cost evidence requires action/resting-notional provenance;
833. missing ALO placement evidence is PRIORITY_PLACEMENT_UNMEASURABLE rather than zero cost;
834. priority-sensitive sleeves report break-even priority rate and fraction of gross alpha consumed by priority cost;
835. a priority-sensitive edge may be killed when competitive priority economics absorb its post-cost advantage;
836. conflicting official snippets are reconciled against current Markdown plus first-party implementation/version evidence before a protocol rule is frozen;
837. V6.20 keeps all numeric latency/priority observations versioned and does not treat empirical current-mainnet effects as deterministic guarantees;
838. all V6.20 work remains GitHub-hosted, paper/read-only and cannot introduce signed actions, API-wallet operation, private keys, live probing, self-hosted nodes or user-PC dependencies;
839. Hyperliquid portfolio-graph samples are treated as coarse reconciliation evidence rather than precise accounting truth;
840. 15-minute/deposit-withdrawal graph sampling cannot certify intraperiod PnL extrema or drawdown without stronger event evidence;
841. venue frontend graph PnL definitions are preserved as reported and differences from Alina's ledger become explicit reconciliation exceptions;
842. Hyperliquid UI max drawdown remains a frontend-only reconciliation metric and does not replace Alina's certified equity-curve drawdown;
843. sampled frontend histories cannot prove absence of deeper intraperiod drawdown;
844. proof-source precedence is event ledger > reconciled account state > venue-derived analytics > frontend graph/UI;
845. all V6.21 work remains GitHub-hosted, paper/read-only and introduces no signed actions, private keys, live probing, self-hosted nodes or user-PC dependencies.
846. canonical execution evidence preserves unaggregated fills when available and does not use aggregateByTime-compressed fills for queue/partial-fill proof;
847. periods with only aggregated fill evidence are labeled AGGREGATED_FILL_EVIDENCE and receive weaker execution-certification status;
848. source-native trade id tid is the preferred fill dedup identity where available and timestamp-price-size alone is insufficient;
849. builderFee is treated as a component already included in the reported total fee under the current Hyperliquid fill schema;
850. feeToken and fee sign are preserved so rebates and non-default fee currencies cannot be mis-accounted;
851. venue-native crossed is preferred for maker/taker attribution and reconstructed aggressiveness remains a cross-check;
852. reconnect/bootstrap snapshots are deduplicated against previously committed fill/order identities and are never counted as fresh duplicate events;
853. current 60-second server-idle WebSocket timeout is versioned and quiet streams use heartbeat/pong health handling;
854. heartbeat/pong traffic is excluded from market-event and opportunity counts;
855. reconnect recovery requires snapshot/backfill reconciliation and continuity checks before feed health returns to HEALTHY;
856. both oid and optional 128-bit cloid are retained for order reconciliation without conflating either with trade identity;
857. unknownOid does not prove nonexistence when account/DEX scope or data continuity is uncertain;
858. multi-DEX open-order queries preserve explicit DEX scope and do not infer no-order state from the first-DEX default;
859. openOrders/frontendOpenOrders, orderUpdates, fills and historical status sources have distinct bootstrap/lifecycle/execution/reconciliation roles;
860. frontend labels remain provenance/semantic hints and cannot invent matching-engine behavior absent a protocol rule;
861. Scale is modeled as child limit-order decomposition/controller until stronger point-in-time server-native parent semantics are proven;
862. Scale/adaptive ladders charge child-level queue, latency, fee and partial-fill economics rather than atomic-parent fills;
863. user-specific streaming coverage respects current connection/subscription/unique-user/message constraints and reports constrained coverage when limits bind;
864. data-plane sharding/rotation cannot silently convert partial wallet coverage into complete-market trigger/copy evidence;
865. all V6.22 work remains GitHub-hosted, paper/read-only and cannot introduce signed actions, private keys, live probing, self-hosted nodes or user-PC dependencies;
866. V6.23 models Hyperliquid self-trade prevention as expire-maker: the resting self order is canceled, no fill/fee/trade-print is created, and the aggressor may continue through external liquidity;
867. selfTradeCanceled is lifecycle evidence rather than execution volume;
868. current price validation applies the five-significant-figure rule plus the perp/spot decimal bound derived from szDecimals, while integer prices remain valid under the documented exception;
869. size validation uses point-in-time szDecimals and invalid price/size normalization cannot improve a candidate's paper economics;
870. TP/SL trigger evaluation uses point-in-time mark price rather than last trade/BBO;
871. TP/SL market and limit execution retain their documented slippage/limit semantics after trigger and do not receive guaranteed fills;
872. parent-associated TP/SL children remain inactive/canceled or become active according to the documented full-fill, user-cancel and margin-cancel lifecycle, including the partial-fill plus insufficient-margin exception;
873. native TWAP replay models current minimum interval, duration, minimum-notional, child-slippage, catch-up cap and residual-unfilled behavior rather than assuming a smooth complete schedule;
874. TWAP trigger/termination controls use the applicable mark-price semantics and network/post-only execution restrictions for the rule version;
875. standard-perp funding replay uses five-second premium sampling, hourly settlement from the eight-hour formula and the current documented cap only for rule intervals where those semantics are valid;
876. standard funding cash flow uses position size times oracle price times funding rate and does not substitute mark price for oracle price;
877. HIP-3 funding premium rules remain distinct from standard-perp funding rules;
878. predicted/current funding remains forecast state and cannot be substituted for finally realized settlement;
879. impactPxs/premium/null fields preserve point-in-time provenance and contract-specific impact-notional semantics;
880. stale expiresAfter feasibility accounts for the documented higher address-rate-limit cost where the historical/current rule applies;
881. fast-cancel feasibility does not assume trigger-order support when the rule rejects fast cancel for triggers;
882. scheduled cancel/dead-man-switch timing, daily trigger cap and reset semantics are modeled as feasibility/safety state rather than alpha;
883. modify/batchModify respects always_place and rule-specific cancel-replace semantics rather than assuming timeless atomic edit behavior;
884. deterministic batch pre-validation failure rejects the full paper batch when the venue rule would reject the full batch;
885. open-order feasibility versions the current 1000-base, volume-expanded and 5000-cap rule rather than assuming unlimited resting orders;
886. trigger/reduce-only feasibility accounts for the documented rejection behavior once open-order thresholds are exceeded;
887. batched actions distinguish IP-request counting from child-count address-rate accounting;
888. congestion-state feasibility accounts for current documented maker-share/block-space constraints when evidence exists and otherwise applies explicit uncertainty stress;
889. mark/oracle update timing is separate from BBO timing so mark-triggered events cannot fire from BBO alone;
890. every numerical V6.23 protocol rule is tagged to a verified rule interval and historical unknowns remain UNMEASURABLE_RULE_VERSION;
891. executable net-PnL proof must fail closed when a material V6.23 validity, trigger, funding, lifecycle or throughput input is missing;
892. V6.23 adds no signed/live action path and preserves GitHub-hosted paper/read-only operation.
893. the canonical acceptance catalog rejects duplicate numeric IDs and future criteria allocate IDs strictly above the current maximum;
894. acceptance-ID renumbering requires an explicit migration map and cannot silently reuse an existing ID;
895. every PnL/admissibility-critical venue rule has a provenance manifest with source, collection time, effective interval/confidence, parser version and normalized unit where available;
896. current official rules are never silently back-applied to historical periods without applicability evidence;
897. conflicting first-party rule sources are retained and resolved by version rather than averaged;
898. canonical instrument identity includes venue/DEX scope, instrument class, native identifier where available, collateral/reference semantics and metadata version rather than symbol text alone;
899. point-in-time asset/index mappings are versioned and identifier reuse cannot silently merge economically different contracts;
900. timestamp fields declare semantic meaning and unit, normalize wall time to UTC and preserve source ordering evidence;
901. second/millisecond/microsecond conversions have boundary fixtures so unit mistakes cannot create false lead-lag or fill timing;
902. economically relevant numeric fields carry explicit unit/scale and bps/decimal/percentage conversions are centralized;
903. deterministic Decimal/fixed-point or equivalent arithmetic is used where floating representation could alter tick validity, notional, fee or accounting state;
904. fee/rebate/funding and other ledger signs are preserved under one documented account-value sign convention;
905. builder/deployer/priority attribution remains distinct from total cash-flow amount so components are not double-counted;
906. optional protocol fields whose valid serialization requires omission rather than explicit false/null are modeled with exact omission semantics in feasibility fixtures;
907. serialization feasibility cannot introduce private keys, signing code or live actions;
908. unknown future order/status/rejection enum values are preserved raw and never defaulted to a favorable terminal state;
909. schema drift tracks field set, enum set, nullability, representation, timestamp units, pagination and snapshot/incremental semantics;
910. semantic schema changes create a new version and cannot silently reuse an older parser assumption;
911. additive unknown fields do not unnecessarily stop unrelated collection paths when core semantics remain certified;
912. the completeness matrix explicitly covers identity, precision, books, queue, latency, lifecycle, fees, funding, reference prices, margin, liquidation, venue state, portfolio attribution and rule provenance;
913. any missing proof-critical completeness row propagates scoped UNMEASURABLE/UNCERTAIN state rather than a default guess;
914. same-ticker instruments across DEXs/deployers/reference families remain distinct until semantic compatibility is certified;
915. rule/source hashes or immutable revision identifiers are retained when available so later documentation drift is detectable;
916. the canonical provenance/serialization closure introduces no new profitability claim or alpha module; it is a proof-quality and representation-integrity layer;
917. all canonical provenance/serialization requirements remain GitHub-hosted, paper/read-only and cannot create self-hosted-node or user-PC dependencies;
918. the repository treats this file as the single canonical current spec and does not create a new versioned spec/tranche for routine research updates;
919. historical V6.x labels are change-history markers only and future verified evidence is merged into functional sections plus this acceptance catalog;
920. point-in-time account-abstraction mode is stored and Standard, Unified and Portfolio Margin balance semantics are not conflated;
921. Unified/Portfolio Margin proof uses the documented shared/spot-clearinghouse balance representation and does not treat individual perp-DEX user states as standalone balance truth;
922. current Unified/Portfolio Margin user-action limits are modeled as versioned feasibility constraints where relevant;
923. manual borrow, auto-borrow, supply interest, borrow interest, repayment and borrow liquidation are separate ledger classes and cannot be misclassified as trading PnL;
924. conflicting first-party Portfolio Margin constants remain RULE_SOURCE_CONFLICT until a controlling rule is established and the engine cannot choose the favorable value;
925. non-deterministic Portfolio Margin liquidation ordering caused by oracle-update ordering is preserved as uncertainty rather than forced into a deterministic sequence;
926. current multi-DEX WebSocket coverage recognizes DEX-scoped clearinghouse/TWAP state plus all-DEX clearinghouse and asset-context streams;
927. activeAssetData is capacity/account-state evidence and cannot create alpha by itself;
928. undocumented webData3 fields cannot become proof-critical dependencies;
929. fastAssetCtxs decoding follows the documented base64/raw-DEFLATE/UTF-8 JSON wire contract and sparse deltas are merged without zero-filling omitted fields;
930. outcomeMetaUpdates is metadata/state evidence and not substituted for executable price or fill evidence;
931. canonical Hyperliquid trade identity uses block/event time plus instrument identity plus tid; tid alone is not assumed globally unique;
932. BBO event sparsity advances quote age when no new BBO change message arrives and absence of a message is not treated as a fresh quote;
933. trailing-stop replay separates mark-price activation, watermark, retracement, trigger and execution and labels hidden historical state unobservable when it cannot be proven;
934. frontend/support trailing-stop wording cannot create a fictional server-native lifecycle absent protocol/API evidence;
935. reserve-request weight and nonce-invalidating no-op are modeled only as signed-action feasibility semantics, with no signing or live action path in Alina;
936. paid additional action capacity is charged as cost rather than free throughput when evaluating hypothetical high-frequency feasibility;
937. exchangeStatus, spot clearinghouse state and active-asset state are control-plane/account evidence, not alpha by default;
938. latest-source conflicts, sparse-schema changes and account-mode changes propagate scoped uncertainty instead of spawning another spec version.
939. one LLM controller is the default and Agent Skills do not spawn, imply, or authorize additional LLM agents;
940. no subagent, second coding agent, debate team, or multi-agent fan-out is used unless the user explicitly changes the single-controller policy;
941. Alina skills use narrow trigger descriptions and progressive disclosure rather than loading their full instructions into every task;
942. skill content references the canonical spec for project truth and does not fork a second competing specification;
943. overlapping or contradictory skills are merged, narrowed, disabled, or removed instead of accumulating indefinitely;
944. quota-minimal execution prefers one model decision followed by the largest safe deterministic batch and a compact result summary;
945. when the user explicitly launches a local Codex/agent checkout, deterministic development tests, replay, backtest, lint, static analysis and CPU-heavy validation run locally as much as practical;
946. no autonomous workflow, ChatGPT action, or GitHub Action may wake, commandeer, depend on, or configure the user's PC as a self-hosted runner;
947. GitHub Actions are reserved for cloud-native collection/orchestration, essential integration/release gates, or checks not adequately established on the active local tree;
948. completion discipline maintains a bounded unfinished-work ledger and continues through independent requested work after intermediate milestones;
949. repeated failures change method after two materially identical attempts and become an explicit blocker after a third equivalent failure rather than an unbounded loop;
950. GitHub-changing work cannot be called complete until final HEAD is checked and any expected content change is verified to have a real diff and a different tree from its parent;
951. completion discipline cannot manufacture empty commits, claim background execution, or override platform, credential, safety, or external-service hard limits.
952. ChatGPT/Codex long-running Alina work continues through feasible requested items in the same active turn/session instead of stopping at planning, one tool call, one file edit, one test, one commit, or one intermediate success;
953. interactive completion maintains a compact completed/in-progress/blocked/remaining ledger and advances to the next feasible unfinished item without requiring redundant confirmation;
954. repeated conversational/tool failures change method after two materially identical failures and become an explicit checkpointed blocker after a third equivalent failure while independent work continues;
955. a real interruption leaves a durable continuation checkpoint with verified repository state, completed work, exact remaining work, and next safe action, without claiming unscheduled background execution or spawning extra agents.
956. required first-party Alina executable code is measured with branch coverage enabled and the enforced threshold is exactly 100%, with no rounding of sub-100 results;
957. line/statement coverage alone cannot satisfy the coverage gate and every reachable decision outcome, error/fail-closed path, boundary condition and state-transition branch in scope is exercised;
958. economic-, data-integrity-, timing-, replay-, orchestration-, and paper/read-only-safety-critical branches cannot be excluded from coverage, and coverage exclusions cannot be used to game the metric;
959. any permitted coverage exclusion is narrow, documented, reviewable, limited to genuinely non-decision first-party/generated/third-party/platform glue, and unreachable first-party logic is preferentially removed or refactored;
960. completion, release, or certification of implementation against this spec is blocked while required branch coverage is below 100%, while 100% coverage remains separate from economic/OOS/data-quality correctness gates.
961. certified PnL is reconstructible from one canonical append-only accounting ledger and no dashboard, strategy helper, legacy module or report may maintain an independent proof-authority PnL counter;
962. any material missing or ambiguous PnL component propagates UNMEASURABLE_PNL/INVALID_PNL and cannot default to zero;
963. alternate/legacy PnL helpers with permissive defaults or heuristic close detection remain diagnostic-only until they satisfy the canonical accounting contract;
964. realized PnL requires a valid OPEN/ADD/REDUCE/CLOSE lifecycle and cannot be inferred solely from a non-zero PnL field, action label, disappearing snapshot or dashboard classification;
965. actual filled quantity, fill price and filled notional reconcile within documented contract tolerance and fees are charged from economically applicable filled amount rather than inconsistent requested notional;
966. reductions/closures cannot exceed open quantity in certified accounting and over-close/overfill mismatches fail closed instead of silently clipping proof economics;
967. fills, funding settlements, fee/rebate events, liquidations and non-funding ledger updates have stable exactly-once identities across REST/WS snapshots, reconnect overlap, backfill, archive repair and replay restart;
968. snapshot or bootstrap re-observation of an already-accounted source event cannot change canonical PnL;
969. Hyperliquid settled funding proof uses actual userFunding/userFundings events or exact point-in-time hourly settlement reconstruction with position size, oracle price and applicable funding rule;
970. prorated funding accrual, predicted/forecast funding and proportionally split historical estimates remain diagnostic estimates and cannot enter certified settled/net PnL;
971. Hyperliquid standard-perp funding notional uses oracle price where the applicable rule requires it and cannot substitute mark price;
972. deposits, withdrawals, transfers, vault flows, rewards, account-class transfers and similar external/non-trading ledger changes are reconciled separately and cannot create strategy alpha/PnL;
973. borrow interest, financing, liquidation closing cost, withdrawal/transfer fees and other real economic debits cannot disappear merely because they are outside ordinary trade fills;
974. proof-critical mark/unrealized state carries price type, source/event time, receive time and freshness; stale carried-forward marks are diagnostic-only and cannot certify current equity/PnL;
975. mark price, oracle price, midpoint, last trade and executable liquidation/exit price remain distinct accounting/execution semantics and cannot be interchanged for favorable PnL;
976. each cost/rebate component has exactly one accounting location so fill-price-embedded spread/slippage/latency or fees cannot also be subtracted/credited a second time;
977. zero cost is admissible only when point-in-time venue/account/rule evidence proves zero; unknown cost is never represented as zero;
978. final proof cannot rely on open unrealized profit: required positions are fully closed or the result is non-certifiable unless an explicitly certified liquidation-equivalent close model is applied;
979. multi-leg/cross-venue PnL requires all leg fills, partial-fill state, residual inventory, costs and exits; one-filled/one-rejected or asymmetric legs cannot be collapsed into favorable paired PnL;
980. canonical PnL reconciles independently across event ledger, position lifecycle, cash/equity equation, raw/campaign aggregate and published scoreboard within strict deterministic numerical tolerance;
981. any unexplained reconciliation mismatch blocks promotion/certification and cannot be averaged, ignored or absorbed into a broad tolerance;
982. a constant-price round trip with non-zero costs produces exactly negative all-in costs within tolerance, while a zero-cost constant-price round trip produces zero PnL;
983. anti-false-PnL tests cover duplicate fills, duplicate funding, non-trading cash flows, stale marks, partial closes, over-close, requested-vs-filled notional mismatch, sign symmetry, double-counted costs and funding-estimate contamination;
984. final economic certification prefers first-party Hyperliquid fills/funding/non-funding-ledger records and immutable raw evidence over sampled frontend portfolio graphs or convenience PnL fields when they disagree;
985. a positive reported PnL that cannot satisfy the complete anti-false-PnL gate is labeled unverified/invalid and cannot count toward the +4 USD/day target, promotion, scoreboard success or economic proof.
986. malformed or truncated proof-critical accounting records quarantine/fail the affected certification scope and cannot be silently skipped when their omission could change PnL, costs, exposure or trade count;
987. independent certifying PnL reconstruction is derived from raw/typed accounting events and lifecycle state and cannot consume the published/final aggregate PnL field as an input;
988. removing a proof-critical fill, fee, funding or cash-flow event from a controlled accounting fixture must cause FAIL/UNMEASURABLE rather than improve certifiable PnL.
989. the simulation UI/API displays a numeric PnL only when the exact displayed scope has valid canonical accounting status; otherwise it displays an explicit invalid/unmeasurable/reconciliation-failed status and no numeric PnL;
990. no UI/report fallback may substitute zero, cached/last-known PnL, estimated/gross PnL, midpoint markout or another scope's PnL for unavailable canonical net PnL;
991. realized, unrealized, estimated and diagnostic values are structurally and visually distinct, and stale unrealized state cannot appear as current verified PnL;
992. parent/module/portfolio PnL aggregation is deny-by-default when a material child component is invalid or unmeasurable and cannot silently omit unknown unfavorable components;
993. restart, reconnect, replay resume, dataset repair or ledger rebuild suppresses cached numeric PnL until canonical reconciliation completes again, and conflicting UI/report surfaces suppress numeric display for the affected scope.
994. simulation certification targets venue-behavioral/event parity rather than aggregate-PnL similarity, and any material hidden state remains explicit uncertainty instead of a favorable synthetic fill;
995. the existing snapshot-level simulation realism audit is not sufficient for live-readiness and canonical parity additionally covers execution, order lifecycle, latency, queue, rejection, margin, funding, liquidation, restart and action-feasibility semantics;
996. runtime/replay parity is proven on the canonical src/hl_observer execution/accounting path and cannot rely solely on deterministic equality of a legacy simulator;
997. canonical fill price is the raw simulated venue match/VWAP; trading fees, rebates, builder/deployer/priority fees and funding remain separate signed cash-flow events;
998. certifying execution cannot fold trading fees into entry/exit price because doing so changes venue-equivalent entry price, cash timing, margin and liquidation state;
999. adverse selection is post-fill markout/economic outcome and cannot be added to the raw maker fill price;
1000. causal latency changes the market/order state reached by the action and the canonical path proves use of the first admissible execution state at/after simulated arrival time rather than merely zeroing a scalar latency surcharge;
1001. a decision-time book cannot also serve as the latency-adjusted execution book unless the modeled arrival delay is zero and provenance proves the state is valid at that arrival instant;
1002. every actionable paper intent carries venue-native order semantics including TIF/reduce-only/limit/trigger/grouping fields required by the target future Hyperliquid action;
1003. ALO, IOC and GTC residual behavior is simulated distinctly and unsupported venue-native order semantics fail with UNSUPPORTED_SIMULATION_SEMANTICS rather than a generic fill approximation;
1004. resting-order simulation preserves persistent state and causal partial-fill/cancel/modify/trigger transitions across later events rather than resolving every intent in one call;
1005. point-in-time venue pre-validation reproduces relevant tick, lot, minimum-notional, margin, reduce-only, ALO-cross, IOC-no-liquidity, trigger, OI-cap, oracle, max-position, batch and request-validity rejection classes;
1006. an action that would be rejected under the applicable venue rule produces no fill, position mutation or PnL in simulation;
1007. aggressive execution walks side-correct depth at simulated arrival time, preserves level fills, price protection and actual filled quantity, and never uses midpoint as an executable price;
1008. shared displayed/reconstructed liquidity is consumed exactly once across competing paper intents so parallel strategies cannot each receive the same book quantity;
1009. IOC residual quantity is canceled while GTC residual quantity may rest only when the corresponding live order semantics permit it;
1010. maker fills require sufficient causal queue/order-flow evidence and aggregate L2 alone cannot be treated as exact queue position;
1011. unavailable exact maker queue state is QUEUE_STATE_UNOBSERVABLE/bounded uncertainty and favorable assumed queue placement cannot support certified PnL;
1012. cancellations ahead improve simulated queue only under a validated queue-depletion model and are not automatically credited to the paper order;
1013. evidence freshness is strategy/action specific and a compatibility default such as five seconds cannot certify short-horizon execution without a justified consumer threshold;
1014. proof-critical replay preserves exchange/block time, local receive time, monotonic ordering and source identity/sequence and applies deterministic tie-breaking;
1015. point-in-time account/asset fee state drives fees and static 4.5/1.5-bps defaults are compatibility assumptions rather than universal certified truth;
1016. maker rebates and builder/deployer/priority charges remain distinct signed accounting components and cannot be hidden inside slippage or fill price;
1017. unknown material fee tier/multiplier makes exact net PnL unmeasurable unless a preregistered conservative bound is used and explicitly labeled;
1018. certified funding uses actual settlement evidence or exact hourly boundary reconstruction with point-in-time size, oracle price and rule/rate, never continuous prorating as settled truth;
1019. canonical simulation tracks the applicable account mode, collateral, margin tier, cross/isolated state, open-order reservation, maintenance requirement and match-time margin checks rather than substituting local risk caps for venue margin;
1020. liquidation-sensitive simulation uses mark/equity/maintenance-margin state and applicable partial/book/backstop/ADL rules; missing material liquidation semantics block certification;
1021. TP/SL and trigger simulation uses point-in-time mark trigger semantics and preserves market/limit execution uncertainty after activation;
1022. parent-linked TP/SL, Scale, TWAP, Chase and other advanced order behavior are modeled only when used and evidenced; otherwise that live scope is unsupported rather than approximated favorably;
1023. paper action feasibility enforces point-in-time address/IP/action/open-order/batch/congestion constraints when they could change whether or when a future live action is accepted;
1024. a strategy cannot be certified live-feasible if its required action rate, subscription coverage or order count exceeds the target architecture's venue limits;
1025. restart/reconnect restores and reconciles durable order/position/fill/funding state before new affected actions or numeric PnL are trusted;
1026. disappeared local order state is never interpreted as fill/cancel without reconciliation evidence;
1027. multi-leg simulation preserves independent latency, fill, rejection, cost and residual inventory state per leg and never assumes atomicity absent a real mechanism;
1028. one-filled/one-rejected, unequal partial fills and delayed hedge states have explicit emergency/residual economics and cannot be collapsed into intended paired-spread PnL;
1029. parity validation compares discrete order/rejection/state/fill outcomes plus fees, funding, account state and reconciled PnL; aggregate PnL similarity alone does not pass;
1030. real/archival venue ground-truth fixtures are used wherever available to validate order-state and fill behavior under narrowly defined rounding tolerances;
1031. replay, forward paper and future live-intent planning share one canonical execution/accounting engine and strategy modules cannot maintain a more favorable private fill/PnL simulator;
1032. simulation realism status is fail-closed per capability: a missing unsupported feature blocks only scopes that depend on it but those scopes cannot claim live parity;
1033. latency parity tracks signal/data age separately from local processing, outbound/write, mempool/consensus and result-return components and unavailable components remain measured assumptions rather than zero;
1034. current observed Hyperliquid write-latency/order-sequencing figures are versioned empirical inputs and never guaranteed constants;
1035. raw venue-equivalent entry price remains distinct from all-in/effective economic price so dashboard, position state, margin and accounting can reconcile to future venue records;
1036. simulated fee cash flow occurs at the fill event so equity/buying-power evolution reflects venue timing rather than deferring cost until position close;
1037. mark-to-market required for certification cannot fall back to entry price, stale last mark or another convenience price when a current admissible mark/liquidatable price is missing;
1038. maker fill calibration explicitly reports the data resolution used (L2, raw order diffs/order-level, trades) and certification strength cannot exceed that evidence resolution;
1039. deterministic failure drills cover disconnect during open order, partial fill then cancel, modify/fill race, stale book at arrival, rate-limit rejection, margin rejection, funding boundary, trigger gap and liquidation transition;
1040. future real-money readiness remains false while any material execution capability used by the strategy is approximate, unmeasurable, unsupported, unreconciled or not parity-validated;
1041. no signed testnet/mainnet action, API wallet, key or live executor is introduced by this simulation-realism contract; any future scope change requires separate explicit user authorization;
1042. simulation parity tests are included in the 100% branch-coverage scope and may not be excluded as integration-only convenience paths;
1043. a simulator change that improves PnL while reducing venue-parity evidence, rejection realism, cost timing or failure realism is rejected even if backtest metrics improve;
1044. parity scorecards expose at least rejection-match rate, state-transition match, fill/partial-fill match, quantity/VWAP error, fee/funding reconciliation, latency-evidence quality and account-state reconciliation;
1045. final economic proof can count a simulated trade only if every execution/accounting capability that materially affected that trade is certified for the evidence resolution and venue-rule version used.

## Non-goals

This change does not:

- create an Oracle/VPS collector;
- autonomously wake, commandeer, or depend on the user's PC; user-started local Codex/agent sessions may run deterministic development checks locally;
- enable real trading;
- guarantee a 4 USD profit;
- activate candidate research modules or historical research-tranche ideas without scoped evidence gates;
- paper-fill invalid tick/precision/min-notional orders or silently normalize them to a more favorable price;
- trigger TP/SL from BBO/last trade when the applicable rule uses mark price;
- treat self-trade prevention as executed volume or charge a self-trade fee;
- assume every native TWAP fully completes its theoretical schedule;
- use frontend portfolio charts or UI max drawdown as the primary proof ledger for strategy PnL/DD;
- call raw AMM spot or slot0 an executable cross-protocol hedge price without fee/impact/gas modeling;
- call a formula-index residual arbitrage when no executable replicating hedge exists;
- price ADL like an ordinary market order when the protocol rule requires previous-mark execution;
- give backstop-acquired positions privileged ADL treatment absent an explicit protocol rule;
- assume Portfolio Margin eligibility, borrowing headroom or cross-DEX capital efficiency without point-in-time account/cap state;
- treat delisting settlement as an ordinary market exit or permit post-settlement fills;
- collapse public-book liquidation, backstop transfer and ADL into one interchangeable forced-flow event;
- assume cross-DEX margin sharing without account-abstraction and collateral semantics that actually enable it;
- back-apply today's impact notionals, order caps, funding constants, liquidation thresholds, action limits, Chase/TWAP limits or mark/oracle source weights to historical periods without rule evidence;
- treat an allMids last-trade fallback as executable two-sided midpoint;
- assume ALO priority cost occurs only when filled;
- substitute mark price for oracle price in standard funding cash-flow notional when the rule requires oracle;
- treat option mark IV/mark price as executable fills;
- assume positive IV-RV implies profitable short volatility;
- credit Chase with exact maker queue economics when historical repricing/queue evidence is unavailable;
- call API-capped wallet history complete merely because a request returned successfully;
- apply portfolio-margin capital efficiency to a historical/account mode where it was unavailable;
- infer full trigger coverage from a wallet subset;
- assume two outcome markets are equivalent from names alone;
- call an outcome parity trade risk-free without exact settlement-state equivalence;
- mirror the full Hyperliquid raw-node/L4 corpus by default when bounded evidence windows suffice;
- classify a public wallet as a protocol/backstop actor without verified provenance;
- treat all venue books as equivalent visible CLOB liquidity;
- treat RFQ indicative quotes or hidden-liquidity absence as executable truth;
- treat tracked-wallet trigger orders as a complete market-wide stop map;
- infer exact hidden iceberg size from aggregated L2 replenishment alone;
- let portfolio netting erase or rewrite standalone module research results;
- use live minimum-size probe orders to calibrate queue/latency while the project remains paper/read-only;
- treat current fee, priority, oracle or matching rules as timeless historical constants;
- treat public bot code, X posts, stars, APR claims or repository popularity as proof of edge;
- deanonymize public wallets or infer real-world identities from flow-provenance research;
- resurrect previously killed strategies without a materially new preregistered hypothesis;
- remove historical campaign evidence;
- replace existing native venue collectors without a demonstrated need.

Its purpose is to make the existing GitHub architecture operationally simple: collect when instructed, stop cleanly when instructed, then spend compute on evidence generation instead of competing workloads.
