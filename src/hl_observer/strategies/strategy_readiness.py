"""AUD-043 — READY_STRATEGIES : barrière de disponibilité PAR FAMILLE active.

READY_CORE (preuve_de_vie) prouve que le SOCLE de collecte vit. Il ne prouve PAS qu'une famille
STRATÉGIQUE donnée dispose de TOUTE sa donnée requise (ni que ses buffers de warm-up sont chauds).
READY_STRATEGIES comble ce trou, PAR FAMILLE : une famille active est strategy-ready ssi
  (a) ses sources REQUISES (autorité `strategy_data_dependencies`) sont explicitement prêtes
      — vérifié par la porte `aggregate_market_ready_gate` — ET
  (b) sa barrière de warm-up (`execution_core.warmup_barrier`, si fournie) est prête.
Deny-by-default : source manquante/non prête, ou warm-up incomplet -> famille NON ready.

Ce module CÂBLE deux briques jusque-là orphelines (warmup_barrier, aggregate_market_ready_gate)
et l'autorité de dépendances de données, en un niveau NOMMÉ distinct de READY_CORE. Read-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from hl_observer.quoting.aggregate_market_ready_gate import pret as _porte_sources
from hl_observer.strategies.active_scope import active_strategy_families
from hl_observer.strategies.strategy_data_dependencies import required_sources


@dataclass(frozen=True, slots=True)
class FamilyReadiness:
    family: str
    ready: bool
    data_ready: bool
    warmup_ready: bool
    missing_sources: frozenset[str]
    raison: str


def _etats(source_states: Mapping[str, Any] | Iterable[str]) -> dict[str, Any]:
    """Accepte soit un mapping source->état (True/'READY'/...), soit un itérable de noms prêts."""
    if isinstance(source_states, Mapping):
        return {str(k): v for k, v in source_states.items()}
    return {str(s): True for s in source_states}


def ready_strategies(source_states: Mapping[str, Any] | Iterable[str], *,
                     warmup: Any | None = None) -> dict[str, FamilyReadiness]:
    """READY_STRATEGIES par famille active. `warmup` optionnel = `BarriereWarmup` : si fourni, la
    famille exige AUSSI que sa barrière de warm-up soit prête."""
    etats = _etats(source_states)
    out: dict[str, FamilyReadiness] = {}
    for fam in sorted(active_strategy_families()):
        req = required_sources(fam)
        # (a) données : chaque source REQUISE doit être explicitement prête (porte agrégée).
        sous_etats = {s: etats.get(s, False) for s in req}
        data_ready = bool(req) and bool(_porte_sources(sous_etats).get("pret"))
        manquantes = frozenset(s for s in req if not bool(_porte_sources({s: etats.get(s, False)}).get("pret")))
        # (b) warm-up : optionnel ; si fourni, la barrière de la famille doit être prête.
        warm_ok = True
        if warmup is not None:
            warm_ok = bool(warmup.pret(fam).get("pret"))
        ready = data_ready and warm_ok
        if not bool(req):
            raison = "AUCUNE_DEPENDANCE_DECLAREE"
        elif not data_ready:
            raison = "DATA_MANQUANTE:" + ",".join(sorted(manquantes))
        elif not warm_ok:
            raison = "WARMUP_INCOMPLET"
        else:
            raison = "READY"
        out[fam] = FamilyReadiness(fam, ready, data_ready, warm_ok, manquantes, raison)
    return out


def families_ready(source_states: Mapping[str, Any] | Iterable[str], *,
                   warmup: Any | None = None) -> frozenset[str]:
    return frozenset(f for f, r in ready_strategies(source_states, warmup=warmup).items() if r.ready)


def all_active_families_ready(source_states: Mapping[str, Any] | Iterable[str], *,
                              warmup: Any | None = None) -> bool:
    """READY_STRATEGIES global : VRAI ssi TOUTES les familles actives sont strategy-ready."""
    familles = active_strategy_families()
    return bool(familles) and families_ready(source_states, warmup=warmup) == frozenset(familles)
