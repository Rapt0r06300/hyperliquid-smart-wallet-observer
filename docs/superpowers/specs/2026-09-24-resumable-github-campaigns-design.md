# Resumable GitHub-Hosted Campaigns

Date: 2026-09-24

## Purpose

Long collectors, replays, backtests, and daily module PnL proofs must continue across the GitHub Actions job limit without using a self-hosted runner or a user's computer. Continuation must preserve data provenance and must never turn missing or uncertain evidence into `SAFE`.

This design adds one bounded, idempotent campaign protocol shared by both repositories:

- `Rapt0r06300/hyperliquid-smart-wallet-observer` remains the source of executable code, schemas, replay/backtest logic, and safety policy;
- `Rapt0r06300/alina-smartflow-datasets-v2` remains the canonical Dataset V2 store and owns the GitHub-Hosted campaign control plane;
- every worker runs on `ubuntu-latest` or `windows-latest`; `self-hosted` is forbidden;
- all execution remains paper-only and read-only, with real-order execution disabled.

## Non-goals

- No live orders, exchange withdrawals, key custody, or write-capable trading API.
- No promise that a strategy will earn a fixed daily amount. The system measures net paper PnL honestly.
- No promotion of `PARTIAL`, `UNAVAILABLE`, or `REJECT` data to `SAFE` merely to keep a campaign moving.
- No attempt to resume an exchange WebSocket connection as if it had remained continuous across two runners.
- No unbounded workflow recursion.

## Ownership and trust boundary

The Dataset V2 repository is the orchestration repository. Its controller and worker workflows check out the main repository at a manifest-pinned commit using `persist-credentials: false`. This avoids a cross-repository dispatch token and keeps the Dataset V2 repository as the single durable source of campaign state.

The main repository supplies a campaign library and CLI. It validates state transitions, leases, digests, work-unit results, stop limits, and safety invariants. Dataset workflows may invoke this code but may not weaken its policy.

GitHub Actions artifacts are diagnostic only because they expire. Durable campaign manifests live in Dataset V2 Git history. Large immutable checkpoints and results live in Dataset V2 GitHub Release assets and are referenced by digest from the manifest.

## Campaign kinds

The first version supports:

- `market_collection`
- `copy_vault_collection`
- `official_archive_collection`
- `event_intelligence_collection`
- `replay`
- `backtest`
- `module_pnl_proof`

The PnL proof covers the current modules independently: `copy_vault`, `cross_venue_dislocation`, `arbitrage`, and `lead_lag`. Cross-module profit cannot compensate for a losing module.

## Canonical manifest

Each campaign uses schema `alina.resumable_campaign.v1` and is stored at:

`catalog/campaigns/<campaign_id>.json`

The manifest contains at least:

- identity: `campaign_id`, `kind`, `schema_version`, `created_at`, `updated_at`;
- reproducibility: `code_repo`, `code_sha`, `dataset_repo`, `dataset_generation`, `config_sha256`, `work_plan_sha256`, optional deterministic `seed`;
- state: `status`, `status_reason`, `chunk_index`, `max_chunks`, `max_wall_clock_s`, `expires_at`;
- progress: a typed cursor, completed immutable work-unit IDs, per-unit status and SHA-256, and the next due time;
- lease: `owner_run_id`, random `lease_token_sha256`, `acquired_at`, `expires_at`;
- retry accounting: `attempts`, `consecutive_failures`, `no_progress_count`, and the classified last failure;
- safety: `paper_only: true`, `read_only: true`, `real_execution: false`;
- outputs: release tag, asset names, byte sizes, digests, provenance, and honest quality state;
- audit: originating workflow/run URL, transition history, and parent campaign or dataset generation when applicable.

Valid active states are `PENDING`, `RUNNING`, and `CONTINUATION_REQUIRED`. Terminal states are `COMPLETE`, `FAILED`, `UNAVAILABLE`, `PARTIAL`, and `REJECT`.

Only declared transitions are accepted. A terminal manifest is immutable except for append-only audit metadata. Any schema, digest, ownership, or transition mismatch fails closed.

## Work units and idempotency

A campaign is a deterministic ordered set of bounded work units. A work-unit ID is derived from campaign kind, pinned code/config/data digests, and its source/time/module partition. Repeating an already completed unit is a verified no-op when its digest matches; a different digest for the same ID is `REJECT`.

Collector units are bounded by source, venue, symbol or stream, and a time window. Replay and backtest units are bounded by immutable Dataset V2 shard IDs and configuration. PnL proof units are additionally bounded by module and evaluation window.

Workers checkpoint only at safe work-unit boundaries. They publish the result asset before advancing the manifest cursor. Therefore a crash can leave an unreferenced asset, but cannot record work as complete before the bytes exist and their digest has been verified.

## Controller workflow

Dataset V2 adds `.github/workflows/resumable-campaign-controller.yml` with:

- `schedule` at an off-peak minute plus `workflow_dispatch`;
- GitHub-Hosted `ubuntu-latest` only;
- repository-level concurrency with `cancel-in-progress: false`;
- least-required `actions: write` and `contents: write` permissions;
- a short timeout, because the controller never performs collection or replay work.

The controller reads every active manifest, validates it with the main-repository CLI, and dispatches at most one worker for a campaign whose lease is absent or expired and whose `next_due_at` has passed. Lease acquisition is an optimistic Git update: on a non-fast-forward conflict the controller refetches, revalidates, and either retries safely or skips because another controller won.

Workers never dispatch their successor. The periodic controller is the sole continuation mechanism. This avoids recursive `workflow_run` chaining limits and makes schedule delay harmless: late continuation changes latency, not correctness.

## Worker workflow

Dataset V2 adds `.github/workflows/resumable-campaign-worker.yml`, invoked only through `workflow_dispatch` with `campaign_id`, expected manifest digest, and the lease token. It has:

- `runs-on: ubuntu-latest`;
- `timeout-minutes` below six hours;
- an application soft deadline no later than 315 minutes;
- per-campaign concurrency with `cancel-in-progress: false`;
- pinned third-party actions;
- no self-hosted labels and no dependency on a user's machine.

The worker refetches and validates the manifest, verifies the lease token, checks out the pinned main-repository commit, executes bounded work units, publishes checkpoints/results, and updates the manifest after every completed unit or small batch. Before the soft deadline it closes cleanly as `CONTINUATION_REQUIRED`. If all units pass validation, it records the appropriate terminal state.

A second worker with a stale lease or expected digest exits successfully without doing work. This makes duplicate dispatch safe.

## Start triggers

- Existing market, copy-vault, official-archive, and event-intelligence schedules create or resume a deterministic campaign for their schedule bucket instead of running an untracked long process.
- A replay campaign is created once per new eligible Dataset V2 generation and pinned main/config digest.
- Backtest campaigns can be created manually or by an explicit bounded schedule; continuation is automatic after creation.
- One daily campaign creates four independent `module_pnl_proof` units for the four modules.

Creation is idempotent. The same schedule bucket and configuration cannot create a second logical campaign.

## Collector boundary semantics

The supported venue/source set remains Hyperliquid, Binance, Bybit, OKX, Gate, and Bitget.

Every resumed live collection starts a new `connection_id`. It records receive-wall and monotonic timestamps, per-connection sequences, duplicates, observed gaps, resync attempts, trade reconciliation, instrument metadata, and funding where available. No sequence continuity is invented across workers.

At a worker boundary:

1. the old worker flushes the raw tape and checkpoint;
2. the next worker opens a new connection;
3. it performs the venue's supported snapshot or REST reconciliation;
4. any unverifiable interval remains an explicit gap;
5. quality policy decides `SAFE`, `PARTIAL`, `UNAVAILABLE`, or `REJECT` from evidence.

External unavailability such as an inaccessible archive or venue does not become a retry loop. It is recorded honestly and is retried only by a later, separately due campaign when policy permits.

## Replay, backtest, and PnL proof semantics

Replay and backtest units use immutable input shard IDs, verified SHA-256 digests, deterministic ordering, pinned configuration, and a fixed seed where randomness exists. Merge/finalization occurs only when every required unit is present and verified. A missing or mismatched unit fails closed.

`module_pnl_proof` accepts only `SAFE` inputs. It reports gross PnL, fees, slippage, funding, borrow/financing where applicable, and net PnL for each module. `PARTIAL` inputs may produce a clearly labelled research diagnostic but never a proof result. The four-dollar target is an evaluation threshold, not an asserted outcome.

## Bounded retry policy

Every campaign has hard limits for total chunks, total wall-clock budget, absolute expiry, attempts, consecutive transient failures, and no-progress continuations. The controller will not dispatch beyond any limit.

Only classified transient infrastructure or external-service failures are retryable. Invalid schema, digest mismatch, unsafe execution flags, missing required provenance, data-quality rejection, and non-deterministic output are non-retryable and fail closed. Backoff is persisted in `next_due_at`.

## Security and repository policy

- All workflows are GitHub Hosted.
- `self-hosted` is rejected by policy tests.
- Main-repository checkout does not retain credentials.
- Default workflow permissions are read-only; write permissions are scoped to the controller/worker jobs that update Dataset V2 state or releases.
- Secrets, tokens, headers, and private endpoint material are never written to manifests, artifacts, logs, or raw tape.
- Live execution flags remain disabled and are asserted before work begins.
- Legacy Dataset V1 remains disabled; Dataset V2 is canonical.

## Testing and acceptance

Main-repository tests cover manifest parsing, valid/invalid state transitions, lease acquisition and expiry, stale-worker rejection, idempotent unit completion, checksum conflicts, retry classification, deadlines, and every stop limit.

Dataset-repository tests cover workflow pinning, GitHub-Hosted labels, timeouts, permissions, concurrency, bounded dispatch, existing collector adapters, and the absence of recursive worker dispatch. An integration test simulates: first chunk, clean continuation, second chunk, completion, then duplicate dispatch as a no-op. Another test proves that a quality failure is terminal and is not retried.

Acceptance requires:

- no self-hosted runner reference in an executable job;
- no job timeout at or above the GitHub limit;
- all seven campaign kinds can checkpoint and continue;
- all six current venues remain wired;
- raw tape/replay provenance fields survive continuation;
- Dataset V2 publication and indexing remain valid;
- only evidence-backed results can be `SAFE`;
- all relevant existing CI and new campaign tests pass on GitHub Hosted.

## Rollout

The rollout is fail-closed and incremental:

1. add the protocol library, CLI, schema, and unit tests in the main repository;
2. add controller/worker workflows, manifest storage, and policy tests in Dataset V2;
3. adapt each existing collector schedule without changing its collection or quality logic;
4. enable replay and backtest campaign creation;
5. enable the daily four-module PnL proof;
6. verify one forced two-chunk campaign before allowing longer campaigns;
7. keep existing direct workflows available for manual diagnosis until their adapters are proven, but ensure schedules do not run duplicate collections.

Rollback disables campaign creation and controller dispatch while preserving all manifests and immutable assets. It does not reactivate legacy datasets or self-hosted runners.
