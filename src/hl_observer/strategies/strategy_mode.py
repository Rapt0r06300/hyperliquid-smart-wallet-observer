"""ATTRIBUTION DU MOTEUR : GRINDER vs SNIPER (2026-07-11).

CONSTAT DE LA PHASE 0 — LES DEUX MOTEURS N'EXISTENT PAS DANS LE CODE.

Recherche exhaustive : le mot "sniper" n'apparait **nulle part** dans le moteur. Il n'existe que
dans une ligne de JavaScript du dashboard (`dashboard_v2.py`, fonction `modeOf`) qui DEVINE le mode
d'apres le nom de la strategie, cote navigateur :

    return (m.indexOf('FUNDING')>=0 || m.indexOf('ARBITRAGE')>=0 || ... )?'GRINDER':'SNIPER';

Aucun champ `strategy_mode` n'existe dans le ledger. Aucun moteur separe dans le code. **Tous les
trades passent par le meme chemin** (fusion runtime -> PaperEngine -> adaptateur persistant).
Le "Grinder" et le "Sniper" sont une INTENTION de conception, pas une implementation.

Consequence directe : **on ne peut pas separer le PnL des deux moteurs tant que chaque decision ne
porte pas son mode.** C'est le prerequis de tout le reste (pistes 11 a 20 du backlog).

CE MODULE EST CE PREREQUIS. Il est PUR et TESTE :
  * `classify(...)` -> GRINDER | SNIPER | UNKNOWN_LEGACY, a partir de faits observables ;
  * jamais de devinette silencieuse : ce qu'on ne sait pas est marque UNKNOWN_LEGACY.

DEFINITIONS (tirees du brief de Flo, et assumees comme telles) :
  * GRINDER : beaucoup d'operations, petits objectifs, duree courte. Mecaniquement, il s'agit des
    strategies qui n'ont PAS besoin d'un signal directionnel exceptionnel : market making,
    funding delta-neutre, arbitrage, grid. Extremement sensible aux frais.
  * SNIPER  : peu d'operations, uniquement sur un signal RARE et TRES FRAIS (copie d'un leader).
    Extremement sensible a la fraicheur du signal et au prix d'entree.

Aucun ordre reel. Pur, sans I/O.
"""
from __future__ import annotations

from typing import Any, Mapping

GRINDER = "GRINDER"
SNIPER = "SNIPER"
UNKNOWN_LEGACY = "UNKNOWN_LEGACY"

# Familles de strategies qui ne reposent PAS sur un pari directionnel issu d'un leader.
# (fragments recherches dans le strategy_id / la source / le mode de position)
_GRINDER_TOKENS = (
    "funding",          # funding delta-neutre
    "arbitrage",        # cross-exchange, triangulaire
    "arb_",
    "triangular",
    "delta_neutral",
    "market_making",
    "maker",
    "grid",
    "spread",
    "basis",
    "discrepancy",      # ws_price_discrepancy_paper
)

# Familles qui reposent sur la COPIE d'un signal de leader (rare, doit etre frais).
_SNIPER_TOKENS = (
    "copy",
    "whale",
    "mirror",
    "leader",
    "consensus",
    "fresh_opportunity",
    "sniper",
    "direction_hunt",
    "distilled",        # consensus whale distille
    # aligne sur la definition DEJA presente dans le projet
    # (`fusion_persistent_adapter.COPY_LIKE_FAMILY_TOKENS`) : on n'invente pas une seconde
    # taxonomie a cote de celle qui existe.
    "autonomous_sltp",
)


def _text(*values: Any) -> str:
    return " ".join(str(v or "") for v in values).lower()


def classify(
    *,
    strategy_id: str | None = None,
    source: str | None = None,
    position_mode: str | None = None,
    leader_wallet: str | None = None,
    signal_age_ms: float | None = None,
    reason: str | None = None,
) -> str:
    """Attribue un moteur a une decision, a partir de FAITS observables.

    Ordre de decision (du plus fiable au moins fiable) :
      1. la famille de strategie est explicite (funding/arb/grid -> GRINDER ; copy/whale -> SNIPER) ;
      2. la presence d'un LEADER identifie implique une copie -> SNIPER ;
      3. rien d'exploitable -> UNKNOWN_LEGACY. **On ne devine pas.**

    On ne se sert PAS de `signal_age_ms` pour classer : un signal vieux reste un signal de copie
    (c'est meme le probleme du Sniper). L'age sert a JUGER le trade, pas a l'etiqueter.
    """
    blob = _text(strategy_id, source, position_mode, reason)

    grinder_hit = any(tok in blob for tok in _GRINDER_TOKENS)
    sniper_hit = any(tok in blob for tok in _SNIPER_TOKENS)

    # Une strategie de funding-arb declenchee par un signal de copie reste un GRINDER :
    # sa rentabilite ne depend pas d'une prediction directionnelle.
    if grinder_hit and not sniper_hit:
        return GRINDER
    if sniper_hit and not grinder_hit:
        return SNIPER
    if grinder_hit and sniper_hit:
        return GRINDER          # le mecanisme structurel prime sur l'origine du declencheur

    # Pas de famille identifiable : un leader identifie signe une copie.
    wallet = str(leader_wallet or "").strip()
    if wallet and wallet.lower() not in {"", "0x", "__consensus__", "none"}:
        return SNIPER

    return UNKNOWN_LEGACY


def classify_event(event: Mapping[str, Any]) -> str:
    """Attribue un moteur a un evenement du ledger (entree, sortie, refus)."""
    if not isinstance(event, Mapping):
        return UNKNOWN_LEGACY
    # un mode deja pose fait autorite : on ne re-devine jamais par-dessus un fait
    posed = str(event.get("strategy_mode") or "").upper()
    if posed in {GRINDER, SNIPER, UNKNOWN_LEGACY}:
        return posed
    return classify(
        strategy_id=event.get("strategy_id"),
        source=event.get("source") or event.get("leader_action"),
        position_mode=event.get("position_mode") or event.get("bot_replay_action"),
        leader_wallet=event.get("leader_wallet") or event.get("wallet_address"),
        signal_age_ms=event.get("signal_age_ms"),
        reason=event.get("reason"),
    )


def stamp(event: dict, mode: str | None = None) -> dict:
    """Pose `strategy_mode` sur un evenement, en place. Retourne l'evenement."""
    if not isinstance(event, dict):
        return event
    event["strategy_mode"] = mode if mode in {GRINDER, SNIPER, UNKNOWN_LEGACY} else classify_event(event)
    return event


def mode_of_position(position: Mapping[str, Any] | None) -> str:
    """Moteur d'une POSITION ouverte. Un mode deja pose fait foi."""
    if not isinstance(position, Mapping):
        return UNKNOWN_LEGACY
    posed = str(position.get("strategy_mode") or "").upper()
    if posed in {GRINDER, SNIPER, UNKNOWN_LEGACY}:
        return posed
    return classify_event(position)


def stamp_exit(event: dict, position: Mapping[str, Any] | None) -> dict:
    """Une SORTIE herite du moteur de son ENTREE. En place.

    On ne reclasse JAMAIS une sortie a partir de son propre texte : le motif de sortie
    ("SLTP_CATASTROPHIC_STOP", "GRADED_HALT_RED_FORCE_EXIT", "UNSTUCK_PARTIAL_CLOSE"...) ne dit
    rien du moteur qui a OUVERT la position. Reclasser une sortie ferait fuir le PnL d'un moteur
    vers l'autre -- exactement ce qu'on cherche a mesurer.
    """
    if not isinstance(event, dict):
        return event
    event["strategy_mode"] = mode_of_position(position)
    return event


__all__ = [
    "GRINDER",
    "SNIPER",
    "UNKNOWN_LEGACY",
    "classify",
    "classify_event",
    "mode_of_position",
    "stamp",
    "stamp_exit",
]
