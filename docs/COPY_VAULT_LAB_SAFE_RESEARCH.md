# Copy-Vault lab — AlinaSync SAFE economic research

## Double-click behavior

`LANCER_LAB_QUANT_COPY_VAULT.cmd` (without arguments) now attempts to
convert the **locally restored, unpacked and byte-certified** AlinaSync SAFE
tick envelopes into a Copy-Vault economic workspace, then runs the existing
`tools/run_dataset_economic_campaigns.py --no-start-collection` runner.

This is offline PAPER research: no orders, private keys, collection or
downloads. When SAFE restoration is incomplete or lacks causal fill/L2
evidence the command fails closed with `SAFE_RESEARCH_NO_GO`; **no fixtures
or legacy runtime/data are silently substituted**.

Without an argument, the command uses `safe`: it runs the bounded research
batch and then remains open to detect a new SAFE corpus. This is deliberate
continuous-lab behavior, not an unbounded strategy search. Use `once` when a
single finished run is required:

```cmd
LANCER_LAB_QUANT_COPY_VAULT.cmd once
```

`preflight` performs only the software, freeze and SAFE-boundary checks;
`tests` runs the software test groups; `research` consumes an explicitly
prepared, provenance-bound workspace. The launcher never silently changes
from one mode to another.

## Certified vault inputs (2 tiers) — 2026-11-08

`materialize_safe_workspace` now loads, in addition to the SAFE-cloud corpus, the
**LOCAL tier of the certified vault** (`runtime/coffre_certifie/`, produced by
`Certificateur Coffre Fort.cmd`). `_charger_tier_local` reads `LOCAL_INDEX.json`,
**re-verifies each shard SHA-256** (fail-closed: a tampered shard is ignored), and
merges the certified fills / L2 books / BBO into the in-memory replay inputs, tagged
`provenance_tier="LOCAL"`. Measured on the current corpus: causal fills loaded
`0 → 88,090`, books `50,170 → 433,920`.

**The economic proof stays SAFE-only by design.** LOCAL rows are never given
`quality="SAFE"`: they feed the exploratory TRAIN search but can never be
"economically proven". Every proof layer (signal confirmation, leader evidence,
execution-book evidence) still requires SAFE provenance (`dataset_id` +
`catalog_sha` + `quality="SAFE"` + `replay_compatible`). There is **no fake
certification**: proven profitable backtests require fresh SAFE-cloud data, which the
multi-IP collection lanes feed into the SAFE campaign pipeline.

The input is the AlinaSync-owned directory:

```text
runtime/recovery/full/RESTORE_REPORT.json
runtime/recovery/full/UNPACK_REPORT.json
runtime/recovery/full/SAFE_SHARDS.sqlite3
runtime/recovery/full/usable/shards/<release_tag>/<dataset_id>.jsonl.gz
runtime/recovery/full/usable/unpacked/<release_tag>/<dataset_id>.jsonl
runtime/recovery/full/usable/unpacked/<release_tag>/<dataset_id>.jsonl.alina.json
```

The bridge checks the final catalog SHA on restore, unpack and the active
SQLite registry; exact active shard count; registered compressed stat and
SHA-256; extracted JSONL SHA-256 and byte length; per-frame
`hypersmart.tick.v1` schema, raw payload SHA-256, public read-only
provenance and causal clocks. It decodes the Hyperliquid incremental
`copy_vault_fills`, historical `copy_vault_snapshot`, and `copy_vault_l2`
channels. Historical snapshot fill counts are reported separately from
incremental trade counts.

- WS bootstrap and REST backfill snapshots may supply historical TRAIN research
  rows. They retain their source and snapshot marker and are never eligible as
  forward signals, forward fills, or PnL proof.
- Incremental `copy_vault_fills` retain their observed receive time. Only these
  can qualify as causal forward signals after the strategy's frozen start.
- REST history requests share one read-only `/info` weight budget of 1,080
  units/minute. Each `userFillsByTime` call reserves its maximum 120-unit
  response weight before sending, so concurrent large replies cannot exceed
  the budget. A response cap, malformed fill, timeout, or request-budget
  exhaustion is `PARTIAL`; it is not presented as complete history.
- Each new frozen wallet selection resumes from that wallet's last reconciled,
  durably published same-epoch REST checkpoint. If the gap is older than the
  72-hour repair window, the collector records the uncovered interval and
  advances only the separately marked post-gap cursor after the requested
  window itself is complete. A reached 10,000-fill retention ceiling also
  advances this cursor while recording the recoverable endpoint and the
  remaining gap. The gap stays in the campaign receipt.
- Before lab search, SAFE release tags are matched to committed campaign
  receipts. Missing receipts, partial REST audits, or known gaps set the local
  corpus to incomplete; candidates may remain TRAIN-only and cannot be treated
  as a complete history result.
- Observed L2 must contain at least five valid ordered levels per side,
  non-crossed prices and maximum 1-second receive/exchange lag.
- No missing levels, timestamps, network calls, filled orders or NAV values are
  synthesized.
- Other SAFE families remain untouched and are not claimed to have been
  used by Copy-Vault.

The immutable reconstructed inputs are staged under
`runtime/research_lab/copy_vault_safe/<selection_digest>/` as
`vault_fills.jsonl` (historical snapshots), `vault_fills_live.jsonl`
(incremental fills), and `copy_vault_l2_tape.jsonl`; their output
SHA-256 and each selected source shard identity are recorded in
`runtime/reports/datasets/SELECTION_PROVENANCE.json` inside that workspace.
An identical pre-existing workspace is reused only after checking its output
SHA-256. Existing SAFE bytes are **never moved or deleted**.

The economic campaign consumes the workspace via the repository's existing
multi-source adapter. Its source coverage report and economic output determine
what was actually analyzed; mere SAFE or pytest green status is not a profit
certificate. Lack of required NAV, fundings, forward windows or OOS coverage
remains `NON_MESURABLE` or `NO_GO`, rather than a promised profit.

## Explicit modes

```cmd
LANCER_LAB_QUANT_COPY_VAULT.cmd
LANCER_LAB_QUANT_COPY_VAULT.cmd safe
LANCER_LAB_QUANT_COPY_VAULT.cmd tests
LANCER_LAB_QUANT_COPY_VAULT.cmd preflight
LANCER_LAB_QUANT_COPY_VAULT.cmd research "D:\\verified_FULL_COLD_workspace"
```

`tests` audits the software and its freeze. `preflight` performs a
software-only inspection. `research` consumes a separately prepared
workspace with recognized Copy-Vault files and provenance. None performs real
trading. The SAFE bridge **does not** transform arbitrary market L2 data
into user fills or treat historical fill snapshots as causal or forward proof.

## Exact-hash performance path

The SAFE admission path has two separate phases:

1. it validates the catalog rows, manifests, path boundaries, provenance and
   replay permissions;
2. after the admissible file list is fixed, it recalculates the complete
   SHA-256 of every selected shard in a bounded CPU-only pool.

The default pool is four workers and is controlled by
`ALINA_QUANT_HASH_WORKERS`; the launcher pins it to `4`. The upper bound is
four even if a machine has more cores, so disk contention cannot grow without
limit. A value of `1` is valid for a slow disk or a diagnostic comparison.

This is an I/O scheduling optimization, not a weaker cache: file size,
content and expected catalog SHA are still checked for every shard on every
audit. A one-byte change is therefore still rejected even if file metadata
looks unchanged. Hashing results are consumed in deterministic catalog order,
and a read error remains a rejected SAFE asset.

The measured local run on 5 November 2026 verified `15,256/15,256` shards and
`15,256` recomputed hashes, with `128` strategy trials in the bounded run. It
completed in about `1 min 44 s`, versus about `4 min 48 s` before the bounded
parallel hash path. The search space and trial limit were unchanged. This
measurement is a performance receipt only; the run still reported no economic
proof and remained `PAPER / READ-ONLY`.

The result JSON records `hash_workers=4` and
`hashing_mode=BOUNDED_PARALLEL_EXACT_SHA256`, allowing the performance change
to be audited without trusting a prose estimate. Runtime reports are
append-only outputs; SAFE source shards are not moved, rewritten or deleted.

## Remaining evidence before economic promotion

A successful bridge is input materialization, not strategy selection.
Evidence must still include minimum valid events, cost and capacity
reconciliation, TRAIN-only candidate search, separate VALIDATION/OOS,
forward-paper coverage and explicit economic uncertainty. A positive TRAIN
result alone never authorizes promotion or any real order.
