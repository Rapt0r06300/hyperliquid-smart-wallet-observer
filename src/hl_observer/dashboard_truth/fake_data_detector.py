from __future__ import annotations

from typing import Any


PLACEHOLDER_MARKERS = ("placeholder", "fake", "demo_only", "lorem ipsum", "TODO")


def detect_placeholder_values(payload: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    _walk(payload, "", findings)
    return findings


def _walk(value: Any, path: str, findings: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _walk(child, f"{path}.{key}" if path else str(key), findings)
        return
    if isinstance(value, list):
        for index, child in enumerate(value[:200]):
            _walk(child, f"{path}[{index}]", findings)
        return
    if isinstance(value, str):
        lowered = value.lower()
        if "no fake" in lowered or "not fake" in lowered:
            lowered = lowered.replace("no fake", "no synthetic").replace("not fake", "not synthetic")
        if any(marker.lower() in lowered for marker in PLACEHOLDER_MARKERS):
            findings.append(path or "<root>")
