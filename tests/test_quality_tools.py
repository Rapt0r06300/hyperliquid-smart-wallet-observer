"""Tests qualité & opérations."""
from __future__ import annotations

from hl_observer.backtesting import quality_tools as qt
from hl_observer.backtesting.quality_tools import (
    ModelRegistry,
    ProxyRotator,
    autodoc_functions,
    nonregression_check,
    prometheus_metrics_text,
)


def test_prometheus_format():
    txt = prometheus_metrics_text({"equity": 950.5, "name": "x"})
    assert "# TYPE hypersmart_equity gauge" in txt
    assert "hypersmart_equity 950.5" in txt
    assert "name" not in txt                       # non numérique ignoré


def test_proxy_rotator_round_robin_and_failover():
    r = ProxyRotator(["p1", "p2", "p3"])
    assert {r.next(), r.next(), r.next()} == {"p1", "p2", "p3"}
    r.mark_failed("p1")
    got = {r.next() for _ in range(6)}
    assert "p1" not in got                          # proxy KO écarté


def test_model_registry(tmp_path):
    reg = ModelRegistry(str(tmp_path))
    reg.save("logreg", 1, {"w": [0.5], "b": 0.1}, metadata={"acc": 0.62})
    got = reg.load("logreg", 1)
    assert got["model"]["b"] == 0.1 and got["metadata"]["acc"] == 0.62
    assert reg.load("logreg", 9) is None


def test_nonregression_detects_drop():
    regs = nonregression_check({"net": 100.0, "pf": 1.5}, {"net": 80.0, "pf": 1.48}, tolerance=0.05)
    metrics = {r["metric"] for r in regs}
    assert "net" in metrics                         # -20% -> régression
    assert "pf" not in metrics                      # -1.3% -> dans la tolérance


def test_autodoc_lists_functions():
    md = autodoc_functions(qt)
    assert "prometheus_metrics_text" in md and "ProxyRotator" in md
