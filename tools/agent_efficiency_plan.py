#!/usr/bin/env python3
"""Build a bounded, local-only work plan for a coding task."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hl_observer.agent_tools.efficiency.context_bundle import ContextRequest, compile_context  # noqa: E402
from hl_observer.agent_tools.efficiency.model_routing import route_task  # noqa: E402
from hl_observer.agent_tools.efficiency.repo_index import build_incremental_index  # noqa: E402
from hl_observer.agent_tools.efficiency.telemetry import EfficiencyReceipt  # noqa: E402
from hl_observer.agent_tools.efficiency.test_impact import select_impacted_tests  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--changed", action="append", default=[])
    parser.add_argument("--budget-chars", type=int, default=24_000)
    parser.add_argument("--index", type=Path)
    args = parser.parse_args()

    index_path = args.index or REPO_ROOT / "runtime" / "agent_efficiency" / "repo_index.json"
    index = build_incremental_index(REPO_ROOT, index_path=index_path)
    context = compile_context(
        REPO_ROOT,
        index,
        ContextRequest(task=args.task, changed_files=tuple(args.changed), max_chars=max(1_000, args.budget_chars)),
    )
    impact = select_impacted_tests(REPO_ROOT, args.changed)
    routing = route_task(args.task, args.changed)
    receipt = EfficiencyReceipt(task_id="agent-efficiency-plan")
    receipt.record_context(input_chars=context.estimated_chars, cached=False)
    receipt.tests_run = len(impact.impacted_tests)
    receipt.tests_skipped = 0 if impact.full_suite_required else max(0, len(list(REPO_ROOT.glob("tests/test_*.py"))) - len(impact.impacted_tests))
    payload = {
        "schema": "agent_efficiency_plan.v1",
        "paper_read_only": True,
        "real_execution": False,
        "index": {"path": str(index_path), "fingerprint": index.fingerprint, "records": len(index.records)},
        "routing": routing.to_dict(),
        "context": context.to_dict(),
        "test_impact": impact.to_dict(),
        "receipt": receipt.finalize(),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
