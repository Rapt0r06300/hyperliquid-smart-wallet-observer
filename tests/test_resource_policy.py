"""Resource policy regressions for HyperSmart Windows launchers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import resource_policy as RES  # noqa: E402


def test_policy_is_always_below_normal_and_never_pauses():
    for salad_active in (False, True):
        policy = RES.effective_policy(salad_active=salad_active)
        assert policy["priority"] == "BELOW_NORMAL"
        assert policy["never_idle"] is True
        assert policy["pause_workload"] is False


def test_salad_profile_reduces_only_hypersmart_concurrency():
    normal = RES.effective_policy(salad_active=False)
    salad = RES.effective_policy(salad_active=True)
    assert salad["max_workers"] < normal["max_workers"]
    assert salad["max_sources_per_bootstrap"] < normal["max_sources_per_bootstrap"]
    assert salad["max_bootstrap_megabytes"] < normal["max_bootstrap_megabytes"]
    assert salad["dashboard_refresh_ms"] == normal["dashboard_refresh_ms"] == 1000
    assert salad["priority"] == normal["priority"] == "BELOW_NORMAL"
    assert salad["pause_workload"] is normal["pause_workload"] is False


def test_environment_caps_expose_never_idle_contract(monkeypatch):
    for name in (
        "HYPERSMART_18H_MAX_WORKERS",
        "HYPERSMART_18H_MAX_SOURCES_PER_BOOTSTRAP",
        "HYPERSMART_18H_MAX_BOOTSTRAP_MEGABYTES",
        "HYPERSMART_RESOURCE_PRIORITY",
        "HYPERSMART_RESOURCE_NEVER_IDLE",
    ):
        monkeypatch.delenv(name, raising=False)
    policy = RES.apply_environment_caps(salad_active=True)
    assert policy["pause_workload"] is False
    assert RES.os.environ["HYPERSMART_RESOURCE_PRIORITY"] == "BELOW_NORMAL"
    assert RES.os.environ["HYPERSMART_RESOURCE_NEVER_IDLE"] == "1"
    assert RES.os.environ["HYPERSMART_18H_MAX_WORKERS"] == "1"


def test_process_matching_is_limited_to_hypersmart_project():
    root = Path(r"C:\Users\flo\Desktop\Projet invest")
    matching = (
        r'python C:\Users\flo\Desktop\Projet invest\tools\recherche_continue.py start'
    )
    unrelated = r"python C:\Users\flo\Desktop\Other\worker.py"
    assert RES._is_hypersmart_process(matching, root=root) is True
    assert RES._is_hypersmart_process(unrelated, root=root) is False
    assert RES._is_hypersmart_process(
        "python -m hl_observer ui",
        root=root,
        cwd=root,
    ) is True
    assert RES._is_hypersmart_process(
        "python -m hl_observer ui",
        root=root,
        cwd=Path(r"C:\Users\flo\Desktop\Other"),
    ) is False


def test_salad_detection_accepts_windows_process_variants():
    assert RES.salad_running(["Salad.exe"]) is True
    assert RES.salad_running(["Salad.Bowl.Service.exe"]) is True
    assert RES.salad_running(["SaladWorker-1.exe"]) is True
    assert RES.salad_running(["python.exe", "chrome.exe"]) is False


def test_launchers_declare_below_normal_without_idle_priority():
    cmd = (ROOT / "LANCER-RECHERCHE-CONTINUE.cmd").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    ps1 = (ROOT / "tools" / "start_hypersmart_simulation.ps1").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    assert "HYPERSMART_RESOURCE_NEVER_IDLE=1" in cmd
    assert "HYPERSMART_DASHBOARD_REFRESH_MS=1000" in cmd
    assert 'PriorityClass = "BelowNormal"' in ps1
    assert 'PriorityClass = "Idle"' not in ps1
    assert "resource_policy.py" in ps1
