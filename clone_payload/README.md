# Retired Git LFS recovery mirror (compatibility only)

Alina disaster recovery no longer uses Git LFS. The canonical source is
`Rapt0r06300/hyperliquid-smart-wallet-observer`, branch `main`:
the bot and catalog are Git-tracked, while all durable large collection
and research assets are published in GitHub Releases of the **same repository**.

A regular `git clone` cannot download Release assets. After cloning,
run `Alina-restore.cmd --recover-verifiable` on Windows or
`bash RESTORE_ALINA.sh --recover-verifiable` on Unix. For *previously*
published local-only files, add `--materialize-local-snapshot`.
The restore checks each asset size and SHA-256 and returns nonzero when any
asset is absent or unverifiable; `RESTORE_COMPLETE` is the sole success
certificate for the inventoried published bytes and current SAFE catalog.

`MANIFEST.json` is a legacy manifest and is **not** an authority for the
completeness of GitHub Releases. No migration, scheduled mirroring, new LFS
objects, LFS upload or billing authorization is required or permitted by
the active recovery workflow. Do not mistake a clone or this folder for a
byte-complete archive.

See `docs/DISASTER_RECOVERY.md` for current rules and limitations.
