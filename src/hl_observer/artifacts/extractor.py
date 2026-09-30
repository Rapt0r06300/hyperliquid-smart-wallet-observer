"""Artifacts extractor (V12, repo 01 CloddsBot): auto-extract reports/snippets/decisions/backtests.

Pulls structured artifacts out of a run's outputs for the dashboard "Artifacts" panel.
Pure: extracts only what is present; nothing fabricated.
"""

from __future__ import annotations


_KINDS = ("report", "snippet", "decision", "backtest")


def extract_artifacts(run_outputs: dict) -> list[dict]:
    artifacts: list[dict] = []
    for kind in _KINDS:
        for item in run_outputs.get(kind + "s", []) or []:
            artifacts.append({"kind": kind, "title": str(item.get("title", kind)), "ref": item.get("ref")})
    return artifacts


__all__ = ["extract_artifacts"]
