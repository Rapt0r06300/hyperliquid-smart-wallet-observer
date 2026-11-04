from hl_observer.ops.copy_vault_security_controls import (
    cli_no_real_execution_receipt,
    cmd_argument_injection_receipt,
    localhost_ui_permissions_receipt,
    ollama_loopback_receipt,
    portable_python_integrity_receipt,
    powershell_policy_receipt,
    process_secret_inheritance_receipt,
    raw_log_secret_receipt,
    readonly_audit_dependencies_receipt,
    runtime_token_request_receipt,
)


def test_lch171_runtime_does_not_request_github_token() -> None:
    assert runtime_token_request_receipt({"token_requested": False, "runtime_mode": "paper"})["status"] == "PROVEN"
    assert runtime_token_request_receipt({"token_requested": True, "runtime_mode": "paper"})["status"] == "REJECTED"


def test_lch172_child_does_not_inherit_secret_keys() -> None:
    assert process_secret_inheritance_receipt({"PRIVATE_KEY": "x"}, {"real_execution": False, "paper_read_only": True})["status"] == "PROVEN"
    assert process_secret_inheritance_receipt({}, {"PRIVATE_KEY": "x", "real_execution": False, "paper_read_only": True})["status"] == "REJECTED"


def test_lch173_execution_policy_bypass_is_disabled() -> None:
    assert powershell_policy_receipt({"execution_policy_bypass": False})["status"] == "PROVEN"
    assert powershell_policy_receipt({"execution_policy_bypass": True})["status"] == "REJECTED"


def test_lch174_ui_is_loopback_read_only() -> None:
    assert localhost_ui_permissions_receipt({"bind_host": "127.0.0.1", "write_enabled": False, "paper_read_only": True})["status"] == "PROVEN"
    assert localhost_ui_permissions_receipt({"bind_host": "0.0.0.0", "write_enabled": False, "paper_read_only": True})["status"] == "REJECTED"


def test_lch175_raw_logs_do_not_contain_secrets() -> None:
    assert raw_log_secret_receipt(["mode=paper", "token=<redacted>"])["status"] == "PROVEN"
    assert raw_log_secret_receipt(["private_key=abc"])["status"] == "REJECTED"


def test_lch176_cmd_arguments_reject_metacharacters() -> None:
    assert cmd_argument_injection_receipt(["--mode", "paper"])["status"] == "PROVEN"
    assert cmd_argument_injection_receipt(["--mode", "paper & whoami"])["status"] == "REJECTED"


def test_lch177_portable_python_hash_is_pinned() -> None:
    assert portable_python_integrity_receipt({"executable_sha": "a" * 64, "expected_sha": "a" * 64, "replacement_detected": False})["status"] == "PROVEN"
    assert portable_python_integrity_receipt({"executable_sha": "a" * 64, "expected_sha": "b" * 64, "replacement_detected": False})["status"] == "REJECTED"


def test_lch178_cli_has_no_real_execution_path() -> None:
    assert cli_no_real_execution_receipt({"paper_read_only": True, "real_execution": False, "execution_endpoint": ""})["status"] == "PROVEN"
    assert cli_no_real_execution_receipt({"paper_read_only": True, "real_execution": False, "execution_endpoint": "https://exchange"})["status"] == "REJECTED"


def test_lch179_ollama_is_loopback_only() -> None:
    assert ollama_loopback_receipt({"host": "127.0.0.1", "remote_access": False})["status"] == "PROVEN"
    assert ollama_loopback_receipt({"host": "0.0.0.0", "remote_access": True})["status"] == "REJECTED"


def test_lch180_audit_dependencies_are_read_only() -> None:
    row = {"dependency": "json", "write_capability": False, "network_access": False}
    assert readonly_audit_dependencies_receipt([row])["status"] == "PROVEN"
    row["network_access"] = True
    assert readonly_audit_dependencies_receipt([row])["status"] == "REJECTED"
