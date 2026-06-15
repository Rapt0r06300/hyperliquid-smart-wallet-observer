# ChatGPT / GitHub Connector Access Check

Repository: `Rapt0r06300/hyperliquid-smart-wallet-observer`

Purpose: make the repository easier to access from ChatGPT, Codex, and GitHub
connectors without exposing local runtime artifacts.

## Current connector notes

- The repository can be reached through the local `origin` remote.
- The authenticated GitHub account has `ADMIN` permission on the repository.
- The default branch is `main`.
- GitHub Issues are enabled.
- Runtime folders must stay out of Git:
  - `.refact/`
  - `.pytest_tmp*/`
  - `runtime/pytest_tmp_*/`
  - `logs/`
  - `data/`
  - `*.sqlite3`, `*.db`, `*.log`, archives
  - generated `*.egg-info/`

## Why this matters

ChatGPT and GitHub connectors work best when the repository contains only source
code, tests, docs, and reproducible configuration. Local runtime data, pytest
temp outputs, Refact agent state, databases, logs, and generated package metadata
can confuse repository indexing and may expose implementation traces that should
not be public.

## Safety statement

This project remains research/paper-only. Public repository access must not
include secrets, private keys, real trading credentials, runtime databases, or
local logs.
