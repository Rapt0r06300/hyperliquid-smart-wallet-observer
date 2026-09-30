"""Local Ollama advisor for offline paper-simulation diagnostics.

Ported pattern from local-LLM trading repos:
  - configurable provider/endpoint/model;
  - OpenAI-compatible and native Ollama endpoints are supported conceptually;
  - model gives research recommendations only;
  - never in the hot path, never emits a PaperIntent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from hl_observer.research.ollama_client import (
    OllamaClientConfig,
    config_from_env as client_config_from_env,
    generate,
    generate_json,
)

SYSTEM_PROMPT = (
    "Tu es un analyste offline HyperSmart. Tu analyses uniquement une simulation paper locale Hyperliquid. "
    "Tu ne peux pas ouvrir, fermer, acheter, vendre, signer, connecter un wallet ou appeler une API de trading. "
    "Tu dois expliquer les pertes/refus, proposer des reglages de recherche et signaler les donnees manquantes."
)


@dataclass(frozen=True, slots=True)
class OllamaAdvisorConfig:
    enabled: bool = False
    host: str = "http://127.0.0.1:11434"
    model: str = "llama3.2"
    timeout_sec: float = 10.0
    api_style: str = "auto"
    system_prompt: str = SYSTEM_PROMPT

    def client_config(self) -> OllamaClientConfig:
        base = client_config_from_env()
        return OllamaClientConfig(
            enabled=self.enabled,
            host=self.host,
            model=self.model,
            api_style=self.api_style,
            timeout_sec=self.timeout_sec,
            ui_timeout_sec=base.ui_timeout_sec,
            temperature=base.temperature,
            num_predict=base.num_predict,
        )


@dataclass(frozen=True, slots=True)
class OllamaAdvisorResult:
    text: str
    used_llm: bool
    source: str
    warnings: tuple[str, ...] = field(default_factory=tuple)
    hot_path: bool = False
    paper_only: bool = True
    external_action: bool = False


def config_from_env() -> OllamaAdvisorConfig:
    client = client_config_from_env()
    return OllamaAdvisorConfig(
        enabled=client.enabled,
        host=client.host,
        model=client.model,
        timeout_sec=client.timeout_sec,
        api_style=client.api_style,
    )


def build_loss_advisor_prompt(summary: dict[str, object]) -> str:
    compact = json.dumps(summary, ensure_ascii=False, sort_keys=True)[:6_000]
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "Voici le resume technique JSON d'une session paper. "
        "Retourne en francais: 1) causes probables des pertes, 2) seuils a durcir, "
        "3) donnees manquantes, 4) tests/backtests a lancer. "
        "Ne promets jamais de PnL positif.\n\n"
        f"SESSION_JSON={compact}"
    )


def advise_from_summary(summary: dict[str, object], *, config: OllamaAdvisorConfig | None = None) -> OllamaAdvisorResult:
    cfg = config or config_from_env()
    prompt = build_loss_advisor_prompt(summary)
    fallback = _rule_based_advice(summary)
    if not cfg.enabled:
        return OllamaAdvisorResult(fallback, False, "rules", ("OLLAMA_DISABLED",))
    text = _ollama_generate(prompt, config=cfg)
    if not text:
        return OllamaAdvisorResult(fallback, False, "rules", ("OLLAMA_UNAVAILABLE",))
    return OllamaAdvisorResult(text.strip(), True, "ollama")


def advise_json_from_summary(summary: dict[str, object], *, config: OllamaAdvisorConfig | None = None) -> dict[str, object]:
    """Return a bounded structured advisor payload for logs/dashboard.

    The payload is advisory only.  It cannot create or approve a paper trade.
    """

    cfg = config or config_from_env()
    fallback = {
        "mode": "rules",
        "used_llm": False,
        "diagnosis": _rule_based_advice(summary),
        "recommended_adjustments": [],
        "missing_data": [],
        "safety": "offline_research_only_no_action",
    }
    if not cfg.enabled:
        fallback["warnings"] = ["OLLAMA_DISABLED"]
        return fallback
    prompt = (
        build_loss_advisor_prompt(summary)
        + "\n\nRetourne uniquement un JSON avec les cles: diagnosis, recommended_adjustments, "
        "missing_data, tests_to_run, risk_notes. Chaque valeur doit etre courte."
    )
    data, result = generate_json(prompt, system=cfg.system_prompt, config=cfg.client_config(), timeout=cfg.timeout_sec)
    if not data:
        fallback["warnings"] = list(result.warnings or ("OLLAMA_UNAVAILABLE",))
        return fallback
    return {
        "mode": "ollama",
        "used_llm": True,
        "model": cfg.model,
        "endpoint": result.endpoint,
        "diagnosis": str(data.get("diagnosis") or ""),
        "recommended_adjustments": data.get("recommended_adjustments") or [],
        "missing_data": data.get("missing_data") or [],
        "tests_to_run": data.get("tests_to_run") or [],
        "risk_notes": data.get("risk_notes") or [],
        "safety": "offline_research_only_no_action",
    }


def _ollama_generate(prompt: str, *, config: OllamaAdvisorConfig) -> str | None:
    result = generate(
        prompt,
        system=config.system_prompt,
        config=config.client_config(),
        timeout=config.timeout_sec,
    )
    return result.text


def _rule_based_advice(summary: dict[str, object]) -> str:
    reasons = summary.get("reason_counts") or summary.get("top_refusal_reasons") or {}
    pnl = float(summary.get("net_pnl_usdc") or summary.get("pnl_usdt") or 0.0)
    hints: list[str] = []
    if pnl < 0:
        hints.append("PNL negatif: reduire taille, renforcer edge net et verifier frais/slippage.")
    text = json.dumps(reasons, ensure_ascii=False).upper()
    if "STALE" in text or "TOO_LATE" in text:
        hints.append("Beaucoup de signaux trop vieux: prioriser flux WS, horodatage, cache marche court et rejet apres seuil.")
    if "EDGE" in text:
        hints.append("Edge insuffisant: augmenter margin-of-safety et refuser si couts > edge.")
    if "LIQUID" in text or "SLIPPAGE" in text:
        hints.append("Liquidite/slippage: baisser taille et exiger profondeur multi-niveaux.")
    if not hints:
        hints.append("Pas assez de donnees: collecter plus de decisions paper et verifier source health.")
    return " ".join(hints) + " Analyse offline uniquement; aucune action reelle."


__all__ = [
    "OllamaAdvisorConfig",
    "OllamaAdvisorResult",
    "advise_json_from_summary",
    "advise_from_summary",
    "build_loss_advisor_prompt",
    "config_from_env",
]
