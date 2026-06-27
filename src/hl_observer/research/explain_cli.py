"""V13 #156 (wiring) — génère les explications de décisions et les écrit dans un cache JSON.

Tourne en ARRIÈRE-PLAN (boucle d'entraînement), donc un appel Ollama lent ne bloque jamais
le dashboard. L'endpoint read-only /api/v12/panels lit ce cache et l'affiche. Offline :
règles toujours, Ollama seulement si HYPERSMART_V13_OLLAMA_ENABLED=1 et présent localement.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from hl_observer.research.local_llm_explainer import explain, ollama_available


def build_explanations_from_events(events: list[dict], *, limit: int = 8) -> dict:
    seq = sorted(events or [], key=lambda e: int(e.get("observed_at_ms") or 0), reverse=True)
    items: list[dict] = []
    seen: set[str] = set()
    for ev in seq:
        coin = str(ev.get("coin") or "?")
        side = str(ev.get("leader_side") or ev.get("side") or "")
        reason = str(ev.get("decision_reason") or ev.get("reason") or "")
        key = f"{coin}|{side}|{reason}"
        if not reason or key in seen:
            continue
        seen.add(key)
        ex = explain({"coin": coin, "side": side, "decision_reason": reason,
                      "net_edge_bps": ev.get("edge_remaining_bps"),
                      "signal_age_ms": ev.get("signal_age_ms"),
                      "consensus_wallets": ev.get("consensus_wallets")})
        items.append({"coin": coin, "side": side, "reason": reason,
                      "text": ex["text"], "source": ex["source"]})
        if len(items) >= limit:
            break
    narrative = None
    if items and ollama_available():
        from hl_observer.research.local_llm_explainer import _ollama_generate
        joined = " | ".join(i["text"] for i in items[:5])
        narrative = _ollama_generate(
            "Résume en 2 phrases simples, en français, ce que le bot de copy-trading vient de "
            f"faire et pourquoi (aucun conseil financier) : {joined}")
        if narrative:
            narrative = narrative.strip()
    return {"generated_at": int(time.time()), "items": items,
            "ollama_narrative": narrative, "ollama_enabled": ollama_available()}


def run(*, snapshot: str, out: str) -> dict:
    try:
        snap = json.load(open(snapshot, encoding="utf-8"))
    except Exception:
        snap = {}
    events = (snap.get("bot_simulation") or {}).get("events") or []
    payload = build_explanations_from_events(events)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Génère les explications de décisions (offline).")
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out", default="runtime/ml/explanations_latest.json")
    a = ap.parse_args(argv)
    rep = run(snapshot=a.snapshot, out=a.out)
    print(json.dumps({"items": len(rep["items"]), "ollama": rep["ollama_enabled"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
