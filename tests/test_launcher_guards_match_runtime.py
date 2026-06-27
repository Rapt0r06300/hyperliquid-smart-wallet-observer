"""Section 8: launcher safety guards match the runtime deny-by-default posture."""

from __future__ import annotations

from pathlib import Path

from hyper_smart_observer.app.config import AppConfig

ROOT = Path(__file__).resolve().parents[1]


def test_launcher_cmd_declares_simulation_guards():
    cmd = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="ignore")
    required = [
        "HL_ENABLE_MAINNET_EXECUTION=0",
        "HL_ENABLE_TESTNET_EXECUTION=0",
        "HYPERSMART_MODE=SIMULATION_ONLY_UNTIL_MANUAL_REVIEW",
        "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=15000",
        "HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY=1",
        "HYPERSMART_SIMULATION_MIN_EDGE_BPS=15",
        "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE=0.22",
        "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS=40",
        "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS=28",
        "HYPERSMART_V12_GATE_AUTHORITATIVE=1",
        "HYPERSMART_V14_CONSENSUS_WINDOW_AUTHORITATIVE=1",
        "HYPERSMART_V14_EXEC_COST_AUTHORITATIVE=1",
        "HYPERSMART_MAX_POSITION_USDT=40",
        "HYPERSMART_MAX_TOTAL_EXPOSURE_USDT=1200",
        "HYPERSMART_MAX_OPEN_POSITIONS=60",
    ]
    for line in required:
        assert line in cmd, f"launcher missing guard: {line}"


def test_start_script_keeps_same_runtime_guards_as_launcher():
    ps1 = (ROOT / "tools" / "start_hypersmart_simulation.ps1").read_text(
        encoding="utf-8", errors="ignore"
    )
    required = [
        'Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE" "0.22"',
        'Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS" "40"',
        'Set-HyperSmartDefaultEnv "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS" "28"',
        'Set-HyperSmartDefaultEnv "HYPERSMART_V12_GATE_AUTHORITATIVE" "1"',
        'Set-HyperSmartDefaultEnv "HYPERSMART_V14_CONSENSUS_WINDOW_AUTHORITATIVE" "1"',
        'Set-HyperSmartDefaultEnv "HYPERSMART_V14_EXEC_COST_AUTHORITATIVE" "1"',
        'Set-HyperSmartDefaultEnv "HYPERSMART_MAX_POSITION_USDT" "40"',
        'Set-HyperSmartDefaultEnv "HYPERSMART_MAX_TOTAL_EXPOSURE_USDT" "1200"',
        'Set-HyperSmartDefaultEnv "HYPERSMART_MAX_OPEN_POSITIONS" "60"',
    ]
    for line in required:
        assert line in ps1, f"start script overwrites launcher guard: {line}"


def test_runtime_config_defaults_are_deny_by_default():
    cfg = AppConfig()
    # the launcher disables mainnet/testnet execution; the runtime must agree by default
    assert cfg.allow_mainnet is False
    assert cfg.execution_enabled is False
    assert cfg.testnet_execution_enabled is False
