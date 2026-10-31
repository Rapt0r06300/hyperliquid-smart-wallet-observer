"""Exercise canonical-main publication under concurrent GitHub-style writers."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from tools.audit_main_state_writers import render

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "tools" / "publish_main_commit.py"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _repo_pair(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(seed)], check=True, capture_output=True)
    _git(seed, "config", "user.name", "state-writer-test")
    _git(seed, "config", "user.email", "state-writer-test@example.invalid")
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "base")
    _git(seed, "push", "origin", "HEAD:refs/heads/main")
    return remote, seed


def _writer(tmp_path: Path, remote: Path, name: str, *, path: str, body: str) -> Path:
    repo = tmp_path / name
    subprocess.run(["git", "clone", str(remote), str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.name", name)
    _git(repo, "config", "user.email", f"{name}@example.invalid")
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-m", f"state update {name}")
    return repo


def _publish_process(
    repo: Path,
    start: threading.Barrier | None = None,
    *,
    github_context: bool = False,
) -> subprocess.Popen[str]:
    if start is not None:
        start.wait(timeout=20)
    env = dict(os.environ)
    env.pop("GITHUB_RUN_ID", None)
    env.pop("GITHUB_RUN_ATTEMPT", None)
    env.pop("GITHUB_JOB", None)
    env.pop("GITHUB_SHA", None)
    if github_context:
        env.update(
            GITHUB_RUN_ID="run-123",
            GITHUB_RUN_ATTEMPT="2",
            GITHUB_JOB="publish-state",
            GITHUB_SHA="event-sha-456",
        )
    return subprocess.Popen(
        [
            sys.executable,
            str(PUBLISHER),
            "--max-attempts",
            "60",
            "--base-delay-seconds",
            "0.01",
            "--max-delay-seconds",
            "0.08",
        ],
        cwd=repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_parallel_campaign_writers_preserve_every_manifest_and_receipt(tmp_path: Path) -> None:
    remote, seed = _repo_pair(tmp_path)
    base_sha = _git(seed, "rev-parse", "HEAD")
    count = 12
    repos = []
    for i in range(count):
        campaign_id = f"copy-vault-campaign-{i:02d}"
        repos.append(
            _writer(
                tmp_path,
                remote,
                f"worker-{i:02d}",
                path=f"catalog/campaigns/{campaign_id}.json",
                body=json.dumps({"campaign_id": campaign_id, "status": "RUNNING"}) + "\n",
            )
        )
        receipt = repos[-1] / "catalog" / "receipts" / f"{campaign_id}.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({"campaign_id": campaign_id, "accepted": True}) + "\n", encoding="utf-8")
        _git(repos[-1], "add", f"catalog/receipts/{campaign_id}.json")
        _git(repos[-1], "commit", "--amend", "--no-edit")

    # Concurrent operator/control-plane trigger shares the same canonical main.
    trigger_repo = _writer(
        tmp_path,
        remote,
        "operator-trigger",
        path="control/phase-receipts/request-0001.json",
        body=json.dumps({"request_id": "0001", "accepted": True}) + "\n",
    )
    trigger_state = trigger_repo / "catalog" / "operator-dispatches" / "0001.json"
    trigger_state.parent.mkdir(parents=True, exist_ok=True)
    trigger_state.write_text('{"state":"DISPATCHED"}\n', encoding="utf-8")
    _git(trigger_repo, "add", "catalog/operator-dispatches/0001.json")
    _git(trigger_repo, "commit", "--amend", "--no-edit")

    all_repos = [*repos, trigger_repo]
    barrier = threading.Barrier(len(all_repos))
    processes: list[subprocess.Popen[str]] = []
    processes_lock = threading.Lock()

    def start_writer(repo: Path) -> None:
        process = _publish_process(repo, barrier)
        with processes_lock:
            processes.append(process)

    threads = [threading.Thread(target=start_writer, args=(repo,)) for repo in all_repos]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=25)
        assert not thread.is_alive(), "writer start barrier did not release"
    results = [process.communicate(timeout=60) + (process.returncode,) for process in processes]
    failures = [result for result in results if result[2] != 0]
    assert not failures, failures

    verifier = tmp_path / "verify"
    subprocess.run(["git", "clone", str(remote), str(verifier)], check=True, capture_output=True)
    for i in range(count):
        campaign_id = f"copy-vault-campaign-{i:02d}"
        manifest = json.loads((verifier / "catalog" / "campaigns" / f"{campaign_id}.json").read_text(encoding="utf-8"))
        receipt = json.loads((verifier / "catalog" / "receipts" / f"{campaign_id}.json").read_text(encoding="utf-8"))
        assert manifest == {"campaign_id": campaign_id, "status": "RUNNING"}
        assert receipt == {"campaign_id": campaign_id, "accepted": True}
    assert json.loads((verifier / "control/phase-receipts/request-0001.json").read_text(encoding="utf-8")) == {
        "request_id": "0001",
        "accepted": True,
    }
    assert json.loads((verifier / "catalog/operator-dispatches/0001.json").read_text(encoding="utf-8")) == {
        "state": "DISPATCHED",
    }
    assert _git(verifier, "rev-list", "--count", "origin/main") == str(count + 2)
    assert _git(verifier, "merge-base", "--is-ancestor", base_sha, "origin/main") == ""
    assert "--force" not in PUBLISHER.read_text(encoding="utf-8")


def test_overlapping_manifest_conflict_fails_closed_and_keeps_remote_history(tmp_path: Path) -> None:
    remote, seed = _repo_pair(tmp_path)
    manifest = seed / "catalog" / "campaigns" / "same.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"status":"PENDING"}\n', encoding="utf-8")
    _git(seed, "add", "catalog/campaigns/same.json")
    _git(seed, "commit", "-m", "create campaign")
    _git(seed, "push", "origin", "HEAD:refs/heads/main")

    writer_a = _writer(
        tmp_path,
        remote,
        "writer-a",
        path="catalog/campaigns/same.json",
        body='{"status":"RUNNING","lease_owner":"a"}\n',
    )
    writer_b = _writer(
        tmp_path,
        remote,
        "writer-b",
        path="catalog/campaigns/same.json",
        body='{"status":"RUNNING","lease_owner":"b"}\n',
    )
    first = _publish_process(writer_a, github_context=True)
    first_out, first_err = first.communicate(timeout=20)
    assert first.returncode == 0, (first_out, first_err)
    first_receipt = json.loads(first_out)
    assert first_receipt["run_id"] == "run-123"
    assert first_receipt["run_attempt"] == "2"
    assert first_receipt["job_id"] == "publish-state"
    assert first_receipt["event_sha"] == "event-sha-456"
    repeated = subprocess.run(
        [sys.executable, str(PUBLISHER), "--base-delay-seconds", "0", "--max-delay-seconds", "0"],
        cwd=writer_a,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(repeated.stdout)["status"] == "already_published"

    second = _publish_process(writer_b)
    second_out, second_err = second.communicate(timeout=20)
    assert second.returncode != 0
    assert "state conflict" in second_err

    verify = tmp_path / "verify-conflict"
    subprocess.run(["git", "clone", str(remote), str(verify)], check=True, capture_output=True)
    assert json.loads((verify / "catalog/campaigns/same.json").read_text(encoding="utf-8")) == {
        "status": "RUNNING",
        "lease_owner": "a",
    }
    assert _git(verify, "rev-list", "--count", "origin/main") == "3"


def test_publish_refuses_uncommitted_tracked_changes(tmp_path: Path) -> None:
    remote, _ = _repo_pair(tmp_path)
    repo = _writer(tmp_path, remote, "dirty-writer", path="catalog/campaigns/new.json", body="{}\n")
    (repo / "README.md").write_text("uncommitted\n", encoding="utf-8")
    process = _publish_process(repo)
    stdout, stderr = process.communicate(timeout=20)
    assert process.returncode != 0
    assert "tracked staged or unstaged changes" in stderr
    verify = tmp_path / "verify-dirty"
    subprocess.run(["git", "clone", str(remote), str(verify)], check=True, capture_output=True)
    assert _git(verify, "rev-list", "--count", "origin/main") == "1"


def test_checked_in_main_writer_inventory_matches_workflow_sources() -> None:
    report = ROOT / "docs" / "audits" / "MAIN_STATE_WRITER_INVENTORY.md"
    assert report.read_text(encoding="utf-8") == render(ROOT)


def test_copy_vault_state_publishers_share_safe_retry_and_durable_queue() -> None:
    workflows = ROOT / ".github" / "workflows"
    state_writers = (
        "advance-analysis-stage.yml",
        "analysis-stage-controller.yml",
        "alina-operator-intent.yml",
        "alina-operator-dispatch.yml",
        "control-phase.yml",
        "phase-request-controller.yml",
        "campaign-watchdog.yml",
        "campaign-resilience-receipt.yml",
    )
    for name in state_writers:
        source = (workflows / name).read_text(encoding="utf-8")
        assert "group: copy-vault-main-state-writer" in source
        assert "cancel-in-progress: false" in source
        assert "queue: max" in source
        assert "publish_main_commit.py" in source
        assert "fetch-depth: 0" in source

    selector = (workflows / "resumable-campaign-controller.yml").read_text(encoding="utf-8")
    assert "group: copy-vault-campaign-selector" in selector
    assert "queue: max" in selector
    assert "cron: '*/5 * * * *'" in selector
    assert "github.sha" not in selector.split("jobs:", 1)[0]

    worker = (workflows / "resumable-campaign-worker.yml").read_text(encoding="utf-8")
    assert "group: resumable-${{ inputs.campaign_id }}" in worker
    assert "queue: max" in worker
    assert worker.count("publish_main_commit.py") == 3
    assert "git push origin HEAD:main" not in worker

    creator = (workflows / "create-resumable-campaigns.yml").read_text(encoding="utf-8")
    assert "publish_main_commit.py" in creator
    assert "queue: max" in creator
    assert "cron: '2 * * * *'" in creator
