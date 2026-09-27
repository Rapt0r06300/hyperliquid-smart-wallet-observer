

## Work carry-over — unfinished items from the interrupted GitHub Work run

This section is the canonical carry-over from the interrupted Work execution that implemented the resumable GitHub campaign foundation. It records only work that remains materially incomplete after comparing the Work conversation with the current `main` state of the principal repository and Dataset V2. It does not reopen items already implemented.

### 1. Principal Alina repository remains an operator/control-plane entry point

Dataset V2 is the default heavy GitHub-hosted execution and durable-data plane, but it is **not** the only user-facing orchestration surface.

Required invariant:

`operator intent in Alina principal -> canonical campaign protocol -> chosen execution backend -> Dataset V2 evidence -> canonical analysis/accounting`

The principal Alina repository must be able to launch every canonical phase and campaign family itself through one supported operator surface, including at minimum:

- `IDLE`;
- `COLLECT`;
- `ANALYZE`;
- market collection;
- Copy-Vault collection;
- Event Intelligence collection;
- official archive collection;
- replay;
- backtest;
- Copy-Vault / Lead-Lag / Cross-Venue analysis;
- module PnL proof;
- scoreboard/report generation;
- checkpoint/resume.

The principal repository must reuse the same campaign manifests, adapters, hashes, SAFE gates and economic engines as Dataset V2. It must not create a second economic implementation.

Dataset V2 remains the preferred backend for long/heavy GitHub-hosted execution and durable publication. A run initiated from Alina principal may dispatch to Dataset V2, but operator intent and campaign identity remain visible and controllable from Alina.

### 2. Implement the canonical manual phase state machine for real

The current Dataset V2 scheduler still creates collection, replay and periodic economic campaigns from schedules. The canonical manual-phase design is not complete until one durable phase authority exists.

Required durable state:

- `IDLE`;
- `COLLECT`;
- `ANALYZE`;
- monotonically increasing `phase_epoch`;
- source collection epoch/cutoff for every analysis run;
- actor/reason/timestamp of each phase transition;
- schema/version and content digest.

The canonical phase file may live in Dataset V2 or another explicitly chosen control location, but the principal Alina operator surface must be able to mutate it safely. There must be one authority, not independent phase state in both repositories.

### 3. Stop mixed continuous creation once manual phases are authoritative

After the phase state machine is activated:

- `IDLE` creates no heavy work;
- `COLLECT` creates only collection-compatible campaigns;
- `ANALYZE` creates only quality/replay/backtest/PnL/scoreboard work for the frozen source collection epoch;
- scheduled triggers act only as watchdog/recovery mechanisms;
- schedules never create work contrary to the current operator phase.

The existing hourly/six-hourly campaign creation behavior must be migrated rather than silently coexisting with the manual phase controller.

### 4. Add phase/epoch isolation to resumable campaign manifests and workers

The resumable campaign protocol must persist and validate at least:

- creation phase;
- `phase_epoch`;
- `source_collection_epoch` for analysis work;
- collection cutoff;
- immutable code/config/work-plan identity;
- execution backend identity.

Controller selection must exclude stale-epoch work.

Workers must perform a second fail-closed phase/epoch check immediately before claim/execution. A queued worker from an older phase must not start heavy work after the operator changes phase.

A campaign already terminal remains immutable. Historical manifests remain readable but cannot become current merely because their lease expired.

### 5. Implement deterministic COLLECT -> ANALYZE drain semantics

When switching from `COLLECT` to `ANALYZE`:

- stop creation/claim of new collection units immediately;
- allow only already-claimed collection units to finish within their valid leases;
- expire/reconcile abandoned claims deterministically;
- seal/index the resulting collection epoch;
- freeze the eligible SAFE evidence set;
- begin analysis only after the drain/freeze checkpoint is durable.

Unclaimed historical collection backlog must not delay analysis.

### 6. Finish exact-count and global-dedup coverage

Dataset V2 metrics are already materialized, but current coverage is not complete.

As of the verification that created this carry-over:

- `TOTAL_TRADES_COUNT_COVERAGE_COMPLETE = false`;
- at least one trade shard still lacks an exact trade count;
- `TOTAL_UNIQUE_TRADES_COVERAGE_COMPLETE = false`;
- hundreds of trade shards still lack an exact unique-count result.

Completion requires:

- every relevant trade shard to have deterministic exact parsed counts;
- exact duplicate counts with reason/provenance;
- global cross-shard deduplication or an explicitly versioned global-identity pass;
- aggregate totals regenerated only from verified shard facts;
- unknown coverage to remain explicit rather than zero-filled.

A within-shard unique total is not a substitute for global unique-trade truth.

### 7. Complete the SAFE -> replayable -> economic-proof closure

Dataset V2 may contain SAFE shards while final economic proof remains disabled.

The Work mission is not complete until the current generation can demonstrate:

`SAFE evidence -> replay-compatible selection -> deterministic replay -> backtest -> OOS/forward -> module PnL proof -> scoreboard`

with immutable evidence receipts.

A dataset-level `SAFE` status must not imply `proof_of_pnl_allowed=true`. Economic proof becomes allowed only when every mandatory dependency for the exact module/path has a passing receipt.

### 8. Materialize the machine-readable acceptance/gate registry

The spec already defines scoped gate classes and proposes `config/acceptance_criteria.yaml`, but the registry is still absent from the principal repository.

Implement the registry so every blocking criterion has machine-readable:

- stable ID;
- gate class;
- smallest scope;
- applicable phase(s);
- dependencies;
- required evidence artifacts;
- enforcement action;
- failure state/reason code;
- recovery/remediation action;
- waiver policy.

The orchestrator must consume this registry rather than relying only on prose or hard-coded independent gates.

### 9. Prove backend parity and prevent split-brain ownership

Alina principal and Dataset V2 must be two launch surfaces over one protocol, not two authorities.

Required tests:

- same frozen inputs + same code/config/rule/environment hashes produce the same campaign partitioning and economic results regardless of launch surface;
- only one valid lease can own a campaign unit;
- a principal-launched run handed to Dataset V2 preserves the same `campaign_id`, epoch, hashes and checkpoint lineage;
- stale/local and cloud controllers cannot both advance the same campaign;
- backend switching cannot duplicate durable outputs or PnL evidence.

Current ChatGPT/GitHub autonomous operation remains GitHub-hosted only and must never touch the user's PC.

### 10. Produce one end-to-end closure receipt for the interrupted Work mission

Before this carry-over is considered complete, produce one deterministic, inspectable closure run that proves the whole intended chain:

`operator command -> phase transition -> COLLECT -> durable Dataset V2 publication -> exact COUNT -> quality/SAFE -> ANALYZE drain/freeze -> REPLAY -> BACKTEST -> OOS/FORWARD -> per-module PNL_PROOF -> SCOREBOARD -> checkpoint -> forced continuation/resume -> terminal receipt`

The closure receipt must bind:

- principal repository SHA;
- Dataset V2 SHA/generation;
- exact selected shard identities/hashes;
- resolved environment/dependency digest;
- config/rule/cost hashes;
- campaign/phase epochs;
- every stage result;
- final module-level proof status;
- no-real-order / paper-read-only assertions.

A technically successful workflow is insufficient if any mandatory economic evidence remains `UNMEASURABLE`.

### Work carry-over Done Contract

This interrupted Work mission is closed only when all of the following are true:

1. Alina principal can launch the canonical phases and full chain without duplicating business/economic logic.
2. Dataset V2 remains the durable heavy GitHub-hosted execution/data plane.
3. One authoritative `IDLE/COLLECT/ANALYZE` state machine is active.
4. Campaign manifests and workers enforce phase/epoch isolation.
5. COLLECT -> ANALYZE drain/freeze is deterministic and resumable.
6. Exact trade-count coverage is complete for all relevant trade shards.
7. Global unique-trade coverage is complete or explicitly proven with a canonical global dedup pass.
8. SAFE/replayable evidence can flow through the full official economic chain without bypasses.
9. The machine-readable acceptance registry exists and is enforced.
10. Principal/backend parity and single-lease ownership are regression-tested.
11. One end-to-end closure receipt proves checkpoint/resume and the complete economic pipeline.
12. Paper/read-only remains strict and no current-cloud path depends on a user PC or self-hosted runner.

### 11. Close cross-repository publication/checkpoint failure windows

The Work conversation did not finish the exactly-once contract between Dataset V2 Releases and campaign manifests.

Required:

- Release publication and campaign checkpoint are linked by one immutable publication receipt;
- if a Release succeeds but manifest commit/push fails, the next run discovers and adopts the exact matching immutable output instead of recomputing it;
- a manifest cannot claim an output whose Release asset/digest is absent or mismatched;
- proof/evidence tags referenced by certification are immutable; `--clobber` must not silently alter certifying evidence;
- push/rebase conflicts after lease claim or publication preserve lease lineage and cannot apply a work unit twice;
- a reconciliation job/report detects orphan Releases, orphan manifests, digest conflicts and incomplete publications.

A repeated unit after any publication-boundary failure must converge to exactly one durable output and one authoritative completed-unit identity.

### 12. Finish the Work-requested six-state audit of the 120 Event Intelligence/Data Expansion ideas

The current 1→120 registry is structural inventory only. It does not satisfy the Work requirement to determine the real operational state of every idea.

Every idea must carry exactly one of:

- `IMPLEMENTED_AND_WIRED`;
- `IMPLEMENTED_BUT_PARTIAL`;
- `IMPLEMENTED_BUT_NOT_WIRED`;
- `BROKEN`;
- `MISSING`;
- `NOT_APPLICABLE`.

Each row must bind:

- implementation file(s);
- deterministic test(s);
- actual canonical runtime/research caller;
- required Dataset V2 family/source;
- last verified code SHA;
- status reason;
- structural-proof state;
- economic-proof state.

A file that exists and has tests but has no reachable canonical caller is not `IMPLEMENTED_AND_WIRED`.

An idea whose required Dataset V2 evidence is incomplete, unsafe or not replay-compatible is at most `IMPLEMENTED_BUT_PARTIAL` for the affected experiment.

The repository-wide cabling audit must be reconciled with this registry so `TESTE_SEULEMENT` / orphan components cannot silently satisfy a wired claim.

### 13. Complete replay-compatibility backfill rather than only having the mechanism

The replay-compatibility mechanism exists, but Work required actual closure of the eligible population.

Required:

- finish or explicitly scope the remaining replay-compatibility candidate population;
- machine-check that every SAFE shard consumed by official research has `replay_compatible=true` for its declared consumer/schema;
- SAFE promotion uses a real minimal deterministic replay through the actual consumer adapter, not only parser/schema acceptance;
- replay compatibility is versioned per family/consumer, so trade replayability does not imply synchronized-L2 replayability;
- repair/promotion preserves original PARTIAL/REJECTED/QUARANTINED history;
- Dataset health explains why SAFE, replayable and trade-safe populations differ by venue/family.

No official economic run may silently select a shard whose replay contract is unverified.

### 14. Add campaign backlog/stuck-work observability

The Work conversation required a system that can be understood without manually reading hundreds of manifests or raw workflow logs.

Publish one machine-readable/human-readable campaign health view containing at least:

- counts by `PENDING`, `RUNNING`, `CONTINUATION_REQUIRED`, terminal status and campaign kind;
- oldest pending age;
- active lease owner/age/expiry;
- attempts, no-progress count and consecutive failures;
- backlog size by kind;
- last durable output/checkpoint;
- current blocking reason;
- current phase/epoch and execution backend.

A campaign remaining `PENDING` with zero attempts beyond the declared controller SLO must become an explicit alert/reason, not look healthy.

### 15. Prove catch-up, timeout margin and concurrency semantics

GitHub Actions scheduling is a recovery mechanism, not a correctness primitive.

Required tests/proofs:

- missed or delayed scheduled controller invocations catch up from durable state without duplicate campaigns;
- cron timing is never used as economic/causal time;
- every heavy unit reaches its soft deadline early enough to publish durable data/evidence and checkpoint before the platform job limit;
- concurrency groups cannot silently cancel or replace the only pending work representing an operator phase transition;
- recovery after a completely missed controller interval depends only on phase/campaign/output state, never on RAM or a permanent process;
- current authoritative workflows enumerate their runner labels and prove no dependency on preserved self-hosted/user-PC workflows.

### 16. Demonstrate a forced two-segment resume and failure matrix

The Work mission explicitly required resumability to be demonstrated, not only unit-tested.

Required closure tests:

- force a first GitHub-hosted unit to stop after producing a durable checkpoint but before campaign completion;
- start a fresh runner and resume from that checkpoint;
- prove no recollection/recount/republication of already completed units;
- compare uninterrupted versus interrupted/resumed execution and require identical deterministic semantic result digests;
- inject bounded failures after collection publication, during quality, during replay, during backtest, after evidence Release publication and before manifest checkpoint;
- every failure point must converge to the same final authoritative identity as the uninterrupted run.

### 17. Bind OOS/forward and scoreboard to immutable proof identity

The Work chain is not complete if backtest, OOS/forward and scoreboard can drift apart.

Required:

- TRAIN/selection, OOS and forward partitions cannot overlap;
- OOS/forward bind the same frozen code/config/data/environment/cost/clock identities;
- Copy-Vault, Lead-Lag and Cross-Venue keep separate economic verdicts;
- generic `arbitrage` cannot double-count Cross-Venue economics;
- scoreboard outputs reference exact dataset manifest, canonical ledger/PnL receipt and all required proof hashes;
- missing fee/slippage/funding/latency/capacity evidence remains `UNMEASURABLE`;
- the +4 USD research milestone is evaluated on complete eligible UTC days including zero-trade days, never only active/profitable days.

### 18. Produce the final Work closure report from repository evidence

The interrupted Work mission is not closed until one generated report contains:

- principal Alina HEAD and Dataset V2 HEAD;
- exact code/tree SHAs used by the demonstrated campaign;
- current phase/epoch and execution backend;
- six-state status of all 120 Event Intelligence/Data Expansion ideas;
- exact raw trades, globally unique trades, SAFE trades and replayable trades with completeness flags;
- record/shard counts by family and venue;
- SAFE/PARTIAL/REJECTED/QUARANTINED counts;
- replay-compatibility coverage and remaining unverified population;
- one real SAFE replay-smoke receipt;
- Copy-Vault, Lead-Lag and Cross-Venue OOS/forward/economic status separately;
- forced checkpoint/resume proof;
- scoreboard/proof artifact identities;
- campaign backlog/stuck-work state;
- confirmation that current cloud execution is GitHub-hosted only and paper/read-only;
- every remaining external blocker with a machine-readable reason.

### Additional Work carry-over Done Contract

In addition to the existing Done Contract above, Work recovery is not complete until:

13. Release publication and campaign checkpoint have tested exactly-once recovery across failure boundaries.
14. Every Event Intelligence/Data Expansion idea 1→120 has the six-state wiring classification with concrete evidence.
15. Replay-compatibility coverage is complete or every unverified remainder is explicitly excluded from official research.
16. Campaign backlog/stuck-work state is visible from one canonical health report.
17. Controller catch-up, timeout margin and concurrency semantics are demonstrated under GitHub-hosted execution.
18. A forced fresh-runner continuation and interruption matrix prove real checkpoint/resume behavior.
19. OOS/forward/scoreboard are bound to immutable proof identity and separate module verdicts.
20. The final Work closure report is generated from repository evidence rather than manual claims.

