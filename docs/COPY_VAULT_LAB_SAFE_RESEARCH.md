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
provenance and causal clocks. It decodes only the Hyperliquid
`copy_vault_fills` and `copy_vault_l2` channels.

- WS userFills snapshots are excluded (historical acknowledgements must not
  become future-known signals).
- Observed L2 must contain at least five valid ordered levels per side,
  non-crossed prices and maximum 1-second receive/exchange lag.
- No missing levels, timestamps, network calls, filled orders or NAV values are
  synthesized.
- Other SAFE families remain untouched and are not claimed to have been
  used by Copy-Vault.

The immutable reconstructed inputs are staged under
`runtime/research_lab/copy_vault_safe/<selection_digest>/` as
`vault_fills_live.jsonl` and `copy_vault_l2_tape.jsonl`; their output
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
into user fills or assume historical fill snapshots are causal.

## Remaining evidence before economic promotion

A successful bridge is input materialization, not strategy selection.
Evidence must still include minimum valid events, cost and capacity
reconciliation, TRAIN-only candidate search, separate VALIDATION/OOS,
forward-paper coverage and explicit economic uncertainty. A positive TRAIN
result alone never authorizes promotion or any real order.
