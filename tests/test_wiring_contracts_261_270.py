from hl_observer.ops.copy_vault_wiring_controls import (
    canary_call_trace_receipt,
    concurrent_pipeline_import_scope_receipt,
    following_wallet_bridge_receipt,
    legacy_vs_canonical_runtime_receipt,
    orphan_component_usage_receipt,
    paper_intent_unification_receipt,
    required_module_wiring_receipt,
    shared_stream_state_receipt,
    startup_module_tree_receipt,
    tested_only_inventory_receipt as inventory_checker,
)


def test_lch261_required_modules_are_wired_to_canonical_runtime() -> None:
    row = {"module": "collector", "import_path": "src.hl_observer.collector", "required": True, "loaded": True, "runtime": "src.hl_observer"}
    assert required_module_wiring_receipt([row])["status"] == "PROVEN"
    row["loaded"] = False
    assert required_module_wiring_receipt([row])["status"] == "UNMEASURABLE"


def test_lch262_test_only_inventory_is_not_runtime_reachable() -> None:
    row = {"classification": "TESTE_SEULEMENT", "runtime_reachable": False, "test_owner": "contract"}
    assert inventory_checker([row])["status"] == "PROVEN"
    row["runtime_reachable"] = True
    assert inventory_checker([row])["status"] == "REJECTED"


def test_lch263_orphan_usage_is_explicit() -> None:
    assert orphan_component_usage_receipt([{"component": "x", "used_by": [], "orphan": True}])["status"] == "PROVEN"
    assert orphan_component_usage_receipt([{"component": "x", "used_by": ["runtime"], "orphan": True}])["status"] == "UNMEASURABLE"


def test_lch264_following_bridge_requires_consent_and_provenance() -> None:
    row = {"following_event_id": "e1", "wallet_id": "w1", "provenance": "SAFE:1", "consent": True}
    assert following_wallet_bridge_receipt([row])["status"] == "PROVEN"
    row["consent"] = False
    assert following_wallet_bridge_receipt([row])["status"] == "UNMEASURABLE"


def test_lch265_legacy_surface_is_not_canonical_runtime() -> None:
    rows = [{"surface": "src.hl_observer", "canonical_runtime": True}, {"surface": "hyper_smart_observer", "canonical_runtime": False}]
    assert legacy_vs_canonical_runtime_receipt(rows)["status"] == "PROVEN"
    rows[1]["canonical_runtime"] = True
    assert legacy_vs_canonical_runtime_receipt(rows)["status"] == "REJECTED"


def test_lch266_pipeline_import_scope_is_copy_vault_only() -> None:
    row = {"pipeline": "copy", "import_path": "src.hl_observer.pipeline", "family": "Copy-Vault", "disabled_family_import": False}
    assert concurrent_pipeline_import_scope_receipt([row])["status"] == "PROVEN"
    row["family"] = "Arbitrage"
    assert concurrent_pipeline_import_scope_receipt([row])["status"] == "REJECTED"


def test_lch267_paper_intent_is_canonical() -> None:
    row = {"canonical_type_id": "paper-intent", "canonical": True, "duplicate_model": False}
    assert paper_intent_unification_receipt([row])["status"] == "PROVEN"
    row["duplicate_model"] = True
    assert paper_intent_unification_receipt([row])["status"] == "REJECTED"


def test_lch268_ui_and_poller_share_state_epoch() -> None:
    row = {"ui_state": "LIVE", "poller_state": "LIVE", "ui_epoch": 3, "poller_epoch": 3}
    assert shared_stream_state_receipt([row])["status"] == "PROVEN"
    row["poller_epoch"] = 2
    assert shared_stream_state_receipt([row])["status"] == "REJECTED"


def test_lch269_startup_tree_has_one_orchestrator() -> None:
    rows = [{"path": "src.hl_observer.control", "importable": True, "startup_order": 1, "role": "ORCHESTRATOR"}, {"path": "src.hl_observer.ui", "importable": True, "startup_order": 2, "role": "UI"}]
    assert startup_module_tree_receipt(rows)["status"] == "PROVEN"
    rows.append({"path": "src.hl_observer.other", "importable": True, "startup_order": 3, "role": "ORCHESTRATOR"})
    assert startup_module_tree_receipt(rows)["status"] == "REJECTED"


def test_lch270_canary_trace_is_paper_read_only() -> None:
    row = {"call": "decision", "mode": "PAPER", "network_order_call": False, "real_execution": False}
    assert canary_call_trace_receipt([row])["status"] == "PROVEN"
    row["network_order_call"] = True
    assert canary_call_trace_receipt([row])["status"] == "REJECTED"
