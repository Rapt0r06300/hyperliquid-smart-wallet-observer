"""G2 -- LE NOYAU UNIQUE. Un seul endroit decide. Et il POSSEDE l'edge.

LE TROU, TROUVE EN LISANT `local_engine.py`
===========================================
`LocalDecisionEngine.decide_from_candidate()` fait ceci :

    risk_context = RiskContext(..., edge_remaining_bps=candidate.edge_remaining_bps, ...)
    risk_decision = RiskEngine(self.settings).evaluate(risk_context)

Il prend l'edge **tel que l'appelant le lui donne**. Le RiskEngine note ensuite ce nombre avec une
arithmetique impeccable... sur une valeur qu'il n'a JAMAIS questionnee.

    >>> PERSONNE NE POSSEDE L'EDGE. <<<

Chaque moteur (copie, fraiche opportunite, arbitrage, funding, triangulaire) calcule le SIEN et le
passe au juge. Le juge juge le CHIFFRE, pas sa PROVENANCE. C'est exactement pour ca que trois edges
FABRIQUES ont pu vivre des mois dans le code :

    fresh_opportunity.py:342      14 + score*0,55 + wallets*9 + notional/25000 + tightness*10
    wallet_mirror_runtime.py:144  24 + score*24 + copyability*18
    ws_price_discrepancy.py:28    abs(mid_A - mid_B)          <- un prix qui n'existe pas

Onze constantes magiques et un prix inexecutable, tous notes serieusement par un RiskEngine qui
n'avait aucun moyen de savoir d'ou ils venaient.

CE QUE FAIT LE NOYAU
====================
Il pose QUATRE questions, dans cet ordre, et il REFUSE des la premiere qui echoue :

  1. FAMILLE DU SIGNAL   (Q3) -- d'ou vient l'information ? Une zone morte PROUVEE -> REFUS.
  2. EDGE BRUT           (Q1) -- il vient de la table MESUREE, JAMAIS d'un nombre fourni.
  3. PRIX EXECUTABLES    (Q2) -- bid/ask et profondeur reelle. Jamais le mid.
  4. EDGE NET            -- apres frais + spread + slippage + degradation. Sous le plancher -> REFUS.

🔴 LA REGLE QUI CHANGE TOUT :

    **Le noyau REFUSE un edge fourni par l'appelant.**

Si un moteur passe `edge_bps=42`, le noyau ne l'utilise pas : il le compare a l'edge MESURE et,
s'ils different, il le signale (`EDGE_FOURNI_CONTREDIT_LA_MESURE`). Un appelant ne peut plus
« s'auto-autoriser » en apportant son propre chiffre.

L'INVARIANT (le meme qui a marche 3 fois aujourd'hui)
=====================================================
    >>> TOUT MODULE QUI AUTORISE UNE ENTREE DOIT PASSER PAR LE NOYAU. <<<

`tests/test_noyau_unique.py` DECOUVRE (par AST, jamais a la main) tout module qui construit un
ordre/intention d'entree, et ECHOUE s'il ne passe pas par ici. Un inventaire se fait une fois et
se trompe ; un invariant se verifie a chaque execution.

Module PUR : aucune I/O, aucun reseau, aucun ordre reel. Simulation paper uniquement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.arbitrage.executable_legs import Jambe, jambe_executable
from hl_observer.edge.edge_source import SOURCE_FORMULE, EdgeBrut, edge_brut, source_configuree
from hl_observer.signals.signal_taxonomy import (
    CARRY_STRUCTUREL,
    DISCRETIONNAIRE_PUBLIC,
    FLUX_FORCE,
    PRE_EXECUTION,
    verdict_du_signal,
)

# --------------------------------------------------------------------------- verdicts

ENTREE = "ENTREE"
NO_TRADE = "NO_TRADE"

# Les refus, dans l'ordre ou ils tombent. Chacun dit POURQUOI, pas seulement QUE.
REFUS_ZONE_MORTE = "NOYAU_SIGNAL_DANS_UNE_ZONE_MORTE_PROUVEE"
REFUS_FAMILLE_INCONNUE = "NOYAU_FAMILLE_DE_SIGNAL_INCONNUE"
REFUS_EDGE_NON_MESURE = "NOYAU_EDGE_NON_MESURE"
REFUS_EDGE_FABRIQUE = "NOYAU_EDGE_FABRIQUE_PAR_UNE_FORMULE"
REFUS_PRIX_NON_EXECUTABLE = "NOYAU_PRIX_NON_EXECUTABLE"
REFUS_EDGE_NET_INSUFFISANT = "NOYAU_EDGE_NET_INSUFFISANT_APRES_COUTS"
REFUS_NOTIONAL_INVALIDE = "NOYAU_NOTIONAL_INVALIDE"

# Signalements (n'empechent pas forcement, mais laissent une trace INEFFACABLE)
EDGE_FOURNI_CONTREDIT_LA_MESURE = "EDGE_FOURNI_PAR_L_APPELANT_CONTREDIT_LA_MESURE"
EDGE_FOURNI_IGNORE = "EDGE_FOURNI_PAR_L_APPELANT_IGNORE"

# La strategie -> la famille de signal. Deny-by-default : un nom inconnu n'est PAS suppose vivant.
FAMILLE_PAR_STRATEGIE: dict[str, str] = {
    "COPY": DISCRETIONNAIRE_PUBLIC,
    "COPY_FOLLOW": DISCRETIONNAIRE_PUBLIC,
    "MIRROR": DISCRETIONNAIRE_PUBLIC,
    "SNIPER": DISCRETIONNAIRE_PUBLIC,
    "GRINDER": DISCRETIONNAIRE_PUBLIC,
    "FRESH_OPPORTUNITY": DISCRETIONNAIRE_PUBLIC,
    "FUNDING": CARRY_STRUCTUREL,
    "CARRY": CARRY_STRUCTUREL,
    "BASIS": CARRY_STRUCTUREL,
    "LIQUIDATION": FLUX_FORCE,
    "ADL": FLUX_FORCE,
    "ORACLE_LAG": FLUX_FORCE,
    "MEMPOOL": PRE_EXECUTION,
    "DEPOT": PRE_EXECUTION,
    # ARBITRAGE : la famille depend du MECANISME, pas du nom. Un arbitrage cross-venue sur des
    # prix executables est du FLUX_FORCE (la divergence se referme mecaniquement). Mais tant
    # qu'on ne collecte pas de carnet CEX, il n'est pas mesurable -> il tombera sur EDGE_NON_MESURE.
    "ARBITRAGE": FLUX_FORCE,
}


@dataclass(frozen=True, slots=True)
class Contexte:
    """Tout ce que le noyau a besoin de savoir. RIEN de plus, RIEN d'implicite."""

    strategie: str
    coin: str
    direction: str
    notional_usd: float
    signal_ms: float | None = None
    signal_age_ms: float | None = None
    leader_score: float | None = None
    consensus_wallets: float | None = None

    # Le carnet REEL (Q2). Absent -> on ne peut pas juger l'executabilite.
    niveaux_achat: list[tuple[float, float]] | None = None    # asks (on paye)
    niveaux_vente: list[tuple[float, float]] | None = None     # bids (on encaisse)

    # Les couts REELS, en bps. Jamais des constantes silencieuses.
    frais_bps: float = 0.0
    degradation_copie_bps: float = 0.0
    plancher_edge_net_bps: float = 0.0

    # 🔴 L'edge que l'appelant CROIT avoir. Le noyau NE L'UTILISE PAS -- il le compare.
    edge_fourni_bps: float | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: str                      # ENTREE | NO_TRADE
    raison: str
    famille: str = ""
    edge_brut_bps: float | None = None
    edge_net_bps: float | None = None
    couts_bps: float | None = None
    slippage_bps: float | None = None
    edge_fabrique: bool = False
    jambe: Jambe | None = None
    signalements: tuple[str, ...] = field(default_factory=tuple)
    preuve: dict = field(default_factory=dict)

    @property
    def autorise(self) -> bool:
        return self.verdict == ENTREE

    @property
    def paper_only(self) -> bool:
        return True

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "raison": self.raison,
            "famille": self.famille,
            "edge_brut_bps": self.edge_brut_bps,
            "edge_net_bps": self.edge_net_bps,
            "couts_bps": self.couts_bps,
            "slippage_bps": self.slippage_bps,
            "edge_fabrique": self.edge_fabrique,
            "signalements": list(self.signalements),
            "preuve": dict(self.preuve),
            "paper_only": True,
            "real_execution": False,
        }


def _refus(raison: str, **kw) -> Decision:
    return Decision(verdict=NO_TRADE, raison=raison, **kw)


def famille_de_la_strategie(strategie: str) -> str:
    """Deny-by-default : une strategie inconnue n'a PAS de famille, donc pas de droit d'entrer."""
    return FAMILLE_PAR_STRATEGIE.get(str(strategie or "").strip().upper(), "")


def decider(ctx: Contexte, *, table=None, racine=None) -> Decision:
    """L'UNIQUE porte. Quatre questions, dans l'ordre. Le premier NON l'emporte.

    Le noyau ne PROMET rien. Il refuse, ou il autorise en laissant sa preuve.
    """
    signalements: list[str] = []
    preuve: dict = {"strategie": ctx.strategie, "coin": ctx.coin, "direction": ctx.direction,
                    "notional_usd": ctx.notional_usd}

    if not (float(ctx.notional_usd) > 0.0):
        return _refus(REFUS_NOTIONAL_INVALIDE, preuve=preuve)

    # ---------------------------------------------------------------- 1. LA FAMILLE (Q3)
    fam = famille_de_la_strategie(ctx.strategie)
    preuve["famille"] = fam or "INCONNUE"
    if not fam:
        return _refus(REFUS_FAMILLE_INCONNUE, preuve=preuve)

    autorise_a_chercher, verdict_fam = verdict_du_signal(fam)
    preuve["verdict_famille"] = verdict_fam
    if not autorise_a_chercher:
        # Zone morte PROUVEE. Ce n'est pas de la prudence : c'est 3 mesures independantes.
        return _refus(REFUS_ZONE_MORTE, famille=fam, preuve=preuve)

    # ---------------------------------------------------------------- 2. L'EDGE BRUT (Q1)
    #
    # 🔴 ICI EST LE COEUR DE G2 : le noyau VA CHERCHER l'edge. Il ne le RECOIT pas.
    #
    # Le mode `formule` reste ALLUMABLE (flag explicite, pour comparer / rejouer l'histoire).
    # Mais il ne FRANCHIT PAS le noyau : on peut mentir a la machine, la machine ne tradera pas
    # sur le mensonge. Et on le dit AVANT de calculer quoi que ce soit, pour que la raison du
    # refus nomme la cause reelle (le mode) et pas son symptome (« edge non mesure »).
    if source_configuree() == SOURCE_FORMULE:
        return _refus(REFUS_EDGE_FABRIQUE, famille=fam, edge_fabrique=True, preuve=preuve)

    e: EdgeBrut = edge_brut(
        coin=ctx.coin,
        direction=ctx.direction,
        signal_age_ms=ctx.signal_age_ms,
        leader_score=ctx.leader_score,
        consensus_wallets=ctx.consensus_wallets,
        signal_ms=ctx.signal_ms,
        strategie=ctx.strategie,
        formule_de_secours=None,          # <- AUCUN repli. Le noyau ne fabrique jamais.
        table=table,
        racine=racine,
    )
    preuve["edge_source"] = e.as_dict() if hasattr(e, "as_dict") else {"raison": e.raison}

    # L'edge que l'appelant CROYAIT avoir : on le CONFRONTE, on ne l'utilise pas.
    if ctx.edge_fourni_bps is not None:
        signalements.append(EDGE_FOURNI_IGNORE)
        preuve["edge_fourni_bps"] = float(ctx.edge_fourni_bps)
        if e.valeur_bps is not None and abs(float(ctx.edge_fourni_bps) - e.valeur_bps) > 1.0:
            # Il ne bloque pas -- mais il laisse une trace que personne ne pourra effacer.
            signalements.append(EDGE_FOURNI_CONTREDIT_LA_MESURE)

    if e.fabrique:
        # Le mode `formule` est autorise (flag explicite), mais il ne franchit PAS le noyau.
        return _refus(REFUS_EDGE_FABRIQUE, famille=fam, edge_fabrique=True,
                      edge_brut_bps=e.valeur_bps, signalements=tuple(signalements), preuve=preuve)
    if not e.utilisable:
        return _refus(REFUS_EDGE_NON_MESURE, famille=fam,
                      signalements=tuple(signalements), preuve=preuve)

    edge_b = float(e.valeur_bps or 0.0)

    # ---------------------------------------------------------------- 3. LES PRIX (Q2)
    niveaux = ctx.niveaux_achat if str(ctx.direction).upper() == "LONG" else ctx.niveaux_vente
    sens = "ACHAT" if str(ctx.direction).upper() == "LONG" else "VENTE"
    j = jambe_executable(niveaux, sens=sens, notional_usd=ctx.notional_usd)
    preuve["jambe"] = j.as_dict()
    if not j.executable:
        # Carnet vide, prix invalide, ou profondeur insuffisante. On n'invente pas de prix.
        return _refus(REFUS_PRIX_NON_EXECUTABLE, famille=fam, edge_brut_bps=edge_b, jambe=j,
                      signalements=tuple(signalements), preuve=preuve)

    slip = float(j.slippage_bps or 0.0)

    # ---------------------------------------------------------------- 4. L'EDGE NET
    couts = (max(0.0, float(ctx.frais_bps))
             + slip
             + max(0.0, float(ctx.degradation_copie_bps)))
    edge_n = edge_b - couts
    preuve["couts_bps"] = couts
    preuve["edge_net_bps"] = edge_n

    if edge_n < float(ctx.plancher_edge_net_bps):
        return _refus(REFUS_EDGE_NET_INSUFFISANT, famille=fam, edge_brut_bps=edge_b,
                      edge_net_bps=edge_n, couts_bps=couts, slippage_bps=slip, jambe=j,
                      signalements=tuple(signalements), preuve=preuve)

    return Decision(
        verdict=ENTREE,
        raison="NOYAU_EDGE_NET_MESURE_ET_EXECUTABLE",
        famille=fam,
        edge_brut_bps=edge_b,
        edge_net_bps=edge_n,
        couts_bps=couts,
        slippage_bps=slip,
        edge_fabrique=False,
        jambe=j,
        signalements=tuple(signalements),
        preuve=preuve,
    )


__all__ = [
    "ENTREE", "NO_TRADE",
    "REFUS_ZONE_MORTE", "REFUS_FAMILLE_INCONNUE", "REFUS_EDGE_NON_MESURE",
    "REFUS_EDGE_FABRIQUE", "REFUS_PRIX_NON_EXECUTABLE", "REFUS_EDGE_NET_INSUFFISANT",
    "REFUS_NOTIONAL_INVALIDE",
    "EDGE_FOURNI_CONTREDIT_LA_MESURE", "EDGE_FOURNI_IGNORE",
    "FAMILLE_PAR_STRATEGIE",
    "Contexte", "Decision", "decider", "famille_de_la_strategie",
]
