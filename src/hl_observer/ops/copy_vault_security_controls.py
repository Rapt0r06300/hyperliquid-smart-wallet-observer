"""Fail-closed security controls for the Copy-Vault paper launcher."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)
CMD_META = set("&|<>^\n\r")
SECRET_WORDS = ("private_key", "secret", "token", "password", "mnemonic", "seed")


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _hash(value: Any) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def runtime_token_request_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Reject a runtime launcher that asks for GitHub credentials."""
    if not isinstance(state, Mapping) or not isinstance(state.get("token_requested"), bool):
        return _base("UNMEASURABLE", reason="runtime_token_state_missing")
    valid = state["token_requested"] is False and state.get("runtime_mode") == "paper"
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="RUNTIME_DOES_NOT_REQUEST_GITHUB_TOKEN" if valid else "RUNTIME_TOKEN_REQUEST_PRESENT",
        token_requested=state["token_requested"],
    )


def process_secret_inheritance_receipt(
    parent: Mapping[str, Any], child: Mapping[str, Any]
) -> dict[str, Any]:
    """Ensure secret-like parent values are not inherited by the child process."""
    if not isinstance(parent, Mapping) or not isinstance(child, Mapping):
        return _base("UNMEASURABLE", reason="invalid_process_environment")
    inherited = [key for key in child if any(word in str(key).lower() for word in SECRET_WORDS)]
    explicit = child.get("real_execution") is False and child.get("paper_read_only") is True
    return _base(
        "PROVEN" if not inherited and explicit else "REJECTED",
        verdict="PROCESS_SECRET_INHERITANCE_DENIED" if not inherited and explicit else "PROCESS_SECRET_INHERITANCE_PRESENT",
        inherited_keys=inherited,
    )


def powershell_policy_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Reject unrestricted ExecutionPolicy bypass in the launcher."""
    if not isinstance(state, Mapping) or not isinstance(state.get("execution_policy_bypass"), bool):
        return _base("UNMEASURABLE", reason="powershell_policy_state_missing")
    valid = state["execution_policy_bypass"] is False
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="POWERSHELL_POLICY_BYPASS_DISABLED" if valid else "POWERSHELL_POLICY_BYPASS_PRESENT",
        execution_policy_bypass=state["execution_policy_bypass"],
    )


def localhost_ui_permissions_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the paper UI bound to loopback and prevent write endpoints."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="invalid_ui_permission_state")
    valid = state.get("bind_host") in {"127.0.0.1", "localhost"} and state.get("write_enabled") is False and state.get("paper_read_only") is True
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="UI_LOOPBACK_READ_ONLY" if valid else "UI_PERMISSION_TOO_BROAD",
        bind_host=state.get("bind_host"),
        write_enabled=state.get("write_enabled"),
    )


def raw_log_secret_receipt(lines: Sequence[str]) -> dict[str, Any]:
    """Reject raw logs containing secret-like key/value material."""
    if not lines:
        return _base("MORE_DATA", reason="empty_log_sample")
    leaked: list[int] = []
    for index, line in enumerate(lines):
        text = str(line).lower()
        if any(word in text and "<redacted>" not in text for word in SECRET_WORDS):
            leaked.append(index)
    return _base(
        "PROVEN" if not leaked else "REJECTED",
        verdict="RAW_LOG_SECRET_FREE" if not leaked else "RAW_LOG_SECRET_LEAK",
        lines=len(lines),
        leaked_rows=leaked,
    )


def cmd_argument_injection_receipt(args: Sequence[str]) -> dict[str, Any]:
    """Reject Windows command metacharacters in launcher arguments."""
    if not args:
        return _base("MORE_DATA", reason="empty_cmd_arguments")
    invalid = [index for index, arg in enumerate(args) if not isinstance(arg, str) or any(char in arg for char in CMD_META)]
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="CMD_ARGUMENTS_SAFE" if not invalid else "CMD_ARGUMENT_INJECTION_RISK",
        arguments=len(args),
        invalid_rows=invalid,
    )


def portable_python_integrity_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require the portable Python executable to match its pinned fingerprint."""
    if not isinstance(state, Mapping) or not _hash(state.get("executable_sha")) or not _hash(state.get("expected_sha")):
        return _base("UNMEASURABLE", reason="portable_python_hash_missing")
    valid = state["executable_sha"].lower() == state["expected_sha"].lower() and state.get("replacement_detected") is False
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="PORTABLE_PYTHON_INTEGRITY_VERIFIED" if valid else "PORTABLE_PYTHON_REPLACEMENT_DETECTED",
        replacement_detected=state.get("replacement_detected"),
    )


def cli_no_real_execution_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the CLI paper-only and reject any execution endpoint."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="invalid_cli_execution_state")
    valid = state.get("paper_read_only") is True and state.get("real_execution") is False and not str(state.get("execution_endpoint") or "").strip()
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="CLI_NO_REAL_EXECUTION" if valid else "CLI_REAL_EXECUTION_PATH_PRESENT",
        execution_endpoint=state.get("execution_endpoint"),
    )


def ollama_loopback_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Restrict the optional local model service to loopback."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="invalid_ollama_state")
    valid = state.get("host") in {"127.0.0.1", "localhost"} and state.get("remote_access") is False
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="OLLAMA_LOOPBACK_ONLY" if valid else "OLLAMA_REMOTE_ACCESS_PRESENT",
        host=state.get("host"),
        remote_access=state.get("remote_access"),
    )


def readonly_audit_dependencies_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require audit dependencies to be read-only and non-networking."""
    if not rows:
        return _base("MORE_DATA", reason="empty_audit_dependency_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("dependency") or "").strip() or row.get("write_capability") is not False or row.get("network_access") is not False
    ]
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="AUDIT_DEPENDENCIES_READ_ONLY" if not invalid else "AUDIT_DEPENDENCY_WRITE_OR_NETWORK_PATH",
        dependencies=len(rows),
        invalid_rows=invalid,
    )


__all__ = [
    "runtime_token_request_receipt",
    "process_secret_inheritance_receipt",
    "powershell_policy_receipt",
    "localhost_ui_permissions_receipt",
    "raw_log_secret_receipt",
    "cmd_argument_injection_receipt",
    "portable_python_integrity_receipt",
    "cli_no_real_execution_receipt",
    "ollama_loopback_receipt",
    "readonly_audit_dependencies_receipt",
]
