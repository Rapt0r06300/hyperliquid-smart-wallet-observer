from pathlib import Path

import pytest

from hl_observer.refactor_fusion.runner import run_refactor_fusion


def test_legacy_fusion_dashboard_runner_is_disabled_by_scope(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    data_dir = tmp_path / "data_reports"
    docs_dir = tmp_path / "docs_reports"
    logs_dir.mkdir()

    with pytest.raises(ValueError, match="DISABLED_BY_SCOPE"):
        run_refactor_fusion(
            log_dir=logs_dir,
            dry_run=True,
            output_data_dir=data_dir,
            output_docs_dir=docs_dir,
        )

    assert not data_dir.exists()
    assert not docs_dir.exists()
