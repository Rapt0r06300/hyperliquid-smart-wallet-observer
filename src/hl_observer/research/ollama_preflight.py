"""Preflight checks for the local Ollama research advisor."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from hl_observer.research.ollama_client import config_from_env, generate, list_models


@dataclass(frozen=True, slots=True)
class OllamaPreflight:
    ok: bool
    enabled: bool
    host: str
    model: str
    models: tuple[str, ...] = field(default_factory=tuple)
    native_generate_ok: bool = False
    openai_compatible_configured: bool = False
    hot_path: bool = False
    paper_only: bool = True
    can_create_trade: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_ollama_preflight(*, probe: bool = True) -> OllamaPreflight:
    cfg = config_from_env()
    warnings: list[str] = []
    models = list_models(config=cfg)
    if not cfg.enabled:
        warnings.append("OLLAMA_DISABLED_BY_ENV")
    if not models:
        warnings.append("OLLAMA_NO_MODELS_OR_API_DOWN")
    model_names = {m.split(":")[0] for m in models} | set(models)
    if models and cfg.model not in model_names and f"{cfg.model}:latest" not in models:
        warnings.append("OLLAMA_CONFIGURED_MODEL_NOT_LISTED")

    native_ok = False
    if probe and cfg.enabled and models:
        quick = generate(
            "Reponds uniquement: OK",
            config=cfg,
            timeout=min(cfg.ui_timeout_sec, 2.5),
            num_predict=8,
        )
        native_ok = bool(quick.text)
        if not native_ok:
            warnings.extend(quick.warnings)

    ok = cfg.enabled and bool(models) and (native_ok if probe else True)
    return OllamaPreflight(
        ok=ok,
        enabled=cfg.enabled,
        host=cfg.host,
        model=cfg.model,
        models=models,
        native_generate_ok=native_ok,
        openai_compatible_configured=True,
        warnings=tuple(dict.fromkeys(warnings)),
    )


__all__ = ["OllamaPreflight", "run_ollama_preflight"]
