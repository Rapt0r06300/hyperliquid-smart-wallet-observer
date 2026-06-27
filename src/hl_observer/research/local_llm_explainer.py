"""V13 #156 — Couche IA locale GRATUITE (Ollama optionnel) — explainer OFFLINE.

Explique en français simple POURQUOI une décision a été prise (ou refusée) et résume une
session. Deux niveaux, tous deux GRATUITS :
  * règles (toujours dispo, déterministe, aucune dépendance, aucun réseau) ;
  * Ollama LOCAL (optionnel) pour une formulation plus naturelle, UNIQUEMENT si l'utilisateur
    l'active (HYPERSMART_V13_OLLAMA_ENABLED=1) et qu'il tourne sur sa machine.
RÈGLE: recherche/offline UNIQUEMENT — jamais dans le chemin de décision (no LLM hot-path),
jamais d'API payante, dégradation gracieuse (si Ollama absent -> on garde le texte règles).
"""

from __future__ import annotations

import json
import os

_REASON_FR = {
    "STALE_SIGNAL": "le signal était trop vieux",
    "OPPORTUNITY_STALE_SIGNAL": "le signal était trop vieux",
    "REJECT_TOO_LATE": "on serait entré trop tard",
    "EDGE_REMAINING_TOO_LOW": "la marge de gain était trop faible après les frais",
    "REJECT_EDGE_NEGATIVE": "la marge de gain était négative après les frais",
    "SINGLE_WALLET_EDGE_TOO_LOW": "un seul trader, signal pas assez fort",
    "LIQUIDITY_TOO_LOW": "le marché n'était pas assez liquide",
    "COPY_DEGRADATION_TOO_HIGH": "copier ce trade coûtait trop cher (dégradation)",
    "PRICE_DEVIATION_TOO_HIGH": "le prix avait déjà trop bougé",
    "MAX_OPEN_PAPER_TRADES_REACHED": "trop de positions déjà ouvertes",
    "NO_MATCHING_PAPER_POSITION_FOR_CLOSE": "le leader fermait une position qu'on n'avait pas",
    "REJECT_MODEL_LOW_P": "l'IA jugeait la chance de gain trop faible",
    "EDGE_OK_FOR_LOCAL_SIMULATION": "marge nette positive, signal frais",
}


def rule_based_explanation(decision: dict) -> str:
    """Phrase claire, déterministe, sans IA — toujours disponible et gratuite."""
    coin = str(decision.get("coin", "?")).upper()
    side = str(decision.get("side") or decision.get("direction") or "").upper()
    reason = str(decision.get("decision_reason") or decision.get("reason") or "")
    edge = decision.get("net_edge_bps", decision.get("edge_remaining_bps"))
    age = decision.get("signal_age_ms")
    cons = decision.get("consensus_wallets")
    accepted = reason == "EDGE_OK_FOR_LOCAL_SIMULATION"
    parts = [str(r) for r in reason.split("|") if r]
    why = " ; ".join(_REASON_FR.get(p, p) for p in parts) if parts else "raison inconnue"
    head = (f"Trade {coin} {side} retenu" if accepted else f"Trade {coin} {side} écarté")
    extra = []
    if edge is not None:
        try:
            extra.append(f"marge {float(edge):.0f} bps")
        except (TypeError, ValueError):
            pass
    if age is not None:
        try:
            extra.append(f"signal {float(age)/1000:.0f}s")
        except (TypeError, ValueError):
            pass
    if cons is not None:
        extra.append(f"{cons} trader(s) d'accord")
    tail = (" (" + ", ".join(extra) + ")") if extra else ""
    return f"{head} : {why}{tail}."


def ollama_available(*, host: str | None = None, timeout: float = 0.6) -> bool:
    if str(os.environ.get("HYPERSMART_V13_OLLAMA_ENABLED", "")).lower() not in {"1", "true", "yes", "on"}:
        return False
    url = (host or os.environ.get("HYPERSMART_V13_OLLAMA_HOST") or "http://127.0.0.1:11434") + "/api/tags"
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:   # localhost only, opt-in
            return r.status == 200
    except Exception:
        return False


def _ollama_generate(prompt: str, *, timeout: float = 8.0) -> str | None:
    host = os.environ.get("HYPERSMART_V13_OLLAMA_HOST") or "http://127.0.0.1:11434"
    model = os.environ.get("HYPERSMART_V13_OLLAMA_MODEL") or "llama3.2"
    try:
        import urllib.request
        data = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
        req = urllib.request.Request(host + "/api/generate", data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return (json.loads(r.read().decode("utf-8")) or {}).get("response")
    except Exception:
        return None


def explain(decision: dict, *, use_llm: bool | None = None) -> dict:
    """Explication offline. Toujours une phrase règles ; Ollama l'enrichit si dispo (opt-in)."""
    base = rule_based_explanation(decision)
    want_llm = ollama_available() if use_llm is None else bool(use_llm)
    if want_llm:
        narrative = _ollama_generate(
            "En une phrase simple et en français, explique cette décision de copy-trading "
            f"(aucun conseil financier) : {base}")
        if narrative:
            return {"text": narrative.strip(), "source": "ollama", "llm_used": True,
                    "rule_based": base, "context_only": True, "hot_path": False}
    return {"text": base, "source": "regles", "llm_used": False,
            "rule_based": base, "context_only": True, "hot_path": False}


__all__ = ["rule_based_explanation", "ollama_available", "explain"]
