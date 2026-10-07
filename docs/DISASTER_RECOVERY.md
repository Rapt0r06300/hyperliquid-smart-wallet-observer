# Alina Smart Flow — Disaster Recovery

## Contract

The user's PC is never an operational dependency of Alina Smart Flow.

A fresh machine must be able to recover the canonical project from the single
repository:

`Rapt0r06300/hyperliquid-smart-wallet-observer`

Git itself stores code, history, workflows, specs, manifests, catalogs,
checkpoints and small results. Heavy immutable evidence is intentionally stored
as GitHub Release assets because GitHub rejects very large Git blobs and because
raw L2/trade histories would make normal Git operations unusable.

Therefore **plain `git clone` cannot, by Git design, download Release assets**.
The supported full restore is:

```bash
git clone https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer.git
cd hyperliquid-smart-wallet-observer
python tools/restore_alina.py --everything
```

The second command is mandatory for a complete disaster restore.

Convenience launchers are committed at repository root:

- Windows: `RESTORE_ALINA.cmd`
- Linux/macOS: `RESTORE_ALINA.sh`

The restore streams large assets to disk instead of loading them into RAM, checks
free disk space before starting, and verifies hashes before accepting restored
evidence.

## What `restore_alina.py --everything` restores

It enumerates every GitHub Release in the canonical repository and downloads all
assets, including market trades, BBO/L2/order-book evidence, replay inputs,
recovery capsules, analysis/backtest/OOS/forward/scoreboard assets published in
Releases, run manifests/checksums and explicit local runtime snapshots.

Every GitHub-provided SHA-256 digest is checked. Dataset `RUN_MANIFEST.json`
references are checked again against restored files. The command fails closed
when an asset is missing or has the wrong identity.

The latest explicit local snapshot is materialized back into the fresh checkout
under its original ignored runtime paths.

## Protection against GitHub Release rate limits

Every GitHub-hosted Dataset V2 collection publication writes a dedicated,
deterministic `alina-recovery-*` Release **before** the hundreds of individual
shard uploads.

That Recovery Release contains `ALINA_RECOVERY_INDEX.json` and one or more
`ALINA_RECOVERY_BUNDLE.partNNN.tar` assets with exact SHA-256/byte identities.

If a later shard upload hits a GitHub API or secondary rate limit, the exact
collection unit is already durable. The scheduled
`recover-durable-publication.yml` workflow downloads the capsule, verifies it,
and retries canonical per-shard publication without recollecting or fabricating
data. Recovery capsules are retained after canonical publication succeeds.

## Local Codex work and ignored runtime data

Cloud Alina never depends on the PC. If Codex is explicitly used on a local
checkout and creates important ignored runtime evidence (local replays,
backtests, databases, reports or research-lab files), publish it with:

```bash
python tools/publish_local_recovery_snapshot.py
```

On Windows, `BACKUP_LOCAL_ALINA.cmd` runs this snapshot command directly.
Interrupted snapshots keep a small resume state under `runtime/recovery/` and
reuse already uploaded 1 GB chunks only when byte size and SHA-256 match.

The command snapshots the canonical ignored `data/`, `logs/`, `reports/` and `runtime/` roots, and also enumerates every other useful Git-ignored local-only project file
into chunked Release assets. Files larger than one Release asset are split into
1 GB chunks. SQLite files are copied through SQLite's backup API.

Reproducible caches/toolchains/build outputs (virtualenvs, node_modules, build/dist, portable runtimes, editor caches) are excluded. Secret-like paths, private-key material and `.env` files are excluded and must
never be published.

## What cannot be recovered retroactively

A file that existed **only on a PC and was never committed or uploaded to a
GitHub Release before the PC was lost cannot be recovered by GitHub after the
fact**.

For that reason, canonical cloud collectors publish recovery capsules first,
canonical results must be committed or published as Releases, and important
local-only Codex runtime evidence must be snapshotted explicitly.

## Acceptance rule

Alina disaster recovery is healthy only when code/history clones from `main`,
all canonical heavy evidence is present in same-repository Releases, new
collection units have recovery capsules, failed publications resume from exact
capsules, `restore_alina.py --everything` succeeds with zero missing/bad assets,
tests pass, and no private key/trading credential/real-order capability is added.
