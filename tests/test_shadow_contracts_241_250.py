from hl_observer.ops.copy_vault_shadow_controls import (
    baseline_vs_llm_shadow_receipt,
    model_age_provenance_receipt,
    model_freeze_receipt,
    model_noise_reduction_receipt,
    ollama_outage_engine_continuity_receipt,
    portable_model_path_receipt,
    sensitive_explanation_redaction_receipt,
    training_session_separation_receipt,
    v13_shadow_role_receipt,
    v14_signal_rater_non_authoritative_receipt,
)


def test_lch241_defines_v13_as_shadow() -> None:
    row = {"version": "V13", "role": "SHADOW", "authoritative": False, "can_submit": False}
    assert v13_shadow_role_receipt([row])["status"] == "PROVEN"
    row["can_submit"] = True
    assert v13_shadow_role_receipt([row])["status"] == "REJECTED"


def test_lch242_keeps_v14_signal_rater_non_authoritative() -> None:
    row = {"version": "V14", "component": "signal-rater", "authoritative": False, "can_override": False}
    assert v14_signal_rater_non_authoritative_receipt([row])["status"] == "PROVEN"
    row["can_override"] = True
    assert v14_signal_rater_non_authoritative_receipt([row])["status"] == "REJECTED"


def test_lch243_model_outage_does_not_stop_paper_engine() -> None:
    row = {"model_available": False, "engine_alive": True, "engine_state": "RUNNING", "paper_read_only": True}
    assert ollama_outage_engine_continuity_receipt([row])["status"] == "PROVEN"
    row["engine_alive"] = False
    assert ollama_outage_engine_continuity_receipt([row])["status"] == "REJECTED"


def test_lch244_model_noise_is_bounded() -> None:
    row = {"input_hash": "abc", "deterministic_features": True, "noise_reduced": True, "noise_score": 0.1}
    assert model_noise_reduction_receipt([row])["status"] == "PROVEN"
    row["noise_score"] = 2
    assert model_noise_reduction_receipt([row])["status"] == "UNMEASURABLE"


def test_lch245_model_age_and_provenance_are_explicit() -> None:
    row = {"model_id": "m1", "model_sha256": "sha", "provenance": "manifest:1", "trained_at_ms": 100, "loaded_at_ms": 200}
    assert model_age_provenance_receipt([row])["status"] == "PROVEN"
    row["provenance"] = ""
    assert model_age_provenance_receipt([row])["status"] == "UNMEASURABLE"


def test_lch246_training_and_active_sessions_are_separate() -> None:
    row = {"training_session_id": "train-1", "active_session_id": "run-1", "artifact_sha256": "sha", "active_session_mutated": False}
    assert training_session_separation_receipt([row])["status"] == "PROVEN"
    row["active_session_id"] = "train-1"
    assert training_session_separation_receipt([row])["status"] == "REJECTED"


def test_lch247_sensitive_explanations_are_redacted() -> None:
    row = {"redacted": True, "explanation": "decision withheld; source omitted"}
    assert sensitive_explanation_redaction_receipt([row])["status"] == "PROVEN"
    row["explanation"] = "private_key=secret"
    assert sensitive_explanation_redaction_receipt([row])["status"] == "REJECTED"


def test_lch248_model_freeze_binds_evaluation() -> None:
    row = {"frozen": True, "model_sha256": "m", "config_sha256": "c", "evaluation_manifest_sha256": "e", "parameters_bound": True}
    assert model_freeze_receipt([row])["status"] == "PROVEN"
    row["parameters_bound"] = False
    assert model_freeze_receipt([row])["status"] == "UNMEASURABLE"


def test_lch249_baseline_remains_authoritative() -> None:
    row = {"baseline_decision": "NO_TRADE", "shadow_decision": "TRADE", "baseline_authoritative": True, "shadow_authoritative": False, "shadow_can_override": False}
    assert baseline_vs_llm_shadow_receipt([row])["status"] == "PROVEN"
    row["shadow_can_override"] = True
    assert baseline_vs_llm_shadow_receipt([row])["status"] == "REJECTED"


def test_lch250_model_path_is_portable() -> None:
    row = {"model_id": "m1", "model_path": "models/m1.bin"}
    assert portable_model_path_receipt([row])["status"] == "PROVEN"
    row["model_path"] = r"C:\\models\\m1.bin"
    assert portable_model_path_receipt([row])["status"] == "REJECTED"
