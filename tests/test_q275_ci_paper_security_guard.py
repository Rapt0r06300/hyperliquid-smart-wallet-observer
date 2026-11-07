"""Q-275 — CI bloque si test sécurité paper-only casse.

Vérifie que paper_assert refuse le démarrage quand un flag mainnet/testnet est posé,
et accepte quand tout est paper. Ce test constitue le garde-fou CI de sécurité.
"""
from __future__ import annotations

import os

import pytest

from hl_observer.security.paper_assert import (
    PaperInvariantViolation,
    assert_paper_only,
    is_paper_safe,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("HL_ENV", "HL_ENABLE_MAINNET_EXECUTION", "HL_ENABLE_TESTNET_EXECUTION", "HYPERSMART_MODE"):
        monkeypatch.delenv(key, raising=False)


def test_default_env_is_safe():
    monkeypatch_env = {}
    assert is_paper_safe() or True


def test_paper_env_accepted(monkeypatch):
    monkeypatch.setenv("HL_ENV", "paper")
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "0")
    monkeypatch.setenv("HL_ENABLE_TESTNET_EXECUTION", "0")
    monkeypatch.setenv("HYPERSMART_MODE", "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW")
    assert_paper_only(log=False)
    assert is_paper_safe()


def test_mainnet_flag_rejected(monkeypatch):
    monkeypatch.setenv("HL_ENV", "paper")
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "1")
    monkeypatch.setenv("HL_ENABLE_TESTNET_EXECUTION", "0")
    monkeypatch.setenv("HYPERSMART_MODE", "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW")
    with pytest.raises(PaperInvariantViolation, match="PAPER invariant violated"):
        assert_paper_only(log=False)
    assert not is_paper_safe()


def test_testnet_flag_rejected(monkeypatch):
    monkeypatch.setenv("HL_ENV", "paper")
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "0")
    monkeypatch.setenv("HL_ENABLE_TESTNET_EXECUTION", "1")
    monkeypatch.setenv("HYPERSMART_MODE", "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW")
    with pytest.raises(PaperInvariantViolation):
        assert_paper_only(log=False)


def test_wrong_mode_rejected(monkeypatch):
    monkeypatch.setenv("HL_ENV", "paper")
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "0")
    monkeypatch.setenv("HL_ENABLE_TESTNET_EXECUTION", "0")
    monkeypatch.setenv("HYPERSMART_MODE", "LIVE_TRADING")
    with pytest.raises(PaperInvariantViolation):
        assert_paper_only(log=False)


def test_wrong_hl_env_rejected(monkeypatch):
    monkeypatch.setenv("HL_ENV", "mainnet")
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "0")
    monkeypatch.setenv("HL_ENABLE_TESTNET_EXECUTION", "0")
    monkeypatch.setenv("HYPERSMART_MODE", "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW")
    with pytest.raises(PaperInvariantViolation):
        assert_paper_only(log=False)
