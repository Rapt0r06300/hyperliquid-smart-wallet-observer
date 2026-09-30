"""ALPHA N — REPLAY = FORWARD : UN SEUL pipeline canonique end-to-end, utilisé À L'IDENTIQUE en replay
(batch rejoué) et en forward (streaming live). Le résultat ne dépend PAS du mode.

Chaîne : CanonicalEvent → state → signal → gate → PaperIntent → CausalExec → Fill → Ledger → Scoreboard.

Ne DUPLIQUE rien : réutilise `ops.paper_canonique` (PaperIntent = contrat d'intention unique, strategie_autorisee
= gate de scope, remplir_partiellement = fill causal sans look-ahead) et applique la MÊME politique de filtrage
causal que `research.replay_consistency` (dédup / hors-ordre / carnet périmé), mais en streaming. Les vérificateurs
`replay_consistency.deterministe / prefix_stable` prouvent l'invariant replay=forward.

Sécurité : `PaperIntent` et `remplir_partiellement` sont paper_only (real_execution=False). 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.ops.paper_canonique import (
    PaperIntent, ScopeViolation, remplir_partiellement, strategie_autorisee,
)

_REQUIS = ("seq", "ts_ms", "coin", "mid")


class PipelineCanonique:
    """Exécuteur causal, incrémental. `consommer(event)` traite UN événement (forward) ; `rejouer` boucle
    exactement sur la même méthode (replay). Aucune décision ne dépend du futur (prefix-stable par construction)."""

    def __init__(self, *, notional_usd: float = 500.0, seuil_net_bps: float = 0.0, fee_bps: float = 9.0,
                 book_max_age_ms: float = 5000.0) -> None:
        self.notional_usd = float(notional_usd)
        self.seuil = float(seuil_net_bps)
        self.fee_bps = float(fee_bps)
        self.book_max_age_ms = float(book_max_age_ms)
        self._mid: dict[str, tuple[int, float]] = {}
        self._vus: set[Any] = set()
        self._dernier_seq: Any = None
        self.decisions: list[dict[str, Any]] = []
        self._net_total = 0.0
        self._n_events = 0
        self._n_intents = 0
        self._n_fills = 0
        self._fill_ratios: list[float] = []

    # ── CanonicalEvent : champs requis présents + seq numérique (sinon SCHEMA, jamais exploité en douce) ──
    def _canonical(self, e: Mapping[str, Any]) -> dict[str, Any] | None:
        seq = e.get("seq")
        if any(e.get(c) is None for c in _REQUIS) or isinstance(seq, bool) or not isinstance(seq, (int, float)):
            return None
        return {"seq": seq, "ts_ms": int(e["ts_ms"]), "coin": str(e["coin"]).upper(), "mid": float(e["mid"]),
                "book_ts_ms": e.get("book_ts_ms"), "strategy": e.get("strategy"), "side": e.get("side"),
                "edge_bps": e.get("edge_bps"), "book": e.get("book"), "depth": e.get("depth")}

    # ── même politique causale que replay_consistency.filtre_evenements, en streaming ──
    def _causal(self, c: Mapping[str, Any]) -> tuple[str, bool]:
        s = c["seq"]
        if s in self._vus:
            return ("DUPLICATE", False)
        if self._dernier_seq is not None and s < self._dernier_seq:
            return ("ORDERING", False)
        if c["book_ts_ms"] is not None and (c["ts_ms"] - float(c["book_ts_ms"])) > self.book_max_age_ms:
            return ("STALE", False)
        return ("OK", True)

    def _log(self, d: dict[str, Any]) -> dict[str, Any]:
        self.decisions.append(d)
        return d

    def consommer(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """FORWARD : traite UN événement. `rejouer` appelle exactement cette méthode (⇒ replay=forward)."""
        self._n_events += 1
        c = self._canonical(event)
        if c is None:
            return self._log({"seq": event.get("seq"), "decision": "NO_TRADE", "raison": "SCHEMA"})
        label, ok = self._causal(c)
        if not ok:                                             # doublon/hors-ordre/périmé : n'altère pas l'état
            return self._log({"seq": c["seq"], "decision": "NO_TRADE", "raison": label})
        self._vus.add(c["seq"])
        self._dernier_seq = c["seq"] if self._dernier_seq is None else max(self._dernier_seq, c["seq"])
        self._mid[c["coin"]] = (c["ts_ms"], c["mid"])          # state
        # signal : requiert strategy + side ±1 + edge_bps ; sinon événement de marché pur (state only)
        if c["strategy"] is None or c["side"] not in (1, -1) or not isinstance(c["edge_bps"], (int, float)):
            return self._log({"seq": c["seq"], "decision": "MARKET", "raison": "pas de signal"})
        net_attendu = float(c["edge_bps"]) - self.fee_bps
        # gate : scope actif + edge net > seuil
        if not strategie_autorisee(c["strategy"]):
            return self._log({"seq": c["seq"], "decision": "NO_TRADE", "raison": "SCOPE"})
        if net_attendu <= self.seuil:
            return self._log({"seq": c["seq"], "decision": "NO_TRADE", "raison": "EDGE_TROP_FAIBLE",
                              "net_bps": round(net_attendu, 4)})
        # PaperIntent : contrat unique (refuse hors scope au point d'émission)
        try:
            intent = PaperIntent(strategy=c["strategy"], coin=c["coin"], side=int(c["side"]),
                                 notional_usd=self.notional_usd, signal_observable_at_ms=c["ts_ms"])
        except (ScopeViolation, ValueError) as exc:
            return self._log({"seq": c["seq"], "decision": "NO_TRADE", "raison": "INTENT_REFUSE:%s" % type(exc).__name__})
        self._n_intents += 1
        # CausalExec / Fill : marche le carnet de l'événement (aucun look-ahead)
        niveaux = c["book"] or [(c["mid"], float(c["depth"]) if c["depth"] is not None else self.notional_usd)]
        fill = remplir_partiellement(self.notional_usd, niveaux)
        fr = fill["fill_ratio"] or 0.0
        if fr <= 0:
            return self._log({"seq": c["seq"], "decision": "NO_FILL", "raison": "LIQUIDITE"})
        self._n_fills += 1
        self._fill_ratios.append(fr)
        net_realise = fr * net_attendu                         # Ledger : net réalisé ∝ fill ratio
        self._net_total += net_realise
        return self._log({"seq": c["seq"], "decision": "FILL", "strategy": c["strategy"], "coin": c["coin"],
                          "side": int(c["side"]), "fill_ratio": round(fr, 6), "net_bps": round(net_realise, 4),
                          "intent": intent.as_dict()})

    def scoreboard(self) -> dict[str, Any]:
        fr = (sum(self._fill_ratios) / len(self._fill_ratios)) if self._fill_ratios else None
        return {"n_events": self._n_events, "n_intents": self._n_intents, "n_fills": self._n_fills,
                "net_bps_total": round(self._net_total, 4),
                "net_bps_moyen": (round(self._net_total / self._n_fills, 4) if self._n_fills else None),
                "fill_ratio_moyen": (round(fr, 6) if fr is not None else None),
                "equity": round(1.0 + self._net_total / 1e4, 8)}


def executer_forward(events: Sequence[Mapping[str, Any]], **kw: Any) -> PipelineCanonique:
    """FORWARD : les événements arrivent un par un (streaming live)."""
    p = PipelineCanonique(**kw)
    for e in events:
        p.consommer(e)
    return p


def executer_replay(events: Sequence[Mapping[str, Any]], **kw: Any) -> PipelineCanonique:
    """REPLAY : mêmes événements rejoués. MÊME classe, MÊME méthode `consommer` ⇒ MÊME scoreboard."""
    return executer_forward(list(events), **kw)


__all__ = ["PipelineCanonique", "executer_forward", "executer_replay"]
