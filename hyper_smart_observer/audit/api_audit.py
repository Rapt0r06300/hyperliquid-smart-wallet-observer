from __future__ import annotations


def audit_api_readonly(payload_types: list[str]) -> tuple[bool, str]:
    dangerous = [payload for payload in payload_types if payload.lower() in {"order", "cancel", "withdraw", "transfer"}]
    return not dangerous, f"dangerous payload types: {dangerous}"
