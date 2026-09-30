"""Ollama-backed signal rater for offline/shadow research.

This ports the common "AI analyst / committee" pattern used by trading agent
projects without giving the LLM execution authority.  It scores a candidate and
explains risk, but it never creates an entry.  If a future caller chooses to use
the result as a gate, it can only veto/slow down a deterministic candidate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from hl_observer.research.ollama_client import OllamaClientConfig, config_from_env, generate_json


SYSTEM_PROMPT = (
    "Tu es un comite IA local HyperSmart, uniquement en simulation paper Hyperliquid. "
    "Tu analyses des candidats deja produits par des regles deterministes. "
    "Tu ne peux jamais creer un signal, ouvrir, fermer, acheter, vendre, signer, connecter un wallet, "
    "ni promettre un PnL. Tu peux seulement noter la qualite, expliquer les risques et recommander "
    "un veto conservateur si les donnees sont faibles."
)


@dataclass(frozen=True, slots=True)
class OllamaSignalRaterConfig:
    enabled: bool = False
    host: str = "http://127.0.0.1:11434"
    model: str = "llama3.2"
    api_style: str = "auto"
    timeout_sec: float = 8.0
    min_ai_score: float = 0.62
    min_confidence: float = 0.55
    system_prompt: str = SYSTEM_PROMPT

    def client_config(self) -> OllamaClientConfig:
        base = config_from_env()
        return OllamaClientConfig(
            enabled=self.enabled,
            host=self.host,
            model=self.model,
            api_style=self.api_style,
            timeout_sec=self.timeout_sec,
            ui_timeout_sec=base.ui_timeout_sec,
            temperature=0.0,
            num_predict=500,
        )


@dataclass(frozen=True, slots=True)
class OllamaSignalRating:
    used_llm: bool
    source: str
    ai_score: float | None
    confidence: float | None
    veto_recommended: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    adjustments: tuple[str, ...] = field(default_factory=tuple)
    missing_data: tuple[str, ...] = field(default_factory=tuple)
    raw_text: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    hot_path: bool = False
    paper_only: bool = True
    can_create_trade: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def config_from_env_for_signal_rater() -> OllamaSignalRaterConfig:
    base = config_from_env()
    return OllamaSignalRaterConfig(
        enabled=base.enabled,
        host=base.host,
        model=base.model,
        api_style=base.api_style,
        timeout_sec=base.timeout_sec,
        min_ai_score=_env_float("HYPERSMART_V14_OLLAMA_MIN_AI_SCORE", 0.62),
        min_confidence=_env_float("HYPERSMART_V14_OLLAMA_MIN_CONFIDENCE", 0.55),
    )


def rate_signal_candidate(
    candidate: dict[str, Any],
    *,
    config: OllamaSignalRaterConfig | None = None,
) -> OllamaSignalRating:
    cfg = config or config_from_env_for_signal_rater()
    fallback = _rule_based_rating(candidate, cfg)
    if not cfg.enabled:
        return fallback

    prompt = _build_signal_prompt(candidate)
    data, result = generate_json(prompt, system=cfg.system_prompt, config=cfg.client_config(), timeout=cfg.timeout_sec)
    if not data:
        return OllamaSignalRating(
            used_llm=False,
            source="rules",
            ai_score=fallback.ai_score,
            confidence=fallback.confidence,
            veto_recommended=fallback.veto_recommended,
            reasons=fallback.reasons,
            adjustments=fallback.adjustments,
            missing_data=fallback.missing_data,
            warnings=result.warnings + ("OLLAMA_SIGNAL_RATER_UNAVAILABLE",),
        )

    score = _bounded_float(data.get("ai_score"))
    confidence = _bounded_float(data.get("confidence"))
    veto = bool(data.get("veto_recommended"))
    if score is None or confidence is None:
        veto = True
    if score is not None and score < cfg.min_ai_score:
        veto = True
    if confidence is not None and confidence < cfg.min_confidence:
        veto = True
    return OllamaSignalRating(
        used_llm=True,
        source="ollama",
        ai_score=score,
        confidence=confidence,
        veto_recommended=veto,
        reasons=_tuple_text(data.get("reasons")),
        adjustments=_tuple_text(data.get("adjustments")),
        missing_data=_tuple_text(data.get("missing_data")),
        raw_text=result.text,
    )


def _build_signal_prompt(candidate: dict[str, Any]) -> str:
    compact = {
        key: candidate.get(key)
        for key in (
            "coin",
            "side",
            "action_type",
            "edge_remaining_bps",
            "net_edge_bps",
            "copy_degradation_bps",
            "signal_age_ms",
            "consensus_wallets",
            "leader_score",
            "copyability_score",
            "liquidity_score",
            "spread_bps",
            "slippage_bps",
            "fee_bps",
            "reason",
            "decision_reason",
        )
    }
    return (
        "Analyse ce candidat paper local Hyperliquid. Retourne UNIQUEMENT un JSON avec: "
        "ai_score (0..1), confidence (0..1), veto_recommended (bool), reasons (liste), "
        "adjustments (liste), missing_data (liste). Le score mesure la qualite du candidat; "
        "un veto recommande de NE PAS simuler l'entree. Tu ne peux jamais recommander d'ouvrir "
        "une position. CANDIDATE="
        + repr(compact)
    )


def _rule_based_rating(candidate: dict[str, Any], cfg: OllamaSignalRaterConfig) -> OllamaSignalRating:
    reasons: list[str] = []
    missing: list[str] = []
    score = 0.5
    confidence = 0.45

    edge = _safe_float(candidate.get("edge_remaining_bps", candidate.get("net_edge_bps")))
    age_ms = _safe_float(candidate.get("signal_age_ms"))
    consensus = _safe_float(candidate.get("consensus_wallets")) or 0.0
    liquidity = _safe_float(candidate.get("liquidity_score"))
    degradation = _safe_float(candidate.get("copy_degradation_bps"))

    if edge is None:
        missing.append("edge_remaining_bps")
        score -= 0.2
    elif edge <= 0:
        reasons.append("edge net non positif")
        score -= 0.25
    else:
        score += min(0.25, edge / 120.0)

    if age_ms is None:
        missing.append("signal_age_ms")
        score -= 0.1
    elif age_ms > 15_000:
        reasons.append("signal trop vieux pour copie rapide")
        score -= 0.2
    else:
        score += 0.1

    if consensus >= 2:
        score += min(0.15, consensus * 0.03)
        confidence += 0.1
    else:
        reasons.append("consensus faible")

    if liquidity is None:
        missing.append("liquidity_score")
    elif liquidity < 0.3:
        reasons.append("liquidite faible")
        score -= 0.15

    if degradation is not None and degradation > 20:
        reasons.append("copie trop degradee")
        score -= 0.12

    score = max(0.0, min(1.0, score))
    confidence = max(0.0, min(1.0, confidence + score * 0.2))
    veto = score < cfg.min_ai_score or confidence < cfg.min_confidence
    return OllamaSignalRating(
        used_llm=False,
        source="rules",
        ai_score=score,
        confidence=confidence,
        veto_recommended=veto,
        reasons=tuple(reasons),
        adjustments=("augmenter edge minimum", "prioriser signaux plus frais") if veto else (),
        missing_data=tuple(missing),
        warnings=("OLLAMA_DISABLED_OR_UNAVAILABLE",),
    )


def _safe_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded_float(value: object) -> float | None:
    number = _safe_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def _tuple_text(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(item) for item in value if str(item).strip())
    except TypeError:
        return (str(value),)


def _env_float(name: str, default: float) -> float:
    import os

    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


__all__ = [
    "OllamaSignalRaterConfig",
    "OllamaSignalRating",
    "config_from_env_for_signal_rater",
    "rate_signal_candidate",
]
