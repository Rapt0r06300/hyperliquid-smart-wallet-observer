#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export GIT_LFS_SKIP_SMUDGE=1
exec python3 tools/sync_alina.py "$@"
