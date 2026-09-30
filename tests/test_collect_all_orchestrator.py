"""'Collect everything' orchestrator: graceful per-step handling, honest summary."""

from __future__ import annotations

from hl_observer.collection.collect_all import CollectAllReport, StepResult, run_steps


def test_all_steps_ok():
    report = run_steps([
        ("discover_markets", lambda: "coins=814"),
        ("leaderboard", lambda: "wallets=200"),
    ])
    assert report.ok is True and report.ran == 2 and report.failed == 0
    assert "coins=814" in report.summary()


def test_one_failing_step_does_not_stop_the_others():
    def boom():
        raise RuntimeError("network read failed")

    report = run_steps([
        ("discover_markets", lambda: "coins=10"),
        ("leaderboard", boom),            # fails
        ("backfill", lambda: "wallets=5"),  # must still run
    ])
    assert report.ok is False
    assert report.ran == 3 and report.failed == 1
    names_ok = {r.name for r in report.results if r.ok}
    assert names_ok == {"discover_markets", "backfill"}  # failure isolated
    assert "FAIL leaderboard" in report.summary()
    assert "network read failed" in report.summary()


def test_report_is_honest_about_partial_coverage():
    report = CollectAllReport(results=[StepResult("a", True, "ok"), StepResult("b", False, error="x")])
    assert report.ran == 2 and report.failed == 1 and report.ok is False
