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
54. existing relevant campaign, dataset, reconciliation, and collector tests continue to pass.

## Non-goals

This change does not:

- create an Oracle/VPS collector;
- run anything on the user's PC;
- enable real trading;
- guarantee a 4 USD profit;
- remove historical campaign evidence;
- replace existing native venue collectors without a demonstrated need.

Its purpose is to make the existing GitHub architecture operationally simple: collect when instructed, stop cleanly when instructed, then spend compute on evidence generation instead of competing workloads.
