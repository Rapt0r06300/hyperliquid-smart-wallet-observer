# Copy-Vault lab: economic research and SAFE data

This document describes the actual code contract, not a claim of economic proof.

## What the double-click launcher does

`LANCER_LAB_QUANT_COPY_VAULT.cmd` (without arguments) runs pytest groups.
Passing tests does not demonstrate a profitable strategy, does not evaluate candidate
parameters, and does not use downloaded AlinaSync shards as economic observations.

The console now prints a read-only AlinaSync status based on:
- `runtime/recovery/full/RESTORE_REPORT.json`
- `runtime/recovery/full/UNPACK_REPORT.json`
- `runtime/recovery/full/SAFE_SHARDS.sqlite3` (the `current_safe_shards` view).

`CERTIFIED_UNPACKED` proves that these receipt identities agree and the
AlinaSync registry contains active shards. It does **not** prove economic
coverage, Copy-Vault event compatibility, or that any campaign consumed a shard.

## Launch economic research on a prepared workspace

```cmd
LANCER_LAB_QUANT_COPY_VAULT.cmd research "D:\\path\\to\\verified_FULL_COLD_workspace"
```

The existing `tools/run_dataset_economic_campaigns.py` is invoked with
`--root ... --no-start-collection`. Its source discovery and economic
coverage report provide consumption evidence. All execution remains PAPER /
read-only. If `SELECTION_PROVENANCE.json` or Copy-Vault source files are
absent, this command returns nonzero rather than silently using test fixtures.

The expected workspace contains
`runtime/reports/datasets/SELECTION_PROVENANCE.json`, plus market/copy
JSONL source files with **recognized** basenames. Consult
`src/hl_observer/datasets/source_discovery.py` for the exact contract.
A manually written placeholder provenance file is **not** sufficient:
actual source provenance, format, integrity, replay eligibility, and coverage
must be checked before treating the results as evidence.

## Remaining incompatibility

AlinaSync restores generic `<dataset_id>.jsonl.gz` files into
`runtime/recovery/full/usable/shards/<release_tag>/` and their extracted
`<dataset_id>.jsonl` counterparts under `usable/unpacked/`. These files are
not automatically mapped to the named Copy-Vault economic source streams such
as `vault_fills.jsonl` and `copy_vault_l2_tape.jsonl`.

Do **not** rename or concatenate those generic shard files into Copy-Vault
streams without verifying raw record schemas, family/venue membership, event
timestamps, causal L2 integrity, duplicates, and the SAFE manifest binding.
The current launcher does not perform this translation. If the only inputs
are downloaded SAFE shards, the missing conversion/validation layer is a
**blocking remaining task** before a real local campaign can start.

A meaningful campaign requires distinct TRAIN / VALIDATION / OOS evaluation,
fees, spread, slippage, funding, delays, replay completeness, and explicit
NO_GO on insufficient history. Never auto-promote a strategy because pytest
passes, because a SAFE shard exists, or because a TRAIN-only result is positive.
