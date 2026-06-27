"""V9 / T8 — Diagnostic par cycle de l'OFFRE de signaux d'entrée.

Répond à la question : « le moteur n'ouvre rien — est-ce un problème d'OFFRE
(presque aucune entrée fraîche → élargir les wallets / WS userFills) ou de GATES
(des entrées fraîches existent mais sont toutes refusées → calibrer) ? »

Consomme les résultats de la porte d'entrée (`fill_admission.admit_live_fill`) plus,
pour chaque ENTRÉE admise, l'issue du scorer (acceptée -> paper trade, ou refusée + raison).
Read-only / paper-only. Aucune donnée inventée, aucune entrée forcée : on ne fait que MESURER.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from hl_observer.signals.fill_admission import FillAdmission, KIND_ENTRY, KIND_EXIT, KIND_SKIP


# verdicts
BOTTLENECK_NO_DATA = "NO_DATA"
BOTTLENECK_SUPPLY = "SUPPLY"   # pas (assez) d'entrées fraîches -> élargir wallets / WS userFills
BOTTLENECK_GATES = "GATES"     # des entrées fraîches existent mais toutes refusées -> calibrer
BOTTLENECK_OK = "OK"           # au moins une entrée paper ouverte


@dataclass(frozen=True, slots=True)
class CycleEvent:
    admission: FillAdmission
    accepted: bool | None = None        # pour une ENTRÉE admise : a-t-elle ouvert un paper trade ?
    refusal_reason: str | None = None   # raison du scorer si refusée


@dataclass(frozen=True, slots=True)
class EntrySupplyReport:
    candidates: int
    skipped: int
    admitted_entries: int
    admitted_exits: int
    fresh_entries: int
    accepted_entries: int
    refused_entries: int
    skip_reasons: dict[str, int] = field(default_factory=dict)
    refusal_reasons: dict[str, int] = field(default_factory=dict)
    read_only: bool = True
    execution: str = "forbidden"

    @property
    def bottleneck(self) -> str:
        if self.candidates == 0:
            return BOTTLENECK_NO_DATA
        if self.accepted_entries > 0:
            return BOTTLENECK_OK
        if self.fresh_entries == 0:
            return BOTTLENECK_SUPPLY
        return BOTTLENECK_GATES

    @property
    def next_action(self) -> str:
        b = self.bottleneck
        if b == BOTTLENECK_NO_DATA:
            return "Aucun candidat sur le cycle : vérifier la collecte (WS/REST) et la shortlist."
        if b == BOTTLENECK_SUPPLY:
            return ("Offre insuffisante : presque aucune entrée FRAÎCHE. Élargir les wallets suivis "
                    "(discovery/collect-all) et activer WS userFills sur les leaders chauds. NE PAS forcer d'entrée.")
        if b == BOTTLENECK_GATES:
            return ("Des entrées fraîches existent mais sont toutes refusées : analyser refusal_reasons "
                    "et calibrer (edge/liquidité/dégradation) — sans jamais inventer de signal.")
        return "Au moins une entrée paper ouverte sur des perps crypto liquides."


def build_entry_supply_report(events: list[CycleEvent]) -> EntrySupplyReport:
    skip_reasons: Counter[str] = Counter()
    refusal_reasons: Counter[str] = Counter()
    skipped = admitted_entries = admitted_exits = fresh_entries = 0
    accepted_entries = refused_entries = 0

    for ev in events:
        a = ev.admission
        if a.kind == KIND_SKIP:
            skipped += 1
            skip_reasons[a.reason] += 1
            continue
        if a.kind == KIND_ENTRY:
            admitted_entries += 1
            if a.is_fresh:
                fresh_entries += 1
            if ev.accepted is True:
                accepted_entries += 1
            elif ev.accepted is False:
                refused_entries += 1
                refusal_reasons[ev.refusal_reason or "UNSPECIFIED"] += 1
        elif a.kind == KIND_EXIT:
            admitted_exits += 1

    return EntrySupplyReport(
        candidates=len(events),
        skipped=skipped,
        admitted_entries=admitted_entries,
        admitted_exits=admitted_exits,
        fresh_entries=fresh_entries,
        accepted_entries=accepted_entries,
        refused_entries=refused_entries,
        skip_reasons=dict(skip_reasons),
        refusal_reasons=dict(refusal_reasons),
    )


def format_entry_supply_report(r: EntrySupplyReport) -> str:
    lines = [
        "entry_supply=read_only",
        f"bottleneck={r.bottleneck}",
        f"candidates={r.candidates}",
        f"skipped_noise={r.skipped}",
        f"admitted_entries={r.admitted_entries}",
        f"fresh_entries={r.fresh_entries}",
        f"accepted_entries={r.accepted_entries}",
        f"refused_entries={r.refused_entries}",
        f"execution={r.execution}",
    ]
    if r.skip_reasons:
        lines.append("skip_reasons=" + ",".join(f"{k}:{v}" for k, v in sorted(r.skip_reasons.items(), key=lambda x: -x[1])))
    if r.refusal_reasons:
        lines.append("refusal_reasons=" + ",".join(f"{k}:{v}" for k, v in sorted(r.refusal_reasons.items(), key=lambda x: -x[1])))
    lines.append("next_action=" + r.next_action)
    return "\n".join(lines)


__all__ = [
    "BOTTLENECK_NO_DATA",
    "BOTTLENECK_SUPPLY",
    "BOTTLENECK_GATES",
    "BOTTLENECK_OK",
    "CycleEvent",
    "EntrySupplyReport",
    "build_entry_supply_report",
    "format_entry_supply_report",
]
