from __future__ import annotations

from pathlib import Path

import pytest

from hl_observer.core.config import CoreConfig, default_core_config


def test_core_config_is_simulation_only(tmp_path):
    cfg = default_core_config(tmp_path)

    assert cfg.runtime_mode.execution_enabled is False
    assert cfg.runtime_mode.orders_allowed is False
    assert cfg.runtime_mode.signatures_allowed is False
    assert cfg.runtime_mode.wallet_connect_allowed is False


def test_core_config_rejects_non_positive_starting_balance():
    with pytest.raises(ValueError, match="default_starting_balance_usdc must be positive"):
        CoreConfig(default_starting_balance_usdc=0).validate()


def test_phase0_foundations_do_not_introduce_real_exchange_calls():
    root = Path("src/hl_observer")
    files = list((root / "core").glob("*.py")) + list((root / "simulation").glob("paper_*.py"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)

    assert '"/exchange"' not in text
    assert "'/exchange'" not in text
    assert "private_key" not in text.lower()
    assert "wallet_connect(" not in text
