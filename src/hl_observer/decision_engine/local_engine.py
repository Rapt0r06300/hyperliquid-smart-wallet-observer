from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from hl_observer.config.settings import Settings
from hl_observer.decision_engine import noyau_unique as noyau
from hl_observer.risk.session_gate import etat_session_courant   # #292b — les 11 gates V19
from hl_observer.hyperliquid.schemas import SignalCandidate
from hl_observer.risk.gates import RiskContext
from hl_observer.risk.risk_engine import RiskEngine
from hl_observer.testnet.models import TestnetAction, TestnetOrderRequest, TestnetSide, unix_ms

# G2 -- LE NOYAU EST BRANCHE ICI.
#
# Avant : `decide_from_candidate` construisait un RiskContext avec
# `edge_remaining_bps=candidate.edge_remaining_bps` -- l'edge TEL QUE L'APPELANT LE DONNE.
# Le RiskEngine notait ensuite ce nombre avec une arithmetique impeccable... sans jamais
# questionner sa PROVENANCE. C'est exactement comme ca que trois edges FABRIQUES ont vecu
# des mois dans le code.
#
# Maintenant : toute ENTREE passe d'abord par `noyau_unique.decider()`, qui va CHERCHER
# l'edge dans la table mesuree (Q1), refuse les zones mortes prouvees (Q3) et exige des prix
# executables (Q2). L'edge de l'appelant n'est plus utilise -- il est CONFRONTE.
#
# 🔴 LE NOYAU NE GARDE QUE LES ENTREES. Jamais les sorties : bloquer une sortie, ce serait
# PIEGER une position ouverte. Un garde-fou qui empeche de sortir n'est pas un garde-fou.
#
# Le nom `MASTER_FLAG` n'est pas decoratif : c'est la CONVENTION que le registre des
# interrupteurs (`risk/interrupteurs.py`, GH-01) decouvre par regex. Un interrupteur nomme
# autrement echapperait a l'invariant -- et on aurait recree, pour la huitieme fois, une
# capacite qu'aucun test ne surveille.
MASTER_FLAG = "HYPERSMART_NOYAU_AUTORITAIRE"
NOYAU_FLAG = MASTER_FLAG
NOYAU_CONSULTATIF = "NOYAU_CONSULTATIF_VERDICT_IGNORE"
NOYAU_NON_APPLICABLE_SORTIE = "NOYAU_NON_APPLICABLE_CE_N_EST_PAS_UNE_ENTREE"


def noyau_autoritaire(env: dict | None = None) -> bool:
    """Defaut ALLUME. Un interrupteur qui ne fait que REFUSER doit etre allume (cf. GH-01)."""
    e = env if env is not None else os.environ
    return str(e.get(NOYAU_FLAG, "1") or "").strip().lower() in ("1", "true", "yes", "on")


class DecisionAction(str, Enum):
    ENTER = "ENTER"
    EXIT = "EXIT"
    REDUCE = "REDUCE"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True, slots=True)
class LocalDecision:
    action: DecisionAction
    reasons: list[str]
    candidate_id: str | None = None
    order_request: TestnetOrderRequest | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    decided_at_ms: int = field(default_factory=unix_ms)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.value
        if self.order_request:
            data["order_request"] = self.order_request.to_dict()
        return data


@dataclass(slots=True)
class LocalDecisionEngine:
    settings: Settings

    def decide_from_candidate(
        self,
        candidate: SignalCandidate,
        *,
        notional_usdc: float,
        cloid: str,
    ) -> LocalDecision:
        action = self._action_from_signal(candidate.signal_type)

        # -------------------------------------------------------------- 1. LE NOYAU (G2)
        # Il ne juge QUE les entrees. Une sortie doit toujours pouvoir sortir.
        noyau_dict: dict[str, Any]
        noyau_refuse = False
        if action is DecisionAction.ENTER:
            verdict = noyau.decider(self._contexte_noyau(candidate, notional_usdc))
            noyau_dict = verdict.as_dict()
            noyau_dict["autoritaire"] = noyau_autoritaire()
            if not verdict.autorise:
                if noyau_autoritaire():
                    noyau_refuse = True
                else:
                    # Mode ombre : on garde la trace, mais on n'empeche pas. Le fait que le
                    # verdict soit IGNORE doit rester ECRIT, sinon personne ne le saura.
                    noyau_dict.setdefault("signalements", []).append(NOYAU_CONSULTATIF)
        else:
            noyau_dict = {"verdict": NOYAU_NON_APPLICABLE_SORTIE, "autoritaire": noyau_autoritaire()}

        risk_context = RiskContext(
            spread_bps=candidate.estimated_spread_bps,
            estimated_slippage_bps=candidate.estimated_slippage_bps,
            orderbook_depth_usdc=candidate.orderbook_depth_usdc,
            wallet_score=candidate.wallet_score,
            signal_score=candidate.signal_score,
            edge_remaining_bps=candidate.edge_remaining_bps,
            signal_age_ms=candidate.signal_age_ms,
        )
        risk_decision = RiskEngine(self.settings).evaluate(risk_context)
        evidence = {
            "candidate": candidate.model_dump(mode="json"),
            "risk_decision": risk_decision.model_dump(mode="json"),
            "noyau": noyau_dict,
            "decision_layer": "local_decision_engine",
        }

        # Le noyau passe AVANT le RiskEngine : il questionne la PROVENANCE de l'edge, le
        # RiskEngine ne fait qu'en noter la VALEUR. Une valeur fabriquee bien notee reste
        # une valeur fabriquee.
        if noyau_refuse:
            return LocalDecision(
                action=DecisionAction.NO_TRADE,
                reasons=[str(noyau_dict.get("raison", "NOYAU_REFUS"))],
                candidate_id=candidate.id,
                evidence=evidence,
            )

        if not risk_decision.allowed:
            return LocalDecision(
                action=DecisionAction.NO_TRADE,
                reasons=list(risk_decision.reasons),
                candidate_id=candidate.id,
                evidence=evidence,
            )

        if action is DecisionAction.NO_TRADE:
            return LocalDecision(
                action=DecisionAction.NO_TRADE,
                reasons=["signal type is not executable in testnet mode"],
                candidate_id=candidate.id,
                evidence=evidence,
            )

        side = TestnetSide.LONG if candidate.side == "long" else TestnetSide.SHORT
        if action is DecisionAction.ENTER:
            testnet_action = TestnetAction.OPEN
            reduce_only = False
            request_notional = notional_usdc
        elif action is DecisionAction.REDUCE:
            testnet_action = TestnetAction.REDUCE
            reduce_only = True
            request_notional = notional_usdc
        elif action is DecisionAction.EXIT:
            testnet_action = TestnetAction.CLOSE
            reduce_only = True
            request_notional = 0.0
        else:
            return LocalDecision(
                action=DecisionAction.NO_TRADE,
                reasons=["signal action cannot be converted to a testnet request"],
                candidate_id=candidate.id,
                evidence=evidence,
            )
        request = TestnetOrderRequest(
            cloid=cloid,
            action=testnet_action,
            coin=candidate.coin,
            side=side,
            notional_usdc=request_notional,
            limit_price=candidate.observed_price,
            reduce_only=reduce_only,
            source_signal_id=candidate.id,
            evidence=evidence,
        )
        return LocalDecision(
            action=action,
            reasons=["risk gates passed; prepared testnet request"],
            candidate_id=candidate.id,
            order_request=request,
            evidence=evidence,
        )

    @staticmethod
    def _contexte_noyau(candidate: SignalCandidate, notional_usdc: float) -> noyau.Contexte:
        """Traduit un candidat en question posee au noyau.

        🔴 `edge_fourni_bps=candidate.edge_remaining_bps` : on le donne au noyau *pour qu'il le
        CONFRONTE*, pas pour qu'il s'en serve. Le noyau ira chercher l'edge lui-meme dans la
        table mesuree. Si l'appelant s'etait fabrique un chiffre, la contradiction sera ECRITE
        dans la preuve (`EDGE_FOURNI_PAR_L_APPELANT_CONTREDIT_LA_MESURE`).

        Un `SignalCandidate` est, par construction, le fill PUBLIC d'un leader (`source_wallet`,
        `signal_type` open/add/...). Sa famille est donc DISCRETIONNAIRE_PUBLIC -- la zone morte
        que Q1 et Q3 ont mesuree. On ne la deguise pas en autre chose pour la faire passer.

        Aucun carnet n'est disponible ici (`SignalCandidate` n'en porte pas) : les niveaux sont
        donc `None`. Ce n'est PAS un laissez-passer -- le noyau refusera sur
        `NOYAU_PRIX_NON_EXECUTABLE` si jamais la famille redevenait vivante. On n'invente jamais
        un prix pour combler un trou.
        """
        return noyau.Contexte(
            strategie="COPY",
            coin=candidate.coin,
            direction="LONG" if candidate.side == "long" else "SHORT",
            notional_usd=float(notional_usdc),
            signal_ms=float(candidate.timestamp_ms),
            signal_age_ms=float(candidate.signal_age_ms),
            leader_score=float(candidate.wallet_score),
            consensus_wallets=None,
            niveaux_achat=None,
            niveaux_vente=None,
            # ═════════════════════════════════════════════════════════════════════════════════
            # 🔴🔴 CORRIGE LE 2026-07-14 — LE CHEMIN D'ENTREE LIVE PASSAIT UN PLANCHER DE **ZERO**.
            #
            # AVANT : `plancher_edge_net_bps=0.0` -- **explicitement**, dans le chemin LIVE.
            #         Un edge net de **+0,01 bps** franchissait la porte.
            #         Et CLAUDE.md dit : « plancher net par defaut **30 bps** ».
            #
            # 🚩 Trois planchers coexistaient : **0,0** (ici, le LIVE) · 8,0 (margin_of_safety)
            #    · 30,0 (edge_calculator, qui n'a AUCUN appelant).
            #    ***La maladie des « 6 fichiers, 4 valeurs » -- mais sur le CHEMIN DE DECISION.***
            #
            # 🔴 Et les frais : si `estimated_fee_bps` n'est pas rempli, le schema le met a **0,0**.
            #    On ne fait plus confiance : sous le cout d'un aller-retour taker, **on prend le
            #    vrai cout**. *Un cout absent n'est pas un cout nul.*
            # ═════════════════════════════════════════════════════════════════════════════════
            frais_bps=max(float(candidate.estimated_fee_bps),
                          noyau.FRAIS_ALLER_RETOUR_TAKER_BPS),
            degradation_copie_bps=float(candidate.estimated_latency_decay_bps),
            plancher_edge_net_bps=noyau.PLANCHER_NET_BPS,      # 30,0 -- PLUS JAMAIS zero
            edge_fourni_bps=float(candidate.edge_remaining_bps),
            # 🔴 #292b — LE DISJONCTEUR DE SESSION (les 11 gates V19).
            #
            # ***Ils ne servaient qu'a EXPLIQUER la perte apres coup*** (seul appelant :
            # `analysis/negative_pnl_auditor.py`). Ils passent desormais **AVANT** la porte.
            #
            # L'etat vient du LEDGER -- la source unique du PnL (regle du projet).
            # Si le ledger n'est pas branche, `etat_session_courant()` rend `None`, et le noyau
            # **SIGNALE** au lieu de faire semblant. *Un etat absent n'est pas un etat sain.*
            etat_session=etat_session_courant(),
        )

    @staticmethod
    def _action_from_signal(signal_type: str) -> DecisionAction:
        normalized = signal_type.lower()
        if normalized in {"open", "add"}:
            return DecisionAction.ENTER
        if normalized == "reduce":
            return DecisionAction.REDUCE
        if normalized == "close":
            return DecisionAction.EXIT
        return DecisionAction.NO_TRADE
