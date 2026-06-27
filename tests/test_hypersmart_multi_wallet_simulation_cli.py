import os
import subprocess
import sys


def test_cli_multi_wallet_simulation_runs_without_network_or_execution(tmp_path):
    wallet = "0x" + "e" * 40
    env = os.environ.copy()
    env["HYPERSMART_DATABASE_PATH"] = str(tmp_path / "cli.sqlite3")
    env["HYPERSMART_REPORTS_DIR"] = str(tmp_path / "reports")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hyper_smart_observer.app.main",
            "--simulate-copy-wallet",
            wallet,
            "--simulation-max-wallets",
            "5",
        ],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "multi-wallet follow simulation" in result.stdout.lower()
    assert "no order" in result.stdout.lower()
    assert "wallets requested: 1" in result.stdout
    assert "wallets simulated: 0" in result.stdout
