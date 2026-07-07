"""Ollama status helpers for the local read-only explainer."""

from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.research.ollama_client import config_from_env, list_models


@dataclass(frozen=True, slots=True)
class OllamaStatus:
    installed_hint: bool
    api_available: bool
    enabled: bool
    host: str
    models: tuple[str, ...] = field(default_factory=tuple)
    reason: str | None = None
    hot_path: bool = False
    paper_only: bool = True


def ollama_status(*, host: str | None = None, timeout: float = 0.6) -> OllamaStatus:
    cfg = config_from_env()
    if host:
        cfg = type(cfg)(
            enabled=cfg.enabled,
            host=host,
            model=cfg.model,
            api_style=cfg.api_style,
            timeout_sec=cfg.timeout_sec,
            ui_timeout_sec=cfg.ui_timeout_sec,
            temperature=cfg.temperature,
            num_predict=cfg.num_predict,
        )
    models = list_models(config=cfg, timeout=timeout)
    if models:
        return OllamaStatus(True, True, cfg.enabled, cfg.host, models, None)
    reason = "OLLAMA_API_UNAVAILABLE_OR_NO_MODELS"
    return OllamaStatus(False, False, cfg.enabled, cfg.host, (), reason)


__all__ = ["OllamaStatus", "ollama_status"]
