"""Durable collection publish shell must parse before GitHub workers run."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_github_worker_durable_publish_heredoc_and_bash_syntax():
    workflow = (ROOT / ".github" / "workflows" / "resumable-campaign-worker.yml").read_text(
        encoding="utf-8"
    )
    prefix = "        name: Persist collection data or analysis evidence"
    start = workflow.index(prefix)
    content = workflow[start:]
    run_start = content.index("        run: |\n") + len("        run: |\n")
    run_end = content.index("      - name: Record immutable publication receipt")
    raw_lines = content[run_start:run_end].splitlines()
    # YAML literal block strips precisely ten indentation spaces.
    assert all(not line.strip() or line.startswith("          ") for line in raw_lines)
    shell = "\n".join(line[10:] if line.strip() else "" for line in raw_lines) + "\n"
    assert """python - "$BUNDLE/RUN_MANIFEST.json" <<'PY'""" in shell
    assert "\nPY\n" in shell
    assert "NON_SAFE_PAYLOAD_IN_RUN_MANIFEST" in shell
    assert "SAFE_ONLY_PUBLICATION_OK" in shell
    if shutil.which("bash") is None:
        pytest.skip("bash unavailable: Windows developer machine")
    check = subprocess.run(["bash", "-n"], input=shell, capture_output=True, text=True)
    assert check.returncode == 0, check.stderr
