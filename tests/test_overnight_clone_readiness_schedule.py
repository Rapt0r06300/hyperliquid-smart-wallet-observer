"""Nightly GitHub-hosted gates required before a fresh SAFE clone."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_overnight_clone_readiness_runs_all_required_gates_on_hosted_runners():
    schedules = {
        "ci.yml": "cron: '7 19 * * *'",
        "dataset-quality-ci.yml": "cron: '17 19 * * *'",
        "collector-replay-integrity-ci.yml": "cron: '27 19 * * *'",
        "native-venues-github-validation.yml": "cron: '37 19 * * *'",
        "alina-restore-safe-regression.yml": "cron: '47 19 * * *'",
        "durable-restore-drill.yml": "cron: '7 20 * * *'",
    }
    for name, cron in schedules.items():
        source = _workflow(name)
        assert "schedule:" in source, name
        assert cron in source, name
        assert "self-hosted" not in source, name
        assert "runs-on: ubuntu-latest" in source or "runs-on: windows-latest" in source


def test_restore_night_gate_keeps_full_catalog_preflight_and_honest_byte_scope():
    restore = _workflow("alina-restore-safe-regression.yml")
    assert "--replay-ready" in restore
    assert "--preflight-only" in restore
    assert "--max-download-gib 0" in restore
    assert '"full_dataset_certified": False' in restore
    assert "Verify real historical SAFE asset download and SHA-256" in restore
    assert "Verify bounded multi-venue SAFE shards against Release bytes" in restore
    assert "Run deterministic restore tests" in restore


def test_existing_dataset_control_gates_continue_overnight():
    expected = {
        "publish-restore-inventory.yml": 'cron: "17 */6 * * *"',
        "quarantine-audit.yml": 'cron: "37 */2 * * *"',
        "dataset-metrics-v2.yml": "cron: '53 * * * *'",
        "backfill-replay-compatibility.yml": "cron: '12,32,52 * * * *'",
        "catalog-partition-parity.yml": "cron: '7 2 * * *'",
        "recovery-contract.yml": 'cron: "23 3 * * *"',
    }
    for name, cron in expected.items():
        source = _workflow(name)
        assert cron in source, name
        assert "self-hosted" not in source, name
