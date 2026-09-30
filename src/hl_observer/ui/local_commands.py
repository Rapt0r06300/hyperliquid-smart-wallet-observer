"""Local commands (V12, repo 04): parse /status /orders /pnl /set_rule (read-only/local).

Parses local terminal-style commands into a structured intent. /set_rule writes to a local
rule store; all others are read-only. NEVER triggers any external/real action.
"""

from __future__ import annotations

_READ_COMMANDS = {"status", "orders", "pnl", "positions", "help"}


def parse_command(text: str) -> dict:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return {"command": None, "ok": False, "error": "not_a_command"}
    parts = raw[1:].split()
    if not parts:
        return {"command": None, "ok": False, "error": "empty"}
    cmd = parts[0].lower()
    if cmd in _READ_COMMANDS:
        return {"command": cmd, "mode": "read", "ok": True, "external_action": False}
    if cmd == "set_rule":
        if len(parts) < 3:
            return {"command": "set_rule", "ok": False, "error": "usage:/set_rule <key> <value>"}
        return {"command": "set_rule", "mode": "local_write", "ok": True,
                "external_action": False, "key": parts[1], "value": " ".join(parts[2:])}
    return {"command": cmd, "ok": False, "error": "unknown_command"}


__all__ = ["parse_command"]
