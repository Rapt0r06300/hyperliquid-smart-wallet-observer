"""Jalon 1 — le SCOREBOARD alimenté par le ledger SCELLÉ (vérité PnL réalisée, PAR stratégie).

`audit_paper_ledger` prouve qu'un ledger est cohérent et rend un PnL réalisé **scalaire** global.
Le scoreboard, lui, exige la **distribution** des PnL de round-trips CLOS par stratégie — pour
`profit_factor`/`max_drawdown`/`expected_shortfall`/`hit_rate` — et un **N indépendant** = nombre
d'épisodes clos (un cycle OPEN→CLOSE = **une** observation), jamais « 1 fill = 1 obs ». Ce module
est le pont honnête entre les deux, et il CÂBLE `scoreboard_metrics` (sinon assembleur orphelin) :

  * il refuse tout si l'audit n'est pas `TRUSTED` (deny-by-default : un ledger douteux ne produit
    AUCUN PnL de stratégie, seulement des lignes UNMEASURABLE / `MORE_DATA`) ;
  * sur un ledger `TRUSTED`, il reconstruit chaque cycle OPEN→CLOSE comme UNE observation
    indépendante (remise à zéro de la clé à la clôture : deux round-trips successifs sur le même
    coin ne se confondent pas), regroupée par `refs["strategy"]` ;
  * il n'affirme QUE le mesuré : PnL réalisé par épisode = mesuré ; edge brut bps, spread/slippage/
    latence bps, OOS, forward = ABSENTS du ledger ⇒ `UNMEASURABLE`. Donc, tel quel, **aucun**
    `net_bps` n'est calculable et **aucun** verdict `PROMOTE` n'est possible : c'est la vérité du
    moment, et `manques_globaux` liste exactement ce que le pipeline doit se mettre à émettre.

Pur, 0 réseau, 0 ordre réel. `depuis_fichier_ledger` branche la lecture sur le ledger scellé réel.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hl_observer.simulation.pnl_ledger_audit import TRUSTED, audit_paper_ledger
from hl_observer.simulation.scoreboard_metrics import ScoreboardRow, assembler_ligne

SCHEMA_VERSION = "hypersmart.scoreboard_feeder.v1"

#: Événements qui RÉALISENT du PnL de round-trip (REDUCE réalise le partiel, CLOSE le solde).
_REALISANTS = ("PAPERPOSITIONREDUCED", "PAPERPOSITIONCLOSED")
_OUVRANTS = ("PAPERPOSITIONOPENED", "PAPERPOSITIONINCREASED")
_CLOTURANT = "PAPERPOSITIONCLOSED"

#: Stratégies « fourre-tout » : rendre visible l'absence/l'ambiguïté d'un tag stratégie au lieu de la cacher.
STRAT_ABSENTE = "STRATEGIE_ABSENTE"
STRAT_AMBIGUE = "STRATEGIE_AMBIGUE"


def _token(value: object) -> str:
    return "".join(c for c in str(value or "").upper() if c.isalnum())


def _finite(value: object) -> float | None:
    try:
        n = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return n if math.isfinite(n) else None


def _refs(row: Mapping[str, Any]) -> Mapping[str, Any]:
    r = row.get("refs")
    return r if isinstance(r, Mapping) else {}


def _strategie(refs: Mapping[str, Any]) -> str | None:
    s = refs.get("strategy")
    if s in (None, ""):
        s = refs.get("strategie")
    s = str(s).strip() if s not in (None, "") else ""
    return s or None


def _cle_position(row: Mapping[str, Any], refs: Mapping[str, Any]) -> str:
    """Même convention d'identité que l'audit : `refs.position_id`, sinon `COIN:SIDE`."""
    pid = refs.get("position_id")
    if pid not in (None, ""):
        return str(pid)
    return f"{str(row.get('coin') or '').upper()}:{str(row.get('side') or '').upper()}"


def _resoudre_strategie(strats: set[str]) -> str:
    """Une seule stratégie observée sur l'épisode → elle ; plusieurs → AMBIGUE ; aucune → ABSENTE."""
    nettoyees = {s for s in strats if s}
    if not nettoyees:
        return STRAT_ABSENTE
    if len(nettoyees) > 1:
        return STRAT_AMBIGUE
    return next(iter(nettoyees))


def _familles_actives() -> tuple[str, ...]:
    try:
        from hl_observer.strategies.active_scope import active_strategy_families
        return tuple(sorted(active_strategy_families()))
    except Exception:  # pragma: no cover - l'autorité reste active_scope, mais on ne casse pas si absente
        return ()


@dataclass(frozen=True, slots=True)
class ResultatScoreboard:
    status: str                       # TRUSTED | CONTAMINATED | UNMEASURABLE (repris de l'audit)
    rows: tuple[ScoreboardRow, ...]
    n_episodes_clos: int
    manques_globaux: tuple[str, ...]  # union des champs UNMEASURABLE sur toutes les lignes
    raison: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "n_episodes_clos": self.n_episodes_clos,
            "rows": [r.to_dict() for r in self.rows],
            "manques_globaux": list(self.manques_globaux),
            "raison": self.raison,
            "paper_only": True,
            "real_execution": False,
        }


def _union_manques(rows: Sequence[ScoreboardRow]) -> tuple[str, ...]:
    vus: list[str] = []
    for r in rows:
        for champ in r.unmeasured:
            if champ not in vus:
                vus.append(champ)
    return tuple(vus)


def lignes_depuis_ledger(
    events: Iterable[Mapping[str, Any]],
    *,
    snapshot: Mapping[str, Any] | None = None,
    roi_denominateurs: Mapping[str, float] | None = None,
    strategies_attendues: Sequence[str] | None = None,
) -> ResultatScoreboard:
    """Assemble les lignes de scoreboard depuis un ledger canonique. `TRUSTED` obligatoire pour un PnL."""
    rows_in = [dict(r) for r in events]
    attendues = tuple(strategies_attendues) if strategies_attendues is not None else _familles_actives()
    roi_denominateurs = dict(roi_denominateurs or {})

    audit = audit_paper_ledger(rows_in, snapshot=snapshot)
    if audit.status != TRUSTED:
        # Deny-by-default : un ledger non fiable ne matérialise AUCUN PnL de stratégie.
        rows = tuple(assembler_ligne(s) for s in attendues)
        return ResultatScoreboard(
            status=audit.status, rows=rows, n_episodes_clos=0,
            manques_globaux=_union_manques(rows),
            raison=f"ledger {audit.status}: PnL par stratégie non calculable (deny-by-default)",
        )

    # Ledger TRUSTED : reconstruire les épisodes (OPEN→CLOSE) dans l'ordre, un par cycle.
    ouvertes: dict[str, dict[str, Any]] = {}
    episodes: list[tuple[str, float]] = []          # (stratégie résolue, PnL réalisé du cycle)
    for row in rows_in:
        et = _token(row.get("event_type"))
        refs = _refs(row)
        strat = _strategie(refs)
        if et in _OUVRANTS:
            cle = _cle_position(row, refs)
            ep = ouvertes.setdefault(cle, {"realized": 0.0, "strats": set()})
            if strat:
                ep["strats"].add(strat)
            continue
        if et in _REALISANTS:
            cle = _cle_position(row, refs)
            ep = ouvertes.setdefault(cle, {"realized": 0.0, "strats": set()})
            if strat:
                ep["strats"].add(strat)
            p = _finite(row.get("realized_pnl_usdc"))
            if p is not None:
                ep["realized"] += p
            if et == _CLOTURANT:
                episodes.append((_resoudre_strategie(ep["strats"]), round(ep["realized"], 10)))
                ouvertes.pop(cle, None)
            continue

    pnls_par_strat: dict[str, list[float]] = {}
    for strat, pnl in episodes:
        pnls_par_strat.setdefault(strat, []).append(pnl)

    # Une ligne par stratégie ATTENDUE (même vide → MORE_DATA explicite) + toute stratégie vue.
    strategies = list(dict.fromkeys([*attendues, *sorted(pnls_par_strat)]))
    rows = tuple(
        assembler_ligne(
            s,
            closed_pnls=pnls_par_strat.get(s) or None,
            n_independent=(len(pnls_par_strat[s]) if s in pnls_par_strat else None),
            roi_denominator_usd=roi_denominateurs.get(s),
        )
        for s in strategies
    )
    return ResultatScoreboard(
        status=TRUSTED, rows=rows, n_episodes_clos=len(episodes),
        manques_globaux=_union_manques(rows), raison=None,
    )


def depuis_fichier_ledger(
    path: str | Path,
    *,
    snapshot: Mapping[str, Any] | None = None,
    roi_denominateurs: Mapping[str, float] | None = None,
    strategies_attendues: Sequence[str] | None = None,
) -> ResultatScoreboard:
    """Câblage réel : lit le ledger SCELLÉ (`ledger_integrity.read_chain`) puis assemble le scoreboard.

    Un fichier illisible ou une chaîne de hash rompue ⇒ `strict_pnl_allowed` faux ⇒ on ne calcule
    aucun PnL (statut du lecteur remonté tel quel). On ne devine jamais un ledger cassé.
    """
    from hl_observer.simulation.ledger_integrity import read_chain

    lecture = read_chain(Path(path))
    if not lecture.strict_pnl_allowed:
        attendues = tuple(strategies_attendues) if strategies_attendues is not None else _familles_actives()
        rows = tuple(assembler_ligne(s) for s in attendues)
        return ResultatScoreboard(
            status=lecture.status, rows=rows, n_episodes_clos=0,
            manques_globaux=_union_manques(rows),
            raison=f"ledger illisible/rompu ({lecture.status}): PnL non calculable",
        )
    return lignes_depuis_ledger(
        lecture.events, snapshot=snapshot,
        roi_denominateurs=roi_denominateurs, strategies_attendues=strategies_attendues,
    )


__all__ = [
    "SCHEMA_VERSION", "STRAT_ABSENTE", "STRAT_AMBIGUE",
    "ResultatScoreboard", "lignes_depuis_ledger", "depuis_fichier_ledger",
]
