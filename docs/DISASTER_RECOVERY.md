# Alina Smart Flow — Disaster Recovery

## Final contract: clone-complete

The user's PC is never an operational dependency of Alina Smart Flow.

The final recovery contract is stricter than "clone + restore": on a machine
where Git LFS is installed, a normal clone of the single canonical repository
must make every canonical Alina payload byte available locally:

```bash
git lfs install
git clone https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer.git
```

GitHub Release assets cannot themselves be downloaded by Git clone. Therefore
heavy immutable evidence is mirrored into `clone_payload/`, where every payload
file is tracked by Git LFS. Releases remain immutable durability/migration
sources, not the final clone surface.

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

## Transitional compatibility

`RESTORE_ALINA.cmd`, `RESTORE_ALINA.sh` and
`tools/restore_alina.py --everything` remain available while the historical
Release backlog is not yet fully mirrored into Git LFS. They are compatibility
fallbacks only and are not the final acceptance contract.

## Hard platform prerequisite

A clone can materialize the real Git LFS payload only if:

1. Git LFS is installed/enabled on the new machine; and
2. the GitHub repository has sufficient LFS storage/bandwidth entitlement.

Without those two platform conditions Git can only obtain LFS pointer files.
The repository must never claim clone-complete while that condition or the
byte-parity audit is unmet.

## Acceptance rule

Alina disaster recovery is `CLONE_COMPLETE` only when:

- `check_clone_payload_completeness.py --require-complete` is green;
- source and clone asset counts are identical;
- source and clone byte totals are identical;
- all LFS OID/size identities are verified;
- fresh-machine clone validation succeeds with Git LFS materialization;
- local-only evidence required for preservation has already been published and
  mirrored;
- no secrets, private keys, signatures, real orders or self-hosted runners are
  introduced.
