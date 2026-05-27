from pathlib import Path


def test_single_hypersmart_launcher_exists_and_forces_simulation_mode():
    launcher = Path("LANCER_HYPERSMART.cmd")
    text = launcher.read_text(encoding="utf-8")

    assert launcher.exists()
    assert "start_hypersmart_simulation.ps1" in text
    assert "HL_ENV=paper" in text
    assert "HL_ENABLE_MAINNET_EXECUTION=0" in text
    assert "HL_ENABLE_TESTNET_EXECUTION=0" in text
    assert "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW" in text
    assert "-Port 8792" in text
    assert "-IntervalSeconds 60" in text
    assert "-MaxLeaders 50" in text
    assert "-Interactive" in text
    assert "WindowStyle Hidden" not in text


def test_legacy_program_launchers_removed_to_keep_one_entrypoint():
    assert not Path("LANCER_HYPERSMART_SIMULATION.cmd").exists()
    assert not Path("DEMARRER_SIMULATION_LIVE_1000_USDT.cmd").exists()
    assert not Path("Ouvrir_Command_Center.bat").exists()


def test_start_script_initializes_everything_without_execution():
    text = Path("tools/start_hypersmart_simulation.ps1").read_text(encoding="utf-8")

    assert "python -m hl_observer init-db" in text
    assert "HL_ENABLE_MAINNET_EXECUTION" in text
    assert "HL_ENABLE_TESTNET_EXECUTION" in text
    assert "hypersmart_simulation_poll_loop.ps1" in text
    assert "RestartExisting" in text
    assert "Arret ancien processus HyperSmart" in text
    assert "FreshWindowMinutes" in text
    assert "LeadersPerPoll" in text
    assert "Commande [R=status, Q=stop]" in text
    assert "Stop-HyperSmartRuntime" in text
    assert "Start-Process -NoNewWindow" in text
    assert "Start-Process -WindowStyle Hidden" not in text
    assert "/#simulationPanel" in text
    assert "/exchange" not in text


def test_poll_loop_runs_public_trades_discovery_before_copy_run():
    text = Path("tools/hypersmart_simulation_poll_loop.ps1").read_text(encoding="utf-8")

    assert "live-public-scan" in text
    assert "--network-read" in text
    assert "--store" in text
    assert "copy-run" in text
    assert text.index("live-public-scan") < text.index("copy-run")
    assert "/exchange" not in text
