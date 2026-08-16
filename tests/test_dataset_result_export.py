from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops.dataset_result_export import export_result


def test_export_result_copie_un_rapport_lisible(tmp_path: Path) -> None:
    project = tmp_path / "project"
    replay = tmp_path / "replay"
    campaign_dir = replay / "runtime" / "reports" / "economic_campaigns"
    campaign_dir.mkdir(parents=True)
    (campaign_dir / "HYPERSMART_ECONOMIC_OBJECTIVE_CAMPAIGN.md").write_text(
        "# Verdict\n\nCopy-Vault test\n", encoding="utf-8"
    )
    (replay / "runtime" / "reports" / "economic_family_scoreboards.json").write_text(
        json.dumps({"families": {"copy_vault": {"net_pnl_usd": 1.23}}}),
        encoding="utf-8",
    )
    (campaign_dir / "copy_vault.json").write_text(
        json.dumps({"family": "copy_vault", "net_pnl_usd": 1.23}),
        encoding="utf-8",
    )

    result = export_result(project, replay)
    assert result["status"] == "OK"
    md = project / "docs" / "research" / "datasets" / "DERNIER_REPLAY_176GO.md"
    js = project / "docs" / "research" / "datasets" / "DERNIER_REPLAY_176GO.json"
    assert md.is_file()
    assert js.is_file()
    assert "PAPER / READ-ONLY" in md.read_text(encoding="utf-8")
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["real_execution"] is False
    assert payload["source_release_id"] == 371149058
    assert payload["family_campaigns"]["copy_vault"]["net_pnl_usd"] == 1.23
