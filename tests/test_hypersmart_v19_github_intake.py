from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_tool():
    path = Path("tools/github_fusion_intake.py")
    spec = importlib.util.spec_from_file_location("github_fusion_intake", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_github_fusion_intake_covers_matrix_without_network() -> None:
    tool = _load_tool()
    rows = tool.build_intake(network_read=False)

    assert len(rows) >= 36
    assert all(row.license_status == "network_read_disabled" for row in rows)
    assert all(row.direct_code_copy_policy == "NO_DIRECT_COPY_UNTIL_LICENSE_CHECKED" for row in rows)
    assert any("RiskEngine" in " ".join(row.hyper_smart_targets) or "risk" in " ".join(row.hyper_smart_targets) for row in rows)


def test_github_fusion_intake_markdown_keeps_paper_boundary() -> None:
    tool = _load_tool()
    markdown = tool.format_intake_markdown(tool.build_intake(network_read=False))

    assert "local_paper_only=true" in markdown
    assert "direct_external_execution=false" in markdown
    assert "future_profit_guarantee=false" in markdown
    assert "Rezzecup" in markdown
    assert "freqtrade" in markdown


def test_github_fusion_queue_prioritizes_p0_p1_modules() -> None:
    tool = _load_tool()
    rows = tool.build_intake(network_read=False)
    queue = tool.build_fusion_queue(rows)
    markdown = tool.format_fusion_queue_markdown(queue)

    assert queue
    assert all(item.priority.startswith(("P0", "P1")) for item in queue)
    assert queue[0].queue_rank == 1
    assert "signal -> risque -> PaperEngine -> evidence -> tests" in markdown
    assert "`risk/risk_engine_v3.py`" in markdown or "`wallets/leader_hotness.py`" in markdown
    assert "queue_count=" in markdown
