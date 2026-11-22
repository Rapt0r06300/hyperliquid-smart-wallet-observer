#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")" && pwd -P)"
cd "$ROOT"
export GIT_LFS_SKIP_SMUDGE=1
# Direct script execution exposes tools/ as sys.path[0], which makes the
# repository package and src/ unavailable in a fresh clone. Keep this
# launcher self-contained for both its own Python process and subprocesses.
export PYTHONPATH="${ROOT}:${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -m tools.sync_complete_clone "$@"
