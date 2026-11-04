from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "platform_responsibility_check.py"


def _module():
    spec = importlib.util.spec_from_file_location("platform_responsibility_check_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_current_platform_has_explicit_responsibility_contract(monkeypatch):
    module = _module()
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "0")
    monkeypatch.setenv("HL_ENABLE_TESTNET_EXECUTION", "0")
    monkeypatch.setenv("REAL_MAINNET_TRADING", "false")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "false")
    report = module.evaluate()
    assert report.platform in {"Linux", "Windows"}
    assert report.runner in {"ubuntu-latest", "windows-latest"}
    assert report.required_commands
    assert report.paper_flags_ok is True
    assert report.python == sys.executable


def test_unknown_platform_fails_closed(monkeypatch):
    module = _module()
    monkeypatch.setattr(module.platform, "system", lambda: "Plan9")
    report = module.evaluate()
    assert report.ok is False
    assert report.runner == "unsupported"
    assert report.required_commands == ()


def test_hosted_mode_requires_github_context(monkeypatch):
    module = _module()
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "0")
    monkeypatch.setenv("HL_ENABLE_TESTNET_EXECUTION", "0")
    monkeypatch.setenv("REAL_MAINNET_TRADING", "false")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "false")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    report = module.evaluate(hosted_required=True)
    assert report.hosted_context_ok is False
    assert report.ok is False


def test_ci_declares_both_platform_responsibilities():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "runs-on: ubuntu-latest" in workflow
    assert "runs-on: windows-latest" in workflow
    assert "platform_responsibility_check.py --hosted --json" in workflow
