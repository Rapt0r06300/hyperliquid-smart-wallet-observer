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

## Collector V3 Replay-Grade

The `COLLECT` phase is not a generic data downloader. It is a capture, recovery, certification, and provenance pipeline whose output must be good enough to reconstruct market state without silently inventing missing information.

The primary invariant is:

> maximize replay-grade evidence, detect every detectable loss, repair every loss that an authoritative public source can repair, and quarantine every interval whose integrity cannot be proven.

The architecture does **not** claim that GitHub-hosted runners can guarantee physical zero-loss networking. GitHub runners are ephemeral and bounded. Instead, the system must guarantee **zero silent gaps**: an unrecoverable gap may exist, but it must be explicitly delimited and forbidden to replay engines that require continuity.

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
40. existing relevant campaign, dataset, reconciliation, and collector tests continue to pass.

## Non-goals

This change does not:

- create an Oracle/VPS collector;
- run anything on the user's PC;
- enable real trading;
- guarantee a 4 USD profit;
- remove historical campaign evidence;
- replace existing native venue collectors without a demonstrated need.

Its purpose is to make the existing GitHub architecture operationally simple: collect when instructed, stop cleanly when instructed, then spend compute on evidence generation instead of competing workloads.
