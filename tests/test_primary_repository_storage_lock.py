from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "publish_dataset_v2_release.py"


def _module():
    spec = importlib.util.spec_from_file_location("publish_dataset_v2_release", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dataset_publisher_refuses_foreign_repository_before_io(tmp_path: Path) -> None:
    module = _module()
    with pytest.raises(module.PublishError, match="single active Alina repository"):
        module.publish_bundle(
            tmp_path / "missing-bundle",
            repository="foreign/repository",
            tag="data-v2-test",
            target="main",
            title="test",
        )
