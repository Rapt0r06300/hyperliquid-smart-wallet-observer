"""Fail-closed portability and launcher UX controls for Copy-Vault."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def clone_without_embedded_python_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require a clone to use declared Python discovery rather than an embedded copy."""
    if not isinstance(state, Mapping) or not isinstance(state.get("embedded_python_present"), bool) or not isinstance(state.get("python_discovery_declared"), bool):
        return _base("UNMEASURABLE", reason="clone_python_state_missing")
    valid = state["embedded_python_present"] is False and state["python_discovery_declared"] is True
    return _base("PROVEN" if valid else "REJECTED", verdict="CLONE_WITHOUT_EMBEDDED_PYTHON" if valid else "EMBEDDED_PYTHON_OR_UNDECLARED_DISCOVERY")


def runtime_migration_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require an explicit old-to-new runtime migration path."""
    if not rows:
        return _base("MORE_DATA", reason="empty_runtime_migration")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("old_runtime") or "").strip() or not str(row.get("new_runtime") or "").strip() or row.get("migration_checked") is not True
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="RUNTIME_MIGRATION_EXPLICIT" if not invalid else "RUNTIME_MIGRATION_INCOMPLETE", invalid_rows=invalid)


def launcher_root_path_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Check that launcher paths derive from the script root rather than a fixed PC path."""
    if not rows:
        return _base("MORE_DATA", reason="empty_launcher_paths")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("script_root") or "").strip() or row.get("derived_from_script_root") is not True or row.get("absolute_user_path") is True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="LAUNCHER_ROOT_PATH_PORTABLE" if not invalid else "LAUNCHER_FIXED_USER_PATH", invalid_rows=invalid)


def tools_python_presence_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require an explicit tools/python entry for non-boot subcommands."""
    if not rows:
        return _base("MORE_DATA", reason="empty_subcommand_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("command") or "").strip() or row.get("requires_tools_python") is not True or row.get("tools_python_present") is not True
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="TOOLS_PYTHON_PRESENT_FOR_SUBCOMMAND" if not invalid else "TOOLS_PYTHON_MISSING", invalid_rows=invalid)


def double_click_accessibility_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require a double-click launcher to leave an accessible report and exit code."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="invalid_double_click_state")
    valid = state.get("report_path_visible") is True and state.get("exit_code_visible") is True and state.get("pause_for_error") is True
    return _base("PROVEN" if valid else "REJECTED", verdict="DOUBLE_CLICK_REPORT_ACCESSIBLE" if valid else "DOUBLE_CLICK_REPORT_INACCESSIBLE")


def noninteractive_deterministic_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require non-interactive mode to use a deterministic input contract."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="invalid_noninteractive_state")
    valid = state.get("noninteractive") is True and state.get("deterministic_inputs") is True and state.get("prompt_required") is False
    return _base("PROVEN" if valid else "REJECTED", verdict="NONINTERACTIVE_DETERMINISTIC" if valid else "NONINTERACTIVE_PROMPT_OR_NONDETERMINISTIC")


def popup_free_subcommands_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reject child commands that leave visible popup processes behind."""
    if not rows:
        return _base("MORE_DATA", reason="empty_popup_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("command") or "").strip() or row.get("popup_spawned") is not False or row.get("background_window") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="SUBCOMMANDS_POPUP_FREE" if not invalid else "SUBCOMMAND_POPUP_PRESENT", invalid_rows=invalid)


def menu_command_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require menu entries to describe their command and safety mode."""
    if not rows:
        return _base("MORE_DATA", reason="empty_menu_commands")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("label") or "").strip() or not str(row.get("command") or "").strip() or row.get("paper_read_only") is not True
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="MENU_COMMANDS_EXPLICIT" if not invalid else "MENU_COMMAND_UNSAFE_OR_UNCLEAR", invalid_rows=invalid)


def utf8_console_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require explicit UTF-8 console configuration for Windows output."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="invalid_console_encoding_state")
    valid = state.get("stdout_encoding") == "utf-8" and state.get("stderr_encoding") == "utf-8" and state.get("unicode_tested") is True
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="CONSOLE_UTF8_CONFIGURED" if valid else "CONSOLE_UTF8_NOT_VERIFIED")


def offline_startup_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require offline startup to perform no network operation and remain paper-only."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="invalid_offline_startup_state")
    valid = state.get("offline") is True and state.get("network_attempted") is False and state.get("paper_read_only") is True and state.get("real_execution") is False
    return _base("PROVEN" if valid else "REJECTED", verdict="OFFLINE_STARTUP_NO_NETWORK" if valid else "OFFLINE_STARTUP_NETWORK_OR_EXECUTION_PATH")


__all__ = [
    "clone_without_embedded_python_receipt",
    "runtime_migration_receipt",
    "launcher_root_path_receipt",
    "tools_python_presence_receipt",
    "double_click_accessibility_receipt",
    "noninteractive_deterministic_receipt",
    "popup_free_subcommands_receipt",
    "menu_command_receipt",
    "utf8_console_receipt",
    "offline_startup_receipt",
]
