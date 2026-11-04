from hl_observer.ops.copy_vault_portability_controls import (
    clone_without_embedded_python_receipt,
    double_click_accessibility_receipt,
    launcher_root_path_receipt,
    menu_command_receipt,
    noninteractive_deterministic_receipt,
    offline_startup_receipt,
    popup_free_subcommands_receipt,
    runtime_migration_receipt,
    tools_python_presence_receipt,
    utf8_console_receipt,
)


def test_lch181_clone_does_not_embed_python() -> None:
    assert clone_without_embedded_python_receipt({"embedded_python_present": False, "python_discovery_declared": True})["status"] == "PROVEN"
    assert clone_without_embedded_python_receipt({"embedded_python_present": True, "python_discovery_declared": True})["status"] == "REJECTED"


def test_lch182_runtime_migration_is_explicit() -> None:
    assert runtime_migration_receipt([{"old_runtime": "legacy", "new_runtime": "src", "migration_checked": True}])["status"] == "PROVEN"


def test_lch183_launcher_uses_script_root() -> None:
    row = {"script_root": "%~dp0", "derived_from_script_root": True, "absolute_user_path": False}
    assert launcher_root_path_receipt([row])["status"] == "PROVEN"
    row["absolute_user_path"] = True
    assert launcher_root_path_receipt([row])["status"] == "REJECTED"


def test_lch184_tools_python_is_present_for_subcommands() -> None:
    row = {"command": "scan", "requires_tools_python": True, "tools_python_present": True}
    assert tools_python_presence_receipt([row])["status"] == "PROVEN"
    row["tools_python_present"] = False
    assert tools_python_presence_receipt([row])["status"] == "UNMEASURABLE"


def test_lch185_double_click_leaves_accessible_report() -> None:
    state = {"report_path_visible": True, "exit_code_visible": True, "pause_for_error": True}
    assert double_click_accessibility_receipt(state)["status"] == "PROVEN"
    state["report_path_visible"] = False
    assert double_click_accessibility_receipt(state)["status"] == "REJECTED"


def test_lch186_noninteractive_mode_is_deterministic() -> None:
    assert noninteractive_deterministic_receipt({"noninteractive": True, "deterministic_inputs": True, "prompt_required": False})["status"] == "PROVEN"
    assert noninteractive_deterministic_receipt({"noninteractive": True, "deterministic_inputs": False, "prompt_required": False})["status"] == "REJECTED"


def test_lch187_subcommands_do_not_spawn_popups() -> None:
    row = {"command": "audit", "popup_spawned": False, "background_window": False}
    assert popup_free_subcommands_receipt([row])["status"] == "PROVEN"
    row["popup_spawned"] = True
    assert popup_free_subcommands_receipt([row])["status"] == "REJECTED"


def test_lch188_menu_commands_are_explicit() -> None:
    row = {"label": "Audit", "command": "audit", "paper_read_only": True}
    assert menu_command_receipt([row])["status"] == "PROVEN"


def test_lch189_console_encoding_is_utf8() -> None:
    assert utf8_console_receipt({"stdout_encoding": "utf-8", "stderr_encoding": "utf-8", "unicode_tested": True})["status"] == "PROVEN"
    assert utf8_console_receipt({"stdout_encoding": "cp1252", "stderr_encoding": "utf-8", "unicode_tested": True})["status"] == "UNMEASURABLE"


def test_lch190_offline_startup_uses_no_network() -> None:
    state = {"offline": True, "network_attempted": False, "paper_read_only": True, "real_execution": False}
    assert offline_startup_receipt(state)["status"] == "PROVEN"
    state["network_attempted"] = True
    assert offline_startup_receipt(state)["status"] == "REJECTED"
