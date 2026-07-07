"""Small local Ollama client used by HyperSmart research/offline explainers.

The trading/runtime hot path must not import or call this module.  It is for
background reports, dashboard explanations already cached on disk, and QA
diagnostics only.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.2"


@dataclass(frozen=True, slots=True)
class OllamaClientConfig:
    enabled: bool = False
    host: str = DEFAULT_HOST
    model: str = DEFAULT_MODEL
    api_style: str = "auto"
    timeout_sec: float = 8.0
    ui_timeout_sec: float = 2.0
    temperature: float = 0.1
    num_predict: int = 700

    @property
    def native_host(self) -> str:
        host = self.host.rstrip("/")
        if host.endswith("/v1"):
            return host[:-3].rstrip("/")
        return host

    @property
    def openai_host(self) -> str:
        host = self.host.rstrip("/")
        if host.endswith("/v1"):
            return host
        return host + "/v1"


@dataclass(frozen=True, slots=True)
class OllamaGenerateResult:
    text: str | None
    used_ollama: bool
    endpoint: str
    model: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def config_from_env() -> OllamaClientConfig:
    """Read the common local-LLM env contract used by several bot frameworks.

    HyperSmart-specific variables win, then common Ollama/OpenAI-compatible
    names are accepted so imported research tooling can be adapted without
    another config layer.
    """

    host = (
        os.environ.get("HYPERSMART_V13_OLLAMA_HOST")
        or os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_HOST")
        or os.environ.get("OPENAI_BASE_URL")
        or DEFAULT_HOST
    )
    model = (
        os.environ.get("HYPERSMART_V13_OLLAMA_MODEL")
        or os.environ.get("OLLAMA_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or DEFAULT_MODEL
    )
    return OllamaClientConfig(
        enabled=_env_bool("HYPERSMART_V13_OLLAMA_ENABLED", False),
        host=host,
        model=model,
        api_style=(os.environ.get("HYPERSMART_V13_OLLAMA_API_STYLE") or "auto").lower(),
        timeout_sec=_env_float("HYPERSMART_V13_OLLAMA_TIMEOUT_SEC", 8.0),
        ui_timeout_sec=_env_float("HYPERSMART_V13_OLLAMA_UI_TIMEOUT_SEC", 2.0),
        temperature=_env_float("HYPERSMART_V13_OLLAMA_TEMPERATURE", 0.1),
        num_predict=_env_int("HYPERSMART_V13_OLLAMA_NUM_PREDICT", 700),
    )


def list_models(*, config: OllamaClientConfig | None = None, timeout: float | None = None) -> tuple[str, ...]:
    cfg = config or config_from_env()
    try:
        with urllib.request.urlopen(cfg.native_host + "/api/tags", timeout=timeout or min(cfg.timeout_sec, 2.0)) as response:
            data = json.loads(response.read().decode("utf-8"))
        return tuple(str(m.get("name")) for m in data.get("models", []) if m.get("name"))
    except Exception:
        return ()


def ollama_available(*, config: OllamaClientConfig | None = None, timeout: float | None = None) -> bool:
    cfg = config or config_from_env()
    if not cfg.enabled:
        return False
    return bool(list_models(config=cfg, timeout=timeout or cfg.ui_timeout_sec))


def generate(
    prompt: str,
    *,
    system: str | None = None,
    config: OllamaClientConfig | None = None,
    timeout: float | None = None,
    json_mode: bool = False,
    num_predict: int | None = None,
) -> OllamaGenerateResult:
    cfg = config or config_from_env()
    if not cfg.enabled:
        return OllamaGenerateResult(None, False, "disabled", cfg.model, ("OLLAMA_DISABLED",))
    if cfg.api_style == "openai":
        return _generate_openai(prompt, system=system, config=cfg, timeout=timeout, json_mode=json_mode, num_predict=num_predict)
    if cfg.api_style == "native":
        return _generate_native(prompt, system=system, config=cfg, timeout=timeout, json_mode=json_mode, num_predict=num_predict)

    native = _generate_native(prompt, system=system, config=cfg, timeout=timeout, json_mode=json_mode, num_predict=num_predict)
    if native.text:
        return native
    openai = _generate_openai(prompt, system=system, config=cfg, timeout=timeout, json_mode=json_mode, num_predict=num_predict)
    if openai.text:
        return openai
    return OllamaGenerateResult(None, False, "auto", cfg.model, native.warnings + openai.warnings)


def generate_json(
    prompt: str,
    *,
    system: str | None = None,
    config: OllamaClientConfig | None = None,
    timeout: float | None = None,
) -> tuple[dict[str, Any] | None, OllamaGenerateResult]:
    result = generate(prompt, system=system, config=config, timeout=timeout, json_mode=True)
    if not result.text:
        return None, result
    try:
        return json.loads(result.text), result
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", result.text, flags=re.S)
        if not match:
            return None, OllamaGenerateResult(
                result.text,
                result.used_ollama,
                result.endpoint,
                result.model,
                result.warnings + ("OLLAMA_JSON_PARSE_FAILED",),
            )
        try:
            return json.loads(match.group(0)), result
        except json.JSONDecodeError:
            return None, OllamaGenerateResult(
                result.text,
                result.used_ollama,
                result.endpoint,
                result.model,
                result.warnings + ("OLLAMA_JSON_PARSE_FAILED",),
            )


def _generate_native(
    prompt: str,
    *,
    system: str | None,
    config: OllamaClientConfig,
    timeout: float | None,
    json_mode: bool,
    num_predict: int | None,
) -> OllamaGenerateResult:
    payload: dict[str, Any] = {
        "model": config.model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": config.temperature,
            "num_predict": num_predict or config.num_predict,
        },
    }
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"
    try:
        req = urllib.request.Request(
            config.native_host + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout or config.timeout_sec) as response:
            data = json.loads(response.read().decode("utf-8"))
        return OllamaGenerateResult(str(data.get("response") or "").strip() or None, True, "native", config.model)
    except Exception as exc:
        return OllamaGenerateResult(None, False, "native", config.model, (f"OLLAMA_NATIVE_ERROR:{exc.__class__.__name__}",))


def _generate_openai(
    prompt: str,
    *,
    system: str | None,
    config: OllamaClientConfig,
    timeout: float | None,
    json_mode: bool,
    num_predict: int | None,
) -> OllamaGenerateResult:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "temperature": config.temperature,
        "max_tokens": num_predict or config.num_predict,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        req = urllib.request.Request(
            config.openai_host + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout or config.timeout_sec) as response:
            data = json.loads(response.read().decode("utf-8"))
        choices = data.get("choices") or []
        text = ""
        if choices:
            text = str((choices[0].get("message") or {}).get("content") or "")
        return OllamaGenerateResult(text.strip() or None, True, "openai", config.model)
    except Exception as exc:
        return OllamaGenerateResult(None, False, "openai", config.model, (f"OLLAMA_OPENAI_ERROR:{exc.__class__.__name__}",))


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_MODEL",
    "OllamaClientConfig",
    "OllamaGenerateResult",
    "config_from_env",
    "generate",
    "generate_json",
    "list_models",
    "ollama_available",
]
