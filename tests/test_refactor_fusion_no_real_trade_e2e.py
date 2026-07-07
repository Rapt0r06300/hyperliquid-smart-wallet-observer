from pathlib import Path
from typing import Any

from hl_observer.refactor_fusion.runner import format_refactor_fusion_run, run_refactor_fusion


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_refactor_fusion_run_writes_payloads_and_never_real_trade(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs a envoyer"
    data_dir = tmp_path / "data_reports"
    docs_dir = tmp_path / "docs_reports"
    logs_dir.mkdir()

    result = run_refactor_fusion(
        log_dir=logs_dir,
        dry_run=True,
        output_data_dir=data_dir,
        output_docs_dir=docs_dir,
    )

    assert result.json_path.exists()
    assert result.dashboard_payload_path.exists()
    assert result.markdown_path.exists()
    assert result.paper_intents_count >= 1
    assert result.arbitrage_accepted_count >= 1
    assert result.dashboard_payload["safety_status"]["real_execution"] is False
    assert "fixture:refactor_fusion_wallet_copy_e2e" in result.dashboard_payload["source_labels"]
    assert "fixture:fusion_runtime" in result.dashboard_payload["source_labels"]
    fusion_panel = result.dashboard_payload["extra_panels"]["fusion_runtime"]
    assert len(fusion_panel["paper_orders"]) >= 1
    assert fusion_panel["real_execution"] is False
    formatted = format_refactor_fusion_run(result)
    assert "fusion_runtime_orders=" in formatted
    assert "fusion_paper_engine_accepted=" in formatted

    for node in _walk(result.dashboard_payload):
        if "real_execution" in node:
            assert node["real_execution"] is False
        if "external_action" in node:
            assert node["external_action"] is False
        if "external_order" in node:
            assert node["external_order"] is False
        assert node.get("private_key") is not True
        assert node.get("signature") is not True


def test_refactor_fusion_run_refuses_non_dry_run(tmp_path: Path) -> None:
    try:
        run_refactor_fusion(log_dir=tmp_path, dry_run=False)
    except ValueError as exc:
        assert "dry-run" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("non dry-run fusion must be refused")
