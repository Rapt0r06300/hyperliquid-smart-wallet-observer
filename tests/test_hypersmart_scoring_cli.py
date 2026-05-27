import os
import subprocess
import sys


def _run_cli(tmp_path, *args):
    env = os.environ.copy()
    env["HYPERSMART_DATABASE_PATH"] = str(tmp_path / "cli.sqlite3")
    return subprocess.run(
        [sys.executable, "-m", "hyper_smart_observer.app.main", *args],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_hypersmart_cli_score_wallet_works_with_temp_db(tmp_path):
    wallet = "0x" + "a" * 40
    result = _run_cli(tmp_path, "--score-wallet", wallet)

    assert result.returncode == 0
    assert "Wallet scoring report" in result.stdout
    assert "research only, not a trading signal" in result.stdout
    assert "NO_LOCAL_FILLS" in result.stdout


def test_hypersmart_cli_list_wallet_scores_works(tmp_path):
    result = _run_cli(tmp_path, "--list-wallet-scores")

    assert result.returncode == 0
    assert "Stored wallet scores" in result.stdout


def test_hypersmart_cli_list_rejected_scores_works(tmp_path):
    wallet = "0x" + "b" * 40
    first = _run_cli(tmp_path, "--score-wallet", wallet)
    second = _run_cli(tmp_path, "--list-rejected-scores")

    assert first.returncode == 0
    assert second.returncode == 0
    assert "INSUFFICIENT_DATA" in second.stdout
