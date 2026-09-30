"""DÉCIDER À L'ARRIVÉE DU FILL, PAS À LA FIN DU CYCLE (2026-07-11). Phase 4 + 15 du brief.

LE PROBLÈME, MESURÉ.

Le firehose WebSocket multiplexé **est allumé** et stocke chaque fill de leader en **sub-seconde**.
Puis... plus rien. La DÉCISION n'a lieu qu'à la **fin de la boucle de poll** :

    cycle median 30,6 s   |   p95 50,4 s   |   max 106,1 s

Le signal arrive en 200 ms et attend 30 secondes qu'on daigne le regarder. **Le hot path est
prisonnier du cold path.** Aucun réglage de seuil ne corrigera ça : le signal est déjà mort quand
on l'examine.

CE MODULE : la décision est déclenchée **par l'événement**, pas par le tic de la boucle.

    fill arrive -> dedupe -> features -> gates -> décision -> intention paper
                   (le tout mesuré à l'horloge MONOTONE, étape par étape)

MODE SHADOW PAR DÉFAUT -- ET CE N'EST PAS DE LA TIMIDITÉ.

Ce décideur **n'ouvre aucune position**. Il observe les MÊMES événements que l'ancien chemin,
décide immédiatement, et **enregistre ce qu'il aurait fait**. On compare ensuite, sur les mêmes
données, ce que les deux auraient decide. C'est la seule façon de savoir si le nouveau chemin est
meilleur **avant** de lui confier quoi que ce soit.

Changer le pipeline ET le comportement en même temps rendrait impossible de savoir lequel des deux
a change le resultat. Le brief l'interdit, et il a raison.

PUR (la boucle est injectée). Aucun ordre réel, jamais.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from hl_observer.runtime.bounded_event_queue import BoundedEventQueue, Event
from hl_observer.runtime.latency_trace import LatencyTrace
from hl_observer.signals.decision_contract import verifier_contrat

ENV_ACTIF = "HYPERSMART_EVENT_DRIVEN_DECIDER"        # defaut OFF : shadow uniquement
ENV_AUTORITAIRE = "HYPERSMART_EVENT_DRIVEN_AUTHORITATIVE"   # JAMAIS actif sans preuve A/B

# Les seuls evenements qui declenchent une decision. Un snapshot de prix ne DECIDE rien --
# il met a jour l'etat. Confondre les deux, c'est re-decider 1 000 fois par seconde pour rien.
DECLENCHEURS = frozenset({"userFill", "user_fill", "fill",
                          "leader_open", "leader_add", "leader_reduce", "leader_close"})


def _vrai(nom: str, defaut: str = "0") -> bool:
    return str(os.environ.get(nom, defaut)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class ShadowDecision:
    """Ce que le nouveau chemin AURAIT fait -- et en combien de temps."""

    event_id: str
    coin: str
    side: str
    decision: str                       # ACCEPT_SHADOW | NO_TRADE
    reason_codes: tuple[str, ...]
    # LES DEUX HORLOGES, SEPAREES (cf. latency_trace : ne jamais les additionner)
    source_age_ms: float | None
    local_processing_ms: float | None
    stage_durations_ms: dict[str, float] = field(default_factory=dict)
    real_execution: bool = False        # invariant : ce chemin n'execute JAMAIS

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "coin": self.coin, "side": self.side,
            "decision": self.decision, "reason_codes": list(self.reason_codes),
            "source_age_ms": self.source_age_ms,
            "local_processing_ms": self.local_processing_ms,
            "stage_durations_ms": self.stage_durations_ms,
            "shadow_only": True, "real_execution": False,
        }


@dataclass(slots=True)
class ShadowStats:
    evenements_recus: int = 0
    declencheurs: int = 0
    decisions: int = 0
    acceptes: int = 0
    refuses: int = 0
    ignores_non_declencheurs: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "evenements_recus": self.evenements_recus,
            "declencheurs": self.declencheurs,
            "decisions": self.decisions,
            "acceptes": self.acceptes,
            "refuses": self.refuses,
            "ignores_non_declencheurs": self.ignores_non_declencheurs,
        }


class EventDrivenDecider:
    """Décide À L'ARRIVÉE de l'événement. En SHADOW : n'ouvre jamais rien.

    `construire_preuve` : Event -> dict de preuve (le contrat de données, Phase 6).
    C'est injecté, donc ce module reste PUR et testable sans serveur, sans réseau, sans DB.
    """

    def __init__(
        self,
        *,
        construire_preuve: Callable[[Event], Mapping[str, Any]],
        queue: BoundedEventQueue | None = None,
    ) -> None:
        self.queue = queue or BoundedEventQueue(max_size=10_000)
        self._construire_preuve = construire_preuve
        self.stats = ShadowStats()
        self.decisions: list[ShadowDecision] = []

    # ------------------------------------------------------------------ le hot path

    def on_event(self, event: Event) -> ShadowDecision | None:
        """LE CŒUR. Appelé DÈS que l'événement arrive -- pas a la fin d'un cycle de 30 s."""
        self.stats.evenements_recus += 1

        sort = self.queue.push(event)
        if sort == "DUPLICATE":
            return None                  # un snapshot rejoue n'est pas un fill neuf

        if event.event_type not in DECLENCHEURS:
            self.stats.ignores_non_declencheurs += 1
            return None                  # un prix met a jour l'etat ; il ne DECIDE pas

        self.stats.declencheurs += 1

        trace = LatencyTrace(
            event_id=event.event_id, coin=str(event.payload.get("coin") or ""),
            source=event.event_type, source_event_time_ms=event.event_time_ms,
        ).start()

        trace.stamp("decode")
        trace.stamp("normalize")
        trace.stamp("dedupe")
        trace.stamp("state_update")

        preuve = dict(self._construire_preuve(event))
        trace.stamp("features")
        trace.stamp("signal")
        trace.stamp("score")

        # LE MEME contrat que le chemin de production : un champ manquant -> NO_TRADE.
        # (le nouveau chemin ne doit PAS etre plus laxiste que l'ancien -- ce serait tricher)
        verdict = verifier_contrat(preuve)
        trace.stamp("gates")

        if not verdict.complet:
            decision, motifs = "NO_TRADE", verdict.reason_codes
        elif preuve.get("edge_is_empirical") is not True:
            decision, motifs = "NO_TRADE", ("EDGE_NOT_EMPIRICAL",)
        else:
            decision, motifs = "ACCEPT_SHADOW", tuple(verdict.reason_codes)

        trace.stamp("decision")
        trace.stamp("intent")

        d = ShadowDecision(
            event_id=event.event_id,
            coin=str(preuve.get("coin") or event.payload.get("coin") or ""),
            side=str(preuve.get("side") or ""),
            decision=decision,
            reason_codes=motifs,
            source_age_ms=trace.source_age_ms(),
            local_processing_ms=trace.local_processing_ms(),
            stage_durations_ms=trace.stage_durations_ms(),
        )
        self.decisions.append(d)
        self.stats.decisions += 1
        if decision == "ACCEPT_SHADOW":
            self.stats.acceptes += 1
        else:
            self.stats.refuses += 1
        return d

    def run(self, events: Iterable[Event]) -> list[ShadowDecision]:
        return [d for e in events if (d := self.on_event(e)) is not None]

    # ------------------------------------------------------------------ garde-fous

    @staticmethod
    def actif() -> bool:
        return _vrai(ENV_ACTIF, "0")

    @staticmethod
    def autoritaire() -> bool:
        """**FAUX tant qu'une comparaison A/B n'a pas prouve que le nouveau chemin est meilleur.**

        Un decideur qui n'a jamais ete compare a l'ancien n'a AUCUN droit d'ouvrir une position,
        aussi elegant soit son code.
        """
        return _vrai(ENV_ACTIF, "0") and _vrai(ENV_AUTORITAIRE, "0")


# ---------------------------------------------------------------------- la comparaison A/B


def comparer(
    ancien: Iterable[Mapping[str, Any]],
    nouveau: Iterable[ShadowDecision],
) -> dict[str, Any]:
    """ANCIEN vs NOUVEAU, sur les MÊMES événements. C'est la seule preuve qui vaille.

    Sans cette comparaison, "le nouveau pipeline est plus rapide" n'est qu'une intuition --
    et une intuition ne se met pas en production.
    """
    a = {str(d.get("event_id")): d for d in ancien}
    n = {d.event_id: d for d in nouveau}
    communs = sorted(set(a) & set(n))

    lignes: list[dict[str, Any]] = []
    divergences = 0
    gains_ms: list[float] = []

    for eid in communs:
        va, vn = a[eid], n[eid]
        dec_a = str(va.get("decision") or "")
        dec_n = vn.decision
        diverge = (dec_a == "ACCEPT") != (dec_n == "ACCEPT_SHADOW")
        if diverge:
            divergences += 1

        age_a = va.get("signal_age_ms")
        age_n = vn.source_age_ms
        if isinstance(age_a, (int, float)) and age_n is not None:
            gains_ms.append(float(age_a) - float(age_n))

        lignes.append({
            "event_id": eid,
            "old_decision": dec_a, "new_decision": dec_n,
            "old_signal_age_ms": age_a, "new_signal_age_ms": age_n,
            "new_local_processing_ms": vn.local_processing_ms,
            "divergence": diverge,
            "divergence_reason": (
                f"old={dec_a} new={dec_n} ({', '.join(vn.reason_codes) or 'sans motif'})"
                if diverge else ""
            ),
        })

    return {
        "evenements_communs": len(communs),
        "divergences": divergences,
        "taux_divergence": (round(divergences / len(communs), 4) if communs else None),
        "gain_fraicheur_median_ms": (
            round(sorted(gains_ms)[len(gains_ms) // 2], 2) if gains_ms else None
        ),
        "lignes": lignes,
        # HONNETETE : plus rapide != meilleur. Un chemin qui decide plus vite sur un signal sans
        # edge decide juste plus vite de perdre de l'argent.
        "avertissement": (
            "Un gain de fraicheur est un gain TECHNIQUE. Il ne devient un gain economique que si "
            "la courbe edge/horizon montre un edge a ces horizons -- ce qui n'est PAS acquis."
        ),
        "shadow_only": True,
        "real_execution": False,
    }


__all__ = [
    "DECLENCHEURS", "ENV_ACTIF", "ENV_AUTORITAIRE",
    "EventDrivenDecider", "ShadowDecision", "ShadowStats", "comparer",
]
