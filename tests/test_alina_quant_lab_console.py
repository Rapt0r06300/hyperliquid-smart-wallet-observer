from __future__ import annotations

import copy
import json
from pathlib import Path

from hl_observer.backtesting.copy_vault_v21_frozen import _verified_freeze
from hl_observer.simulation.economic_freeze_registry import parameter_hash
from tools.alina_quant_lab_console import _pytest_counts, assess_physical_freeze

ROOT = Path(__file__).resolve().parents[1]
FREEZE_PATH = ROOT / "runtime" / "codex_research" / "COPY_V21_PHYSICAL_FREEZE.json"


def test_lab_reports_the_existing_over_limit_freeze_without_modifying_it() -> None:
    before = FREEZE_PATH.read_bytes()

    result = assess_physical_freeze(FREEZE_PATH)

    assert result["status"] == "REJECTED"
    assert result["reason"] == "COPY_V21_PAPER_GROSS_EXPOSURE_LIMIT_EXCEEDED"
    assert FREEZE_PATH.read_bytes() == before


def test_lab_recognizes_a_valid_physical_freeze_without_promoting_it(
    tmp_path: Path,
) -> None:
    source = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    payload = copy.deepcopy(source)
    params = payload["freeze"]["parameters"]
    params["core_notional_usd"] = 200.0
    payload["freeze"]["parameters_sha256"] = parameter_hash(params)
    target = tmp_path / "freeze.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = assess_physical_freeze(target)

    assert _verified_freeze(payload)["parameters"]["core_notional_usd"] == 200.0
    assert result["status"] == "VALID_PHYSICAL_FREEZE"
    assert result["core_notional_usd"] == 200.0


def test_lab_extracts_independent_pytest_summary_counts() -> None:
    counts = _pytest_counts("= 7 passed, 2 failed, 1 skipped in 3.2s =")

    assert counts["passed"] == 7
    assert counts["failed"] == 2
    assert counts["skipped"] == 1
    assert counts["errors"] == 0
