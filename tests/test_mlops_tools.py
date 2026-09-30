"""Tests MLOps & observabilité."""
from __future__ import annotations

from hl_observer.backtesting.mlops_tools import (
    AuditChain,
    ExperimentTracker,
    FeatureStore,
    lineage_record,
    metric_alerts,
)


def test_experiment_tracker_logs_and_finds_best(tmp_path):
    t = ExperimentTracker(str(tmp_path / "runs.jsonl"))
    t.log_run(params={"lr": 0.1}, metrics={"net": 10.0})
    t.log_run(params={"lr": 0.3}, metrics={"net": 42.0})
    assert len(t.list_runs()) == 2
    assert t.best_run("net")["params"]["lr"] == 0.3


def test_feature_store_versioning(tmp_path):
    fs = FeatureStore(str(tmp_path))
    fs.save("edge", 1, [[1.0], [2.0]])
    fs.save("edge", 2, [[3.0]])
    assert fs.versions("edge") == [1, 2]
    assert fs.load("edge", 2) == [[3.0]]
    assert fs.load("edge", 99) == []            # absent -> vide honnête


def test_lineage_record():
    r = lineage_record("marks", source="hyperliquid_ws", transform="dedupe")
    assert r["dataset"] == "marks" and r["source"] == "hyperliquid_ws"


def test_audit_chain_detects_tampering():
    c = AuditChain()
    c.append({"decision": "NO_TRADE", "coin": "BTC"})
    c.append({"decision": "PAPER_ENTRY", "coin": "ETH"})
    assert c.verify() is True
    c.entries[0]["event"]["decision"] = "PAPER_ENTRY"   # falsification a posteriori
    assert c.verify() is False                          # la chaîne casse


def test_metric_alerts():
    a = metric_alerts({"equity": 900.0}, {"equity": {"min": 950.0}, "latency_ms": {"max": 100}})
    issues = {x["issue"] for x in a}
    assert "BELOW_MIN" in issues and "MISSING" in issues
