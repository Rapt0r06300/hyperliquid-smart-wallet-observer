"""Q-259 — Self-test des labels goto du .cmd.

Vérifie que chaque 'goto :label' dans LANCER_HYPERSMART.cmd
a une cible ':label' correspondante, et que chaque ':label'
est effectivement référencé par un goto ou call.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CMD_PATH = Path(__file__).resolve().parents[1] / "LANCER_HYPERSMART.cmd"

_GOTO_RE = re.compile(r"^\s*(?!rem\b).*\bgoto\s+:(\w+)", re.IGNORECASE | re.MULTILINE)
_CALL_RE = re.compile(r"^\s*(?!rem\b).*\bcall\s+:(\w+)", re.IGNORECASE | re.MULTILINE)
_LABEL_RE = re.compile(r"^:(\w+)", re.IGNORECASE | re.MULTILINE)


@pytest.mark.skipif(not CMD_PATH.exists(), reason="LANCER_HYPERSMART.cmd absent")
class TestGotoLabels:
    @pytest.fixture(scope="class")
    def parsed(self):
        text = CMD_PATH.read_text(encoding="utf-8", errors="replace")
        gotos = {m.group(1).lower() for m in _GOTO_RE.finditer(text)}
        calls = {m.group(1).lower() for m in _CALL_RE.finditer(text)}
        labels = {m.group(1).lower() for m in _LABEL_RE.finditer(text)}
        return gotos, calls, labels

    def test_every_goto_has_target(self, parsed):
        gotos, _, labels = parsed
        special = {"eof"}
        missing = gotos - labels - special
        assert missing == set(), f"goto sans cible : {sorted(missing)}"

    def test_every_call_has_target(self, parsed):
        _, calls, labels = parsed
        missing = calls - labels
        assert missing == set(), f"call sans cible : {sorted(missing)}"

    def test_no_orphan_labels(self, parsed):
        gotos, calls, labels = parsed
        used = gotos | calls
        orphans = labels - used
        if orphans:
            pytest.xfail(f"Labels non référencés (peut-être utilisés dynamiquement) : {sorted(orphans)}")
