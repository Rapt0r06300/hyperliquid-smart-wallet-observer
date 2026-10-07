# Alina clone-complete payload

This directory is the canonical Git-LFS-backed clone payload for heavy immutable
Alina evidence that must be present after a normal clone on a machine with Git
LFS installed.

It mirrors explicit GitHub Release assets without deleting or mutating the
original Releases. Release assets remain the migration/recovery source until the
mirror is complete and independently verified.

Rules:

- every heavy payload file under this directory is tracked by Git LFS;
- `MANIFEST.json` and this README stay in normal Git;
- paths are append-only and identity-bound to the source Release asset id;
- source byte size and SHA-256 are recorded in `MANIFEST.json`;
- no private keys, .env files, credentials, seeds or mnemonics may enter this tree;
- no real trading capability is introduced;
- the mirror worker is GitHub-hosted only.

A normal `git clone` downloads these LFS objects automatically only when Git
LFS is installed and the repository account has sufficient LFS storage/bandwidth.
