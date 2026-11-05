"""Stable-prefix construction for prompt/cache reuse without dynamic leakage."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StablePrefix:
    text: str
    sha256: str
    cache_key: str
    dynamic_boundary: str = "DYNAMIC_TAIL_START"

    def to_dict(self) -> dict[str, str]:
        return {
            "sha256": self.sha256,
            "cache_key": self.cache_key,
            "dynamic_boundary": self.dynamic_boundary,
            "text": self.text,
        }


def build_cache_key(*, model_family: str, policy_text: str, repository_fingerprint: str) -> str:
    payload = {
        "model_family": str(model_family),
        "policy_sha256": _sha256(policy_text),
        "repository_fingerprint": str(repository_fingerprint),
    }
    return _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")))[:32]


def build_stable_prefix(
    *,
    model_family: str,
    policy_text: str,
    repository_fingerprint: str,
    tool_manifest: list[str] | tuple[str, ...] = (),
) -> StablePrefix:
    tools = "\n".join(sorted({str(tool).strip() for tool in tool_manifest if str(tool).strip()}))
    text = "\n".join((policy_text.strip(), "TOOLS:", tools, "DYNAMIC_TAIL_START"))
    return StablePrefix(
        text=text,
        sha256=_sha256(text),
        cache_key=build_cache_key(
            model_family=model_family,
            policy_text=policy_text,
            repository_fingerprint=repository_fingerprint,
        ),
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["StablePrefix", "build_cache_key", "build_stable_prefix"]
