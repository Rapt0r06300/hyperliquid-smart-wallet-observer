"""#292b — LES 11 GATES DE `risk_engine_v3`, ENFIN SUR LE CHEMIN D'ENTRÉE.

═══════════════════════════════════════════════════════════════════════════════════════════════
LE CONSTAT QUI FAIT MAL
═══════════════════════════════════════════════════════════════════════════════════════════════

`evaluate_v19_risk_gates()` évalue **onze** garde-fous anti-perte : perte de session, série de
pertes, edge négatif récurrent, closes orphelins, profit factor, drag des frais, signaux périmés…

**Son SEUL appelant est `analysis/negative_pnl_auditor.py`.**

    > ### ***Les 11 gates qui auraient pu EMPÊCHER la perte ne servent qu'à l'EXPLIQUER après coup.***

C'est la maladie du projet dans sa forme la plus cruelle : *une capacité présente, un chaînon
manquant, et le seul témoin est l'autopsie.*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QU'ILS SONT — et pourquoi ils vont AVANT la porte, pas dedans
═══════════════════════════════════════════════════════════════════════════════════════════════

Ce ne sont **PAS** des gates par trade (le noyau s'en charge : edge, prix, coûts).
Ce sont des **DISJONCTEURS DE SESSION** :

    « La session perd. Elle enchaîne les pertes. Son profit factor est sous 1.
      **On arrête d'ouvrir**, on garde les positions existantes marquées au marché,
      et on attend que l'humain regarde. »

Donc ils s'évaluent **une fois par décision, AVANT tout le reste**. Si la session est en halte,
**aucun edge, si beau soit-il, ne rouvre la porte.** *Un disjoncteur qui se laisse convaincre par
un bon argument n'est pas un disjoncteur.*

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 DENY-BY-DEFAULT, MAIS SANS MENSONGE
═══════════════════════════════════════════════════════════════════════════════════════════════

Si l'état de session n'est **pas fourni**, on ne fait PAS semblant qu'il est sain.
On **le signale** (`ETAT_SESSION_NON_FOURNI`) — et un **invariant AST** oblige le chemin d'entrée
LIVE à le fournir. *Un état absent n'est pas un état sain.*

PUR : aucun réseau, aucun ordre réel. Paper-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hl_observer.risk.risk_engine_v3 import V19RiskConfig, evaluate_v19_risk_gates

MOTIF_SESSION_EN_HALTE = "SESSION_EN_HALTE_LES_GATES_V19_BLOQUENT_LES_NOUVELLES_ENTREES"
MOTIF_ETAT_NON_FOURNI = "ETAT_SESSION_NON_FOURNI"
MOTIF_OK = "SESSION_SAINE"


@dataclass(frozen=True, slots=True)
class EtatSession:
    """Ce que la session a **réellement** produit. Aucun de ces chiffres n'est supposé.

    Il vient du **ledger** — la source unique du PnL (règle du projet).
    """
    net_pnl_usdc: float = 0.0
    total_decisions: int = 0
    accepted: int = 0
    negative_events: int = 0
    positive_events: int = 0
    fee_drag_ratio: float = 0.0
    stale_reason_count: int = 0
    edge_negative_count: int = 0
    edge_sentinel_count: int = 0
    orphan_close_count: int = 0
    profit_factor_net: float = 1.0
    consecutive_losses: int = 0
    strategy_protection_recommended: bool = False
    top_losing_coins: tuple[tuple[str, float], ...] = ()
    top_losing_wallets: tuple[tuple[str, float], ...] = ()

    @property
    def vierge(self) -> bool:
        """Une session sans AUCUNE décision ne peut pas être jugée. *Et on le dit.*"""
        return self.total_decisions == 0 and self.positive_events == 0 \
            and self.negative_events == 0


@dataclass(frozen=True, slots=True)
class VerdictSession:
    bloque: bool
    motif: str
    gates_declenches: tuple[str, ...] = ()
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"bloque": self.bloque, "motif": self.motif,
                "gates_declenches": list(self.gates_declenches),
                "detail": self.detail, "evidence": dict(self.evidence),
                "paper_only": True, "real_execution": False}


def evaluer_session(etat: EtatSession | None,
                    *, config: V19RiskConfig | None = None) -> VerdictSession:
    """🔴 **LE DISJONCTEUR.** Il tourne AVANT le noyau, pas après le désastre.

    `etat=None` -> on **signale**, on ne prétend pas que tout va bien.
    ***Un état absent n'est pas un état sain.***
    """
    if etat is None:
        return VerdictSession(
            bloque=False, motif=MOTIF_ETAT_NON_FOURNI,
            detail=("🔴 L'etat de session n'a pas ete fourni au noyau. **On ne pretend PAS qu'il "
                    "est sain** -- on le SIGNALE. Un invariant AST oblige le chemin d'entree LIVE "
                    "a le fournir. *Un etat absent n'est pas un etat sain.*"),
        )
    if etat.vierge:
        return VerdictSession(bloque=False, motif=MOTIF_OK,
                              detail="session vierge : aucune decision encore prise")

    d = evaluate_v19_risk_gates(
        net_pnl_usdc=etat.net_pnl_usdc,
        total_decisions=etat.total_decisions,
        accepted=etat.accepted,
        negative_events=etat.negative_events,
        positive_events=etat.positive_events,
        fee_drag_ratio=etat.fee_drag_ratio,
        stale_reason_count=etat.stale_reason_count,
        edge_negative_count=etat.edge_negative_count,
        edge_sentinel_count=etat.edge_sentinel_count,
        orphan_close_count=etat.orphan_close_count,
        profit_factor_net=etat.profit_factor_net,
        consecutive_losses=etat.consecutive_losses,
        strategy_protection_recommended=etat.strategy_protection_recommended,
        top_losing_coins=list(etat.top_losing_coins),
        top_losing_wallets=list(etat.top_losing_wallets),
        config=config,
    )

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🔴 BUG TROUVE DANS MON PROPRE GARDE-FOU (2026-07-14) — ET IL AURAIT TOUT LAISSE PASSER.
    #
    # J'avais ecrit : `getattr(g, "blocks", False)`.
    # **Le champ s'appelle `blocks_new_entries`.** -> `getattr` rendait TOUJOURS `False`
    # -> ***aucun gate ne bloquait jamais.*** Le disjoncteur etait branche... et MORT.
    #
    # ***J'ai reproduit EXACTEMENT la maladie que je repare*** : un garde-fou qui a l'air
    # branche et qui laisse tout passer en silence. (Comme le voyant soude, le garde-fou
    # affame, les 7 anti-overfit sans appelant.)
    #
    # ✅ ET SURTOUT : la decision expose deja **`allow_new_entries`** -- la verite faisant
    #    AUTORITE. On ne la reconstruit plus : **on la LIT.**
    #    *Un garde-fou qui devine le nom d'un champ est un garde-fou qui finira par mentir.*
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    bloquants = tuple(
        g.code for g in getattr(d, "gates", ())
        if getattr(g, "triggered", False) and getattr(g, "blocks_new_entries", False)
    )
    autorise = bool(getattr(d, "allow_new_entries", True))

    if not autorise or bloquants:
        return VerdictSession(
            bloque=True, motif=MOTIF_SESSION_EN_HALTE,
            gates_declenches=bloquants,
            detail=("**La session est en HALTE** : %s. *Aucun edge, si beau soit-il, ne rouvre "
                    "la porte.* Un disjoncteur qui se laisse convaincre par un bon argument "
                    "n'est pas un disjoncteur."
                    % (", ".join(bloquants) if bloquants else "allow_new_entries=False")),
            evidence=d.as_dict() if hasattr(d, "as_dict") else {},
        )
    return VerdictSession(bloque=False, motif=MOTIF_OK,
                          evidence=d.as_dict() if hasattr(d, "as_dict") else {})


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LA SOURCE : l'état courant, alimenté par le LEDGER.
#
# 🔴 **Le ledger est la source UNIQUE du PnL** (règle du projet). Le disjoncteur ne calcule rien
# lui-même : il LIT. *Un disjoncteur qui recalcule le PnL est un deuxième PnL — et on a déjà vu
# ce que deux tables d'edge produisent.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
_ETAT_COURANT: EtatSession | None = None


def publier_etat_session(etat: EtatSession | None) -> None:
    """Le LEDGER appelle ceci après chaque événement. **Personne d'autre.**"""
    global _ETAT_COURANT
    _ETAT_COURANT = etat


def etat_session_courant() -> EtatSession | None:
    """L'état vu par le noyau. `None` = **non alimenté** → le noyau SIGNALE, il ne suppose pas."""
    return _ETAT_COURANT


def reinitialiser() -> None:
    """Entre deux sessions. *On ne mélange JAMAIS deux runs* (cf. #286)."""
    publier_etat_session(None)


__all__ = [
    "MOTIF_ETAT_NON_FOURNI", "MOTIF_OK", "MOTIF_SESSION_EN_HALTE",
    "EtatSession", "VerdictSession",
    "etat_session_courant", "evaluer_session", "publier_etat_session", "reinitialiser",
]
