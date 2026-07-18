"""Pipeline de FILTRES composable — branche les gardes P1 (« moins de trades, plus propres »)
SUR la porte de décision LIVE (`pipeline/v12_decision_pipeline.py`), à UN seul point.

Principe dur (anti « garde affamé », leçon du 13/07) : chaque garde ne s'applique QUE si son
entrée est présente. Entrée absente → ABSTENTION (jamais un refus fabriqué, jamais une donnée
inventée). Un garde APPLICABLE qui échoue → REFUS (deny-by-default). On ne branche ici QUE des
gardes dont la SORTIE est CONSOMMÉE (refus → NO_TRADE) — pas de facteur « mesuré puis jeté ».

Les gardes ne filtrent QUE les entrées ; ils ne bloquent JAMAIS une sortie (risque-réductrice).
PAPER only : aucun ordre, aucune signature, aucune donnée réseau. Un refus n'est pas un ordre.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hl_observer.copy_wallet.structural_wallet_filter import est_structurel
from hl_observer.execution.freshness_cut import frais_pour_envoi
from hl_observer.market.universe_guard import coin_tradeable
from hl_observer.realtime.tick_quality_guard import tick_est_stale
from hl_observer.risk.margin_reserve import respecte_reserve
from hl_observer.signals.crowding import saturation
from hl_observer.signals.session_conditioning import autorise_session

UNIVERS_MIN = 2   # en-dessous, l'univers est trop pauvre pour gater → abstention (anti-affamé)


@dataclass(frozen=True, slots=True)
class ContexteDecision:
    """Tout ce que la porte PEUT fournir. Un champ à None = entrée absente = garde en ABSTENTION."""
    coin: str
    est_sortie: bool
    univers: tuple[str, ...] = ()          # coins avec un mid valide → univers tradeable
    ts_ms: int | None = None               # horodatage de la décision (session)
    wallet: str | None = None
    wallet_stats: dict | None = None       # winrate / pnl_par_trade → structurel ? (armé si absent)
    age_signal_s: float | None = None      # fraîcheur du signal (armé si absent)
    mid: float | None = None
    prix_reference: float | None = None    # pour stale-tick (armé si absent)
    marge_utilisee: float | None = None
    capital: float | None = None
    edge_hist_bps: float | None = None      # crowding : edge historique
    edge_recent_bps: float | None = None    # crowding : edge récent


@dataclass(frozen=True, slots=True)
class ResultatFiltres:
    accepte: bool
    refus: tuple[str, ...] = ()
    abstentions: tuple[str, ...] = ()
    notes: dict[str, Any] = field(default_factory=dict)


def appliquer_filtres(ctx: ContexteDecision) -> ResultatFiltres:
    """Compose les 7 gardes. accepte=False dès qu'un garde APPLICABLE refuse. Sortie jamais bloquée."""
    refus: list[str] = []
    abst: list[str] = []
    notes: dict[str, Any] = {}

    # Les sorties (reduce/close) sont risque-réductrices : on ne les bloque JAMAIS.
    if ctx.est_sortie:
        return ResultatFiltres(accepte=True, abstentions=("SORTIE_NON_FILTREE",))

    # --- S2 UNIVERS : coin tradeable ? actif seulement si l'univers est assez riche (anti-affamé) ---
    if ctx.univers and len(set(ctx.univers)) >= UNIVERS_MIN:
        if not coin_tradeable(ctx.coin, ctx.univers):
            refus.append("COIN_HORS_UNIVERS")
    else:
        abst.append("UNIVERS_INSUFFISANT")

    # --- G3 SESSION : heure/jour autorisé ? (permissif par défaut) ---
    if ctx.ts_ms is not None:
        if not autorise_session(int(ctx.ts_ms)):
            refus.append("SESSION_NON_AUTORISEE")
    else:
        abst.append("SESSION_TS_ABSENT")

    # --- L5 FRAÎCHEUR : signal assez frais ? (armé si âge inconnu — on ne devine pas l'âge) ---
    if ctx.age_signal_s is not None:
        if not frais_pour_envoi(float(ctx.age_signal_s)):
            refus.append("SIGNAL_TROP_VIEUX")
    else:
        abst.append("FRAICHEUR_AGE_ABSENT")

    # --- G5 WALLET STRUCTUREL : exclure infra/MM structurel (armé si stats absentes) ---
    if ctx.wallet_stats is not None:
        if est_structurel(ctx.wallet_stats):
            refus.append("WALLET_STRUCTUREL")
    else:
        abst.append("WALLET_STATS_ABSENTES")

    # --- G4 STALE TICK : prix aberrant vs référence ? (armé si référence absente) ---
    if ctx.mid is not None and ctx.prix_reference is not None:
        if tick_est_stale(float(ctx.mid), float(ctx.prix_reference)):
            refus.append("TICK_STALE")
    else:
        abst.append("TICK_REFERENCE_ABSENTE")

    # --- S6 RÉSERVE DE MARGE : respecte le buffer ? (armé si marge/capital absents) ---
    if ctx.marge_utilisee is not None and ctx.capital is not None and ctx.capital > 0:
        if not respecte_reserve(float(ctx.marge_utilisee), float(ctx.capital)):
            refus.append("RESERVE_MARGE_VIOLEE")
    else:
        abst.append("MARGE_CAPITAL_ABSENTS")

    # --- S4 CROWDING : edge saturé dans le temps ? (armé si historique absent) ---
    if ctx.edge_hist_bps is not None and ctx.edge_recent_bps is not None:
        sat = saturation(float(ctx.edge_hist_bps), float(ctx.edge_recent_bps))
        if sat is None:                        # historique <= 0 : non mesurable
            abst.append("CROWDING_NON_MESURABLE")
        elif sat.get("sature"):                # refus SEULEMENT si réellement saturé
            refus.append("EDGE_SATURE")
            notes["crowding"] = sat
    else:
        abst.append("CROWDING_HISTORIQUE_ABSENT")

    return ResultatFiltres(
        accepte=not refus,
        refus=tuple(dict.fromkeys(refus)),
        abstentions=tuple(dict.fromkeys(abst)),
        notes=notes,
    )


__all__ = ["ContexteDecision", "ResultatFiltres", "appliquer_filtres", "UNIVERS_MIN"]
