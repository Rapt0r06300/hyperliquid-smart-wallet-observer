from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "LANCER_HYPERSMART.cmd"
SILENT_RUNNER = ROOT / "tools" / "run_verify_oos_silent.vbs"


def test_normal_launcher_does_not_install_scheduled_oos_task() -> None:
    text = LAUNCHER.read_text(encoding="utf-8", errors="replace")
    normal_startup = text.split(":cmd_verifoos", maxsplit=1)[0]

    assert 'schtasks /Create /SC MINUTE /MO 30 /TN "HyperSmart_VerifOOS"' not in normal_startup
    assert "verificateur OOS planifie est strictement opt-in" in normal_startup


def test_explicit_oos_install_uses_hidden_runner() -> None:
    launcher = LAUNCHER.read_text(encoding="utf-8", errors="replace")
    runner = SILENT_RUNNER.read_text(encoding="utf-8", errors="replace")

    assert SILENT_RUNNER.is_file()
    assert "run_verify_oos_silent.vbs" in launcher
    assert 'shell.Run(command, 0, True)' in runner
    assert 'LANCER_HYPERSMART.cmd"" verify-oos run' in runner
