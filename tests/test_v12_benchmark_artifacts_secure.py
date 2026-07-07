from hl_observer.product_benchmark.feature_matrix import all_categories, build_feature_matrix
from hl_observer.alerts.local_alerts import LocalAlerts
from hl_observer.ui.wallet_panels import build_copyability_panel, build_red_flags_panel
from hl_observer.artifacts.extractor import extract_artifacts
from hl_observer.evidence.context_compaction import compact_context
from hl_observer.skills.optional_registry import OptionalSkillRegistry
from hl_observer.security.secure_report import build_secure_report


def test_feature_matrix_has_all_categories():
    m = build_feature_matrix()
    for cat in ("ai_agents", "alerts", "analytics", "dashboards", "data", "trading_bots", "orderbook_depth"):
        assert cat in m["categories"]
    assert m["total"] == len(all_categories())


def test_alerts_disabled_by_default():
    a = LocalAlerts()
    assert a.raise_alert(kind="risk", message="x") is None and a.fired() == []
    a.enabled = True
    assert a.raise_alert(kind="risk", message="x")["external_action"] is False


def test_red_flags_requires_data_and_copyability_uses_evidence():
    assert build_red_flags_panel(None)["empty"] is True
    rf = build_red_flags_panel({"one_big_win_share": 0.6, "recent_fills": 0})
    assert "ONE_BIG_WIN_RISK" in rf["red_flags"] and "INACTIVE_WALLET" in rf["red_flags"]
    cp = build_copyability_panel(copyability_score=0.8, evidence_refs=["ev1"])
    assert cp["evidence_refs"] == ["ev1"] and cp["empty"] is False


def test_artifacts_extracted_after_scan():
    arts = extract_artifacts({"reports": [{"title": "R1", "ref": "a"}], "decisions": [{"title": "D1"}]})
    kinds = {a["kind"] for a in arts}
    assert kinds == {"report", "decision"}


def test_context_compaction_preserves_decisions():
    items = [{"kind": "decision", "id": 1}] + [{"kind": "tick", "id": i} for i in range(100)]
    out = compact_context(items, max_other=10)
    assert out["decisions"] == [{"kind": "decision", "id": 1}]
    assert len(out["other"]) == 10 and out["dropped_other"] == 90 and out["decision_summary_preserved"]


def test_optional_skill_missing_dependency_does_not_crash():
    reg = OptionalSkillRegistry()
    reg.register("present", "json")             # stdlib -> available
    reg.register("absent", "totally_missing_pkg_xyz")
    assert "present" in reg.available() and "absent" in reg.unavailable()


def test_secure_report_attests_no_real_action():
    rep = build_secure_report()
    assert rep["real_action_possible"] is False and rep["signature_sent"] is False
    assert rep["no_fake_data"] is True and rep["fake_findings"] == 0
