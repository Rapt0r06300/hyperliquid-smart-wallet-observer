# Alina Smart Flow — Disaster Recovery

## Current supported recovery: clone + GitHub Releases

The user's PC is never an operational dependency of cloud Alina Smart Flow.
For recovery on a fresh machine, use **two stages**:

1. Clone the canonical bot, modules, scripts, and tracked configuration:

   ```bash
git clone https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer.git
cd hyperliquid-smart-wallet-observer
```

2. Run `RESTORE_ALINA.cmd` (Windows) or `bash RESTORE_ALINA.sh` (Linux/macOS)
   with Python 3, enough disk space, and GitHub API access. This downloads
   **all published Release assets in the inventory taken at startup** and
   verifies the expected sizes and SHA-256 digests. Review
   `runtime/recovery/full/RESTORE_REPORT.json` and require the
   command's successful exit status; never treat a partial restore as complete.

The independent paginated Release-assets API is consulted for **every** Release;
the list embedded in the Releases API response is not trusted as complete.
For large repositories, set `GH_TOKEN` or `GITHUB_TOKEN` to a token
with read access if anonymous API rate limits are encountered. A successful
restore is complete only for the **published assets included in its initial
inventory**; cloud collection can publish additional Releases concurrently.
It cannot recover unpublished data, missing GitHub assets or ephemeral
GitHub Actions artifacts that have expired.

**Future optional objective:** make a single Git clone include heavy payload
bytes by mirroring GitHub Releases to LFS. This is **not yet implemented as
a complete mirror**, and must not be advertised as ready. The clone payload
manifest currently contains no Release assets and the LFS-free capacity gate
remains closed (see below).


## Byte-parity definition

"Same bytes" means application payload identity, not equality of the physical
server/client `.git` directory size. Git may repack/compress identical Git
objects differently.

Clone completeness is accepted only when
`tools/check_clone_payload_completeness.py --require-complete` proves:

- every explicit GitHub Release asset id is represented exactly once;
- source asset byte size equals clone manifest byte size;
- source SHA-256, when supplied by GitHub, equals clone SHA-256;
- every current-tree `clone_payload/releases/**` Git blob is a Git LFS pointer;
- the LFS pointer OID equals the payload SHA-256;
- the LFS pointer size equals the payload byte size;
- `source_assets == clone_assets`;
- `source_bytes == clone_bytes`;
- missing, extra and mismatched asset counts are all zero.

## Git clone only: quota and current blocker

A ZIP downloaded with GitHub's "Download ZIP" is NOT the accepted recovery
mechanism. It does not contain historical Git objects and it does not
automatically include arbitrary GitHub Release assets.

GitHub Free and Pro include 10 GiB of Git LFS storage and 10 GiB of LFS
download bandwidth per billing cycle. These allowances are account-wide and
NOT proof of remaining free entitlement. The LFS billing budget must be
verified as zero dollars at the account level before any bulk mirroring,
and the complete source inventory must be smaller than the verified unused
storage and bandwidth headroom. A zero-dollar budget blocks overages,
but it does not magically make a larger clone possible.

The full source byte count can be requested via:

`python tools/check_clone_payload_completeness.py --inventory-source --require-complete`

This command may take a long time with many large Release inventories; it must
report INCOMPLETE until source assets and current LFS pointers match exactly.

The GitHub Releases list can embed a truncated asset list; for any Release
with 30 or more embedded assets the mirror enumerates the separate
paginated Release-assets endpoint. The independent strict completeness audit
re-enumerates the paginated assets endpoint for EVERY Release, even if the
embedded list contains fewer than 30 assets. Missing pages and malformed records
are fatal. An absent API response cannot be interpreted as zero bytes.

**Important:** evidence that still exists only on an unuploaded local machine
cannot be proven to reside in GitHub. It must first be published using the
existing safe local recovery snapshot process; cloud GitHub must never access
or rely on that machine.

### Measured, non-exhaustive capacity preflight — 2026-10-08

A read-only GitHub API sample of the first 50 listed Releases found **467
asset IDs, 467 distinct nonempty SHA-256 digests, and exactly
12,080,885,180 bytes** (11.2512 GiB) of distinct payload content.

This lower bound alone exceeds the **10 GiB LFS storage allowance** available
on GitHub Free and Pro. It does not include older Releases, newly published
assets, other LFS objects or unpublished local-only evidence. Because all
467 digests in this sample are distinct, LFS object deduplication cannot
reduce this sample beneath the Free/Pro allowance.

This is NOT a complete source inventory or a restored-clone proof.
The owner's exact GitHub plan, account-level LFS balance and zero-dollar
billing budget have not been read through the connector. Consequently, no
mass LFS migration is authorized or attempted. The mirror manifest remains the
authority for mirrored bytes, not these sample totals.

## Release-to-LFS migration

`tools/mirror_releases_to_clone_lfs.py` mirrors immutable Release assets into
`clone_payload/` in bounded batches. It is idempotent by GitHub Release asset
id and verifies byte size/SHA-256 before accepting a payload.

`.github/workflows/clone-payload-lfs-mirror.yml` is GitHub-hosted only. It is
cost-gated because Git LFS storage/bandwidth can become billable. Scheduled
automatic mirroring becomes active only when the repository variable
`ALINA_LFS_MIRROR_ENABLED=true` exists. Canonical campaign workers also queue
the mirror after durable collection/analysis publication only under that flag.

The mirror never deletes Releases and never introduces execution/trading.
Both the workflow and the CLI reject all LFS migration while
`ALINA_LFS_ZERO_COST_BUDGET_VERIFIED` is absent or not exactly `true`.
The mirror workflow is disabled unless the repository variable
`ALINA_LFS_ZERO_COST_BUDGET_VERIFIED=true` is explicitly set *after*
independently confirming an account-wide zero-dollar LFS budget and sufficient
unused free allowance. That variable is a safety attestation, not a technical
way to read billing information, and no workflow changes the billing settings.

## Existing Release durability

Dataset V2 collection publication writes a deterministic
`alina-recovery-*` Release before the high-cardinality per-shard uploads.
That capsule contains exact manifests/assets with SHA-256 identities. If later
Release publication is rate-limited, `recover-durable-publication.yml` resumes
from the exact capsule without recollection.

These Releases are the durable source from which the LFS clone payload is built.

## Local Codex data

Cloud Alina never depends on the PC. Important ignored local evidence is first
published with:

```text
BACKUP_LOCAL_ALINA.cmd
```

The local snapshot is resumable, chunked and SHA-256 verified. It covers useful
Git-ignored project evidence while excluding secret-like material, private keys,
`.env`, credentials, seeds/mnemonics and reproducible caches/toolchains/builds.

Large historical files that exceed GitHub/Git-LFS per-file limits are represented
losslessly as bounded chunks plus manifests. Every original content byte remains
represented, although those historical bytes may be stored as chunks rather
than one giant source file.

Once the snapshot chunks exist as Release assets, the same Release-to-LFS mirror
makes those bytes part of the clone-complete payload.

## Accepted restoration contract: clone + verified GitHub Releases

`git clone` followed by `RESTORE_ALINA.cmd` (or `RESTORE_ALINA.sh`)
is the **currently accepted** recovery method. Git LFS mirroring remains an
optional, quota-dependent future enhancement, not a prerequisite.

The restore command reads the current clone's canonical
`catalog/DATA_INDEX.json` and `catalog/DATA_METRICS.json` before downloading.
It fails closed if the metrics do not match the index SHA-256. It materializes
a verified shard to `usable/` only when the immutable Release manifest AND
the current catalog agree on its identity, SHA-256, release tag, SAFE quality
and replay compatibility. Historical SAFE rows revoked by the catalog,
duplicate shard identities and ambiguous ZIP entries do not become usable.
Previously materialized SAFE files no longer expected by the catalog are
preserved under quarantine, never silently treated as still eligible.

The restore report and exit code must show that all assets in the initial
Release inventory were accounted for, verified and classified without failures.
A successful restoration certifies the **published inventory snapshot**,
not future Releases concurrently added by live COLLECT, the quality of
unpublished local files, or economic profitability.

## Hard platform prerequisite

A clone can materialize the real Git LFS payload only if:

1. Git LFS is installed/enabled on the new machine; and
2. the GitHub repository has sufficient LFS storage/bandwidth entitlement.

Without those two platform conditions Git can only obtain LFS pointer files.
The repository must never claim clone-complete while that condition or the
byte-parity audit is unmet.

## Acceptance rule

The accepted two-step recovery is `RESTORE_COMPLETE` only when
`RESTORE_ALINA.cmd` or `RESTORE_ALINA.sh` exits successfully, its
`RESTORE_REPORT.json` lists all inventoried Release assets with no missing,
corrupt, unverified or misclassified rows, and usable shards are bound to
the current SHA-verified canonical catalog. `PARTIAL` and `REJECT` evidence
can remain in quarantine for diagnosis but must never enter the usable set.

The separate, optional single-clone-plus-LFS objective is
`CLONE_COMPLETE` only when:

- `check_clone_payload_completeness.py --require-complete` is green;
- source and clone asset counts are identical;
- source and clone byte totals are identical;
- all LFS OID/size identities are verified;
- fresh-machine clone validation succeeds with Git LFS materialization;
- local-only evidence required for preservation has already been published and
  mirrored;
- no secrets, private keys, signatures, real orders or self-hosted runners are
  introduced.
