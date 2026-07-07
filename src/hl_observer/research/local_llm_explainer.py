"""Local AI explainer for HyperSmart paper-simulation decisions.

The explainer has two layers:
- deterministic rules, always available and safe;
- optional local Ollama prose, only when enabled by the user.

Important boundary: this module is offline/research/dashboard only. It never
creates a PaperIntent, never creates an order, and never runs in the execution
hot path. When the local model hallucinates an asset, gives advice, or implies
guaranteed profit, the output falls back to deterministic rules.
"""

from __future__ import annotations

from hl_observer.research.ollama_client import (
    config_from_env as ollama_config_from_env,
    generate,
    ollama_available as ollama_client_available,
)

_REASON_FR = {
    "STALE_SIGNAL": "le signal \u00e9tait trop vieux",
    "OPPORTUNITY_STALE_SIGNAL": "le signal \u00e9tait trop vieux",
    "REJECT_TOO_LATE": "on serait entr\u00e9 trop tard",
    "EDGE_REMAINING_TOO_LOW": "la marge de gain \u00e9tait trop faible apr\u00e8s les frais",
    "REJECT_EDGE_NEGATIVE": "la marge de gain \u00e9tait n\u00e9gative apr\u00e8s les frais",
    "SINGLE_WALLET_EDGE_TOO_LOW": "un seul trader, signal pas assez fort",
    "LIQUIDITY_TOO_LOW": "le march\u00e9 n'\u00e9tait pas assez liquide",
    "COPY_DEGRADATION_TOO_HIGH": "copier ce trade co\u00fbtait trop cher",
    "PRICE_DEVIATION_TOO_HIGH": "le prix avait d\u00e9j\u00e0 trop boug\u00e9",
    "MAX_OPEN_PAPER_TRADES_REACHED": "trop de positions d\u00e9j\u00e0 ouvertes",
    "NO_MATCHING_PAPER_POSITION_FOR_CLOSE": "le leader fermait une position qu'on n'avait pas",
    "REJECT_MODEL_LOW_P": "le modele local jugeait la chance de gain trop faible",
    "EDGE_OK_FOR_LOCAL_SIMULATION": "marge nette positive, signal frais",
}


def rule_based_explanation(decision: dict) -> str:
    """Return a deterministic French explanation for one decision."""
    coin = str(decision.get("coin", "?")).upper()
    side = str(decision.get("side") or decision.get("direction") or "").upper()
    reason = str(decision.get("decision_reason") or decision.get("reason") or "")
    edge = decision.get("net_edge_bps", decision.get("edge_remaining_bps"))
    age = decision.get("signal_age_ms")
    cons = decision.get("consensus_wallets")
    accepted = reason == "EDGE_OK_FOR_LOCAL_SIMULATION"
    parts = [str(r) for r in reason.split("|") if r]
    why = " ; ".join(_REASON_FR.get(p, p) for p in parts) if parts else "raison inconnue"
    head = f"Trade {coin} {side} retenu" if accepted else f"Trade {coin} {side} \u00e9cart\u00e9"

    extra: list[str] = []
    if edge is not None:
        try:
            extra.append(f"marge {float(edge):.0f} bps")
        except (TypeError, ValueError):
            pass
    if age is not None:
        try:
            extra.append(f"signal {float(age) / 1000:.0f}s")
        except (TypeError, ValueError):
            pass
    if cons is not None:
        extra.append(f"{cons} trader(s) d'accord")
    tail = f" ({', '.join(extra)})" if extra else ""
    return f"{head} : {why}{tail}."


def ollama_available(*, host: str | None = None, timeout: float = 0.6) -> bool:
    cfg = ollama_config_from_env()
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
    return ollama_client_available(config=cfg, timeout=timeout)


def _ollama_generate(prompt: str, *, timeout: float = 8.0) -> str | None:
    result = generate(
        prompt,
        timeout=timeout,
        num_predict=220,
    )
    return result.text


def _safe_llm_explanation(text: str | None, *, coin: str) -> str | None:
    """Accept local LLM prose only when it stays anchored and non-promissory."""
    if not text:
        return None
    cleaned = " ".join(str(text).strip().split())
    if not cleaned:
        return None

    low = cleaned.lower()
    forbidden_fragments = (
        "bitcoin cash",
        "conseil financier",
        "recommandation d'investissement",
        "recommandation investissement",
        "rendement garanti",
        "profit garanti",
        "gain garanti",
        "benefice garanti",
        "bénéfice garanti",
        "realiser un profit",
        "réaliser un profit",
        "profit assure",
        "profit assuré",
        "gain assure",
        "gain assuré",
        "esperant qu",
        "espérant qu",
    )
    if any(fragment in low for fragment in forbidden_fragments):
        return None

    normalized_coin = str(coin or "").strip().upper()
    if normalized_coin and normalized_coin != "?" and normalized_coin not in cleaned.upper():
        return None
    return cleaned


def explain(decision: dict, *, use_llm: bool | None = None) -> dict:
    """Explain a paper-simulation decision without allowing LLM hot-path control."""
    base = rule_based_explanation(decision)
    coin = str(decision.get("coin", "?")).upper()
    want_llm = ollama_available() if use_llm is None else bool(use_llm)
    if want_llm:
        narrative = _ollama_generate(
            "Tu expliques une decision de simulation paper Hyperliquid, en lecture seule. "
            "Garde exactement le symbole d'actif fourni. N'invente aucun nom d'actif. "
            "Ne donne aucun conseil financier, aucune recommandation, aucune promesse de gain. "
            "Une seule phrase factuelle en francais. Decision: "
            f"{base}"
        )
        safe_narrative = _safe_llm_explanation(narrative, coin=coin)
        if safe_narrative:
            return {
                "text": safe_narrative,
                "source": "ollama",
                "llm_used": True,
                "rule_based": base,
                "context_only": True,
                "hot_path": False,
            }
    return {
        "text": base,
        "source": "regles",
        "llm_used": False,
        "rule_based": base,
        "context_only": True,
        "hot_path": False,
    }


__all__ = ["rule_based_explanation", "ollama_available", "explain"]
