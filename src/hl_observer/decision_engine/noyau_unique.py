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
from hl_observer.edge.carry_edge_source import edge_de_carry_bps   # 🔑 l'edge OBSERVE, pas predit
from hl_observer.edge.edge_source import SOURCE_FORMULE, EdgeBrut, edge_brut, source_configuree
from hl_observer.signals.signal_taxonomy import (
    CARRY_STRUCTUREL,
    DISCRETIONNAIRE_PUBLIC,
    FLUX_FORCE,
    PRE_EXECUTION,
    verdict_du_signal,
)

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔴 BRANCHEMENT DU 2026-07-14 — « rien n'est branché sur la simulation » (Flo).
#
# Il avait raison : **22 modules livrés, 3 branchés.** *Un module qui existe n'est pas un module
# qui garde.* Les quatre ci-dessous ont leur place **DANS LA PORTE**, pas à côté d'elle.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
from hl_observer.fees.hyperliquid_fees import nos_frais           # #543 — la SOURCE UNIQUE
from hl_observer.market.execution_constraints import (            # #576/#498 — physiquement possible ?
    NOTIONNEL_MIN_USD,
    valider_ordre,
)
from hl_observer.market.flow_toxicity import faut_il_s_abstenir   # #521 — quand NE PAS trader
from hl_observer.market.spot_depth import marcher_dans_le_carnet  # 🔴 LA JAMBE SPOT (2e jambe !)
from hl_observer.risk.session_gate import (                       # #292b — LES 11 GATES V19
    EtatSession,
    evaluer_session,
)
from hl_observer.risk.side_lock import only_per_side              # #566 — 19/21 SHORT

_PERP = nos_frais("perp")

# 🔴 PLUS JAMAIS ZERO. Un aller-retour taker : entrée + sortie.
FRAIS_ALLER_RETOUR_TAKER_BPS = 2 * _PERP.taker_bps                # 9,0 bps

# Le plancher net réel (CLAUDE.md : « plancher net par défaut 30 bps »).
PLANCHER_NET_BPS = 30.0

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

# --- les 4 refus BRANCHES le 2026-07-14 ---
REFUS_ORDRE_IMPOSSIBLE = "NOYAU_ORDRE_REFUSE_PAR_L_EXCHANGE"      # #576 : notionnel min, tick/lot
REFUS_FLUX_TOXIQUE = "NOYAU_FLUX_TOXIQUE_ON_S_ABSTIENT"           # #521 : VPIN
REFUS_COTE_VERROUILLEE = "NOYAU_COTE_REFUSEE_PAR_only_per_side"   # #566 : 19/21 SHORT
REFUS_SESSION_EN_HALTE = "NOYAU_SESSION_EN_HALTE_GATES_V19"       # #292b : les 11 disjoncteurs

# 🔴 2026-07-14 — LA JAMBE SPOT. *Un carry a DEUX jambes ; le noyau n'en verifiait qu'UNE.*
# Mesure : le carnet spot de PUMP ne peut pas absorber 500 $ (473 $ dispo).
# ***Un carry dont la jambe spot ne se remplit pas n'est pas un carry : c'est un short A NU.***
REFUS_JAMBE_SPOT_IMPOSSIBLE = "NOYAU_JAMBE_SPOT_IMPOSSIBLE_CARNET_TROP_MINCE"

# Un signalement, pas un refus : l'etat de session n'a pas ete fourni.
# *Un etat absent n'est pas un etat sain.* -> un invariant AST oblige le LIVE a le fournir.
ETAT_SESSION_NON_FOURNI = "ETAT_SESSION_NON_FOURNI"

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

    # ═════════════════════════════════════════════════════════════════════════════════════════
    # 🔴🔴 CORRIGE LE 2026-07-14 — LE PIRE BUG DU PROJET, ET IL ETAIT DANS LA PORTE UNIQUE.
    #
    # AVANT :   frais_bps = 0.0   ·   plancher_edge_net_bps = 0.0
    #
    # ***Si l'appelant ne passait rien : COUTS = ZERO, PLANCHER = ZERO.***
    # Un edge de **+0,01 bps** etait ACCEPTE. Le deny-by-default viole par des **zeros
    # silencieux** -- dans la fonction qui autorise CHAQUE entree.
    #
    # 🚩 Et le commentaire juste au-dessus disait deja : « Les couts REELS, en bps.
    #    **Jamais des constantes silencieuses.** »
    #    ***La docstring mettait en garde contre exactement ce que le code faisait.***
    #    (C'est la signature de ce projet : voir GARCH, `signal_age`, le voyant soude.)
    #
    # APRES : les defauts viennent de la **SOURCE UNIQUE DE VERITE** des frais (#543), et le
    # plancher vaut son vrai plancher. **Un appelant distrait paie desormais le vrai prix.**
    # ═════════════════════════════════════════════════════════════════════════════════════════
    frais_bps: float = FRAIS_ALLER_RETOUR_TAKER_BPS      # 9,0 bps -- PLUS JAMAIS zero
    degradation_copie_bps: float = 0.0
    plancher_edge_net_bps: float = PLANCHER_NET_BPS      # 30,0 bps -- PLUS JAMAIS zero

    # 🔴 L'edge que l'appelant CROIT avoir. Le noyau NE L'UTILISE PAS -- il le compare.
    edge_fourni_bps: float | None = None

    # --- BRANCHES le 2026-07-14 (Flo : « rien n'est branché sur la simulation ») -------------
    # #566 — les cotes DEJA ouvertes, pour que `only_per_side` puisse voir le desequilibre.
    #        (19 de nos 21 ouvertures etaient des SHORT : 1 chance sur 4 520.)
    ouvertures_en_cours: tuple[str, ...] = ()
    cote_autorisee: str | None = None            # None = les deux

    # #521 — la toxicite du flux. 🔴 `None` = NON MESURE -> **on s'abstient** (deny-by-default).
    #        *Ne pas savoir si le flux est toxique n'est pas une permission de trader.*
    vpin: float | None = None
    exiger_vpin: bool = False                    # False par defaut : on n'a pas encore le flux live

    # #576/#498 — la taille de lot du coin, pour valider que l'ordre est PHYSIQUEMENT possible.
    sz_decimals: int | None = None

    # 🔴 #292b — L'ETAT DE LA SESSION (les 11 gates V19).
    #
    # ***Les 11 gates qui auraient pu EMPECHER la perte ne servaient qu'a l'EXPLIQUER apres coup :
    # leur seul appelant etait `analysis/negative_pnl_auditor.py`.***
    #
    # `None` -> on ne pretend PAS que la session est saine : on le SIGNALE.
    # *Un etat absent n'est pas un etat sain.*
    etat_session: EtatSession | None = None

    # ═════════════════════════════════════════════════════════════════════════════════════════
    # 🔴🔴 LE CARNET **SPOT** — branche le 2026-07-14. *La 18e forme de la maladie.*
    #
    # Le noyau verifiait le carnet **PERP**... et **PAS** le carnet **SPOT**.
    # Or un carry a **DEUX** jambes. La jambe spot etait **totalement non verifiee**.
    #
    # 🔑 LA MESURE QUI L'A REVELE : le carnet spot de **PUMP** ne peut pas absorber 500 $
    #    (**473 $ disponibles**). Le bot l'aurait ouvert quand meme -- sur une jambe spot
    #    qu'il ne pouvait **pas** remplir. *Ce n'est plus un carry : c'est un short perp A NU.*
    #
    # Et PURR perd **4,4 points d'APR** au slippage (11,31 -> 6,91 %) : sa jambe de VENTE spot
    # glisse de **47 bps**. *Le prix affiche n'est pas le prix qu'on obtient.*
    #
    # `None` -> pour un CARRY, **on REFUSE**. *Une jambe non verifiee n'est pas une jambe sure.*
    # ═════════════════════════════════════════════════════════════════════════════════════════
    niveaux_spot_achat: list[tuple[float, float]] | None = None   # asks spot (on ACHETE)
    niveaux_spot_vente: list[tuple[float, float]] | None = None   # bids spot (on REVENDRA)


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

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 0. 🔴 #292b — LE DISJONCTEUR DE SESSION (les 11 gates V19), BRANCHE LE 2026-07-14.
    #
    # ***Les 11 gates qui auraient pu EMPECHER la perte ne servaient qu'a l'EXPLIQUER apres coup.***
    # Leur seul appelant etait `analysis/negative_pnl_auditor.py` -- **l'AUTOPSIE**.
    #
    # Il passe EN PREMIER, avant la famille, avant l'edge, avant les prix.
    # *Un disjoncteur qui se laisse convaincre par un bon argument n'est pas un disjoncteur :
    #  si la session est en halte, AUCUN edge, si beau soit-il, ne rouvre la porte.*
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    v_session = evaluer_session(ctx.etat_session)
    preuve["session"] = v_session.as_dict()
    if v_session.motif == ETAT_SESSION_NON_FOURNI:
        # On ne bloque pas (sinon rien ne tournerait), mais on **laisse une trace indelebile**.
        signalements.append(ETAT_SESSION_NON_FOURNI)
    if v_session.bloque:
        return _refus(REFUS_SESSION_EN_HALTE, signalements=tuple(signalements), preuve=preuve)

    # ---------------------------------------------------------------- 1. LA FAMILLE (Q3)
    fam = famille_de_la_strategie(ctx.strategie)
    preuve["famille"] = fam or "INCONNUE"
    if not fam:
        # 🔴 CORRIGE 2026-07-14 : ce refus JETAIT les signalements. Un test rouge l'a trouve.
        # *Un refus qui perd la trace de ce qu'il a vu est un refus qui ment par omission.*
        return _refus(REFUS_FAMILLE_INCONNUE, signalements=tuple(signalements), preuve=preuve)

    autorise_a_chercher, verdict_fam = verdict_du_signal(fam)
    preuve["verdict_famille"] = verdict_fam
    if not autorise_a_chercher:
        # Zone morte PROUVEE. Ce n'est pas de la prudence : c'est 3 mesures independantes.
        # 🔴 Et il PORTE les signalements (dont ETAT_SESSION_NON_FOURNI) -- il les jetait.
        return _refus(REFUS_ZONE_MORTE, famille=fam,
                      signalements=tuple(signalements), preuve=preuve)

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

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🔑 L'EDGE D'UN CARRY N'EST PAS **PRÉDIT**. IL EST **OBSERVÉ**. (2026-07-14)
    #
    # Le noyau refusait le carry sur `NOYAU_EDGE_NON_MESURE` -- il cherchait dans la table
    # mesuree, **qui ne contient que des edges de COPY-TRADING**.
    #
    # Mais un carry n'est pas de la meme NATURE :
    #   * COPY  -> l'edge est une **PREDICTION** (« le prix va monter »). Elle DOIT venir d'une
    #              mesure OOS, sinon c'est une invention. *Et la mesure a dit : -7,97 bps.*
    #   * CARRY -> l'edge est un **PAIEMENT DEJA ENCAISSE**. Le funding a ete verse, heure par
    #              heure, pendant **365 jours**. ***On ne le predit pas : on le LIT.***
    #
    # 🔒 Ce n'est PAS une porte derobee : elle ne s'ouvre QUE pour `CARRY_STRUCTUREL`, la donnee
    #    doit exister sur disque (>= 30 j), la moyenne doit etre positive, et l'edge est **BORNE
    #    par l'horizon de detention** (on n'annualise pas pour faire joli).
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    if fam == CARRY_STRUCTUREL:
        edge_c, motif_c, preuve_c = edge_de_carry_bps(ctx.coin, ctx.strategie)
        preuve["edge_source"] = preuve_c | {"motif": motif_c}
        if edge_c is None:
            return _refus(REFUS_EDGE_NON_MESURE, famille=fam,
                          signalements=tuple(signalements), preuve=preuve)
        e = EdgeBrut(valeur_bps=float(edge_c), fabrique=False, raison=motif_c)
    else:
        e = edge_brut(
            coin=ctx.coin,
            direction=ctx.direction,
            signal_age_ms=ctx.signal_age_ms,
            leader_score=ctx.leader_score,
            consensus_wallets=ctx.consensus_wallets,
            signal_ms=ctx.signal_ms,
            strategie=ctx.strategie,
            formule_de_secours=None,      # <- AUCUN repli. Le noyau ne fabrique jamais.
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

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 5-6-7. LES TROIS PORTES BRANCHEES LE 2026-07-14
    #
    # 🔴 Flo : « en gros rien n'est vraiment branche sur la simulation ? » -- **il avait raison.**
    # 22 modules livres, 3 branches. *Un module qui existe n'est pas un module qui garde.*
    # Ces trois-la refusent des entrees que le noyau AUTORISAIT jusqu'ici.
    # ═══════════════════════════════════════════════════════════════════════════════════════════

    # ---- 5. #566 -- LA COTE (only_per_side). 19/21 SHORT = 1 chance sur 4 520. -----------------
    #
    # 🔴 BUG DE MON PROPRE CABLAGE, CORRIGE LE 2026-07-14 :
    #
    #    `only_per_side` mesure un **DESEQUILIBRE DIRECTIONNEL** -- il est ne de nos 19 SHORT
    #    sur 21 (P = 1 sur 4 520). Il a toute sa place pour un signal directionnel.
    #
    #    ***MAIS UN CARRY EST DELTA-NEUTRE.***
    #    Short le PERP **+** long le SPOT = **exposition nette ZERO**. La jambe perp n'est pas
    #    un pari a la baisse : c'est la moitie d'une couverture.
    #
    #    -> Compter la jambe perp d'un carry comme de l'exposition SHORT est **FAUX**, et ca
    #       refusait PUMP et HYPE **a tort**.
    #
    #    *Un garde-fou appliqué au mauvais objet ne protège pas : il mutile.*
    #    (Comme le garde-fou de concentration qui refusait TOUTE premiere position.)
    #
    # 🔒 Le garde reste **INTACT** pour tout ce qui est directionnel. Il ne s'efface QUE pour
    #    une famille structurellement couverte.
    if fam != CARRY_STRUCTUREL:
        ok_cote, motif_cote = only_per_side(
            "SHORT" if str(ctx.direction).upper() == "SHORT" else "LONG",
            ouvertures_en_cours=list(ctx.ouvertures_en_cours),
            cote_autorise=ctx.cote_autorisee,
        )
        preuve["side_lock"] = motif_cote
        if not ok_cote:
            return _refus(REFUS_COTE_VERROUILLEE, famille=fam, edge_brut_bps=edge_b,
                          edge_net_bps=edge_n, couts_bps=couts, slippage_bps=slip, jambe=j,
                          signalements=tuple(signalements), preuve=preuve)
    else:
        preuve["side_lock"] = ("NON_APPLICABLE_CARRY_DELTA_NEUTRE : short perp + long spot "
                               "= exposition nette ZERO. *La jambe perp n'est pas un pari.*")

    # ---- 6. #521 -- LA TOXICITE DU FLUX (VPIN). ------------------------------------------------
    # ⚠️ `exiger_vpin=False` par defaut : on n'a pas encore le flux de trades live branche.
    #    **Quand on l'aura, passer a True** -> un VPIN non mesurable fera S'ABSTENIR.
    #    *Ne pas savoir si le flux est toxique n'est pas une permission de trader.*
    if ctx.exiger_vpin or ctx.vpin is not None:
        s_abstenir, motif_vpin = faut_il_s_abstenir(ctx.vpin)
        preuve["vpin"] = motif_vpin
        if s_abstenir:
            return _refus(REFUS_FLUX_TOXIQUE, famille=fam, edge_brut_bps=edge_b,
                          edge_net_bps=edge_n, couts_bps=couts, slippage_bps=slip, jambe=j,
                          signalements=tuple(signalements), preuve=preuve)

    # ---- 7. #576/#498 -- L'ORDRE EST-IL PHYSIQUEMENT POSSIBLE ? --------------------------------
    # ***Un trade que l'exchange aurait REFUSE et qu'on compte quand meme est un trade INVENTE.***
    if ctx.sz_decimals is not None and j.prix and j.prix > 0:
        v = valider_ordre(
            prix=float(j.prix),
            taille=float(ctx.notional_usd) / float(j.prix),
            sz_decimals=int(ctx.sz_decimals),
            post_only=False,
        )
        preuve["exchange"] = v.as_dict()
        if not v.valide:
            return _refus(REFUS_ORDRE_IMPOSSIBLE, famille=fam, edge_brut_bps=edge_b,
                          edge_net_bps=edge_n, couts_bps=couts, slippage_bps=slip, jambe=j,
                          signalements=tuple(signalements), preuve=preuve)
    elif float(ctx.notional_usd) < NOTIONNEL_MIN_USD:
        # meme sans szDecimals, le notionnel minimum de 10 $ s'applique (doc : MinTradeNtl)
        preuve["exchange"] = {"motif": "MinTradeNtl", "notionnel": float(ctx.notional_usd)}
        return _refus(REFUS_ORDRE_IMPOSSIBLE, famille=fam, edge_brut_bps=edge_b,
                      edge_net_bps=edge_n, couts_bps=couts, slippage_bps=slip, jambe=j,
                      signalements=tuple(signalements), preuve=preuve)

    # ---- 8. 🔴🔴 LA JAMBE **SPOT** — *un carry a DEUX jambes. On n'en verifiait qu'UNE.* -------
    #
    # Le noyau validait le carnet **PERP** et ignorait totalement le carnet **SPOT**.
    #
    # 🔑 CE QUE LA MESURE A TROUVE :
    #    * **PUMP** : son carnet spot ne peut pas absorber 500 $ (**473 $ dispo**).
    #      Le bot l'aurait ouvert -- sur une jambe qu'il ne pouvait **pas** remplir.
    #      ***Un carry dont la jambe spot ne se remplit pas est un short perp A NU.***
    #    * **PURR** : sa jambe de VENTE spot glisse de **47 bps** -> l'APR tombe de
    #      **11,31 % a 6,91 %**. *Le prix affiche n'est pas le prix qu'on obtient.*
    #
    # 🔒 Pour un CARRY, un carnet spot **absent** = **REFUS**.
    #    *Une jambe non verifiee n'est pas une jambe sure. Ne pas savoir n'est pas une permission.*
    if fam == CARRY_STRUCTUREL:
        a_spot = ctx.niveaux_spot_achat
        v_spot = ctx.niveaux_spot_vente
        if not a_spot or not v_spot:
            preuve["spot"] = ("CARNET_SPOT_NON_FOURNI : un carry a DEUX jambes. "
                              "*Une jambe non verifiee n'est pas une jambe sure.*")
            return _refus(REFUS_JAMBE_SPOT_IMPOSSIBLE, famille=fam, edge_brut_bps=edge_b,
                          edge_net_bps=edge_n, couts_bps=couts, slippage_bps=slip, jambe=j,
                          signalements=tuple(signalements), preuve=preuve)

        achat = marcher_dans_le_carnet(list(a_spot), float(ctx.notional_usd))
        vente = marcher_dans_le_carnet(list(v_spot), float(ctx.notional_usd))
        preuve["spot"] = {"achat": achat.as_dict(), "vente": vente.as_dict()}

        if not achat.rempli or not vente.rempli:
            preuve["spot"]["motif"] = (
                "CARNET_SPOT_TROP_MINCE : la jambe spot ne se remplit pas pour %.0f $. "
                "*Un edge sur un carnet de 3 $ n'existe pas.*" % float(ctx.notional_usd)
            )
            return _refus(REFUS_JAMBE_SPOT_IMPOSSIBLE, famille=fam, edge_brut_bps=edge_b,
                          edge_net_bps=edge_n, couts_bps=couts, slippage_bps=slip, jambe=j,
                          signalements=tuple(signalements), preuve=preuve)

        # 🔴 Le slippage spot est un COUT REEL : il doit RE-passer le plancher net.
        #    *Un cout qu'on mesure mais qu'on ne soustrait pas est un cout qu'on cache.* (17e fois)
        slip_spot = achat.slippage_bps + vente.slippage_bps

        # 🔴🔴 ET LA **SORTIE** DU PERP. *On ouvre une position ; il faudra bien la REFERMER.*
        #
        #    `jambe_executable` ne chiffre que l'**ENTREE**. La porte etait donc **optimiste** :
        #    elle annoncait +8,31 % la ou la mesure complete (4 jambes) disait **+6,6 %**.
        #    ***Deux nombres pour la meme chose : l'un des deux ment.***
        #
        #    Un carry SHORT perp : on VEND dans les bids a l'entree, on RACHETE dans les asks
        #    a la sortie. **Les deux glissent.** *Une sortie qu'on ne chiffre pas est une sortie
        #    qu'on suppose gratuite -- et rien n'est gratuit dans un carnet.*
        sortie_perp = None
        if ctx.niveaux_achat:
            sortie_perp = marcher_dans_le_carnet(list(ctx.niveaux_achat),
                                                 float(ctx.notional_usd))
            preuve["spot"]["sortie_perp"] = sortie_perp.as_dict()
            if not sortie_perp.rempli:
                preuve["spot"]["motif"] = (
                    "CARNET_PERP_TROP_MINCE_POUR_SORTIR : on pourrait ENTRER mais pas SORTIR. "
                    "*Une position qu'on ne peut pas refermer n'est pas une position : c'est un "
                    "piege.*"
                )
                return _refus(REFUS_JAMBE_SPOT_IMPOSSIBLE, famille=fam, edge_brut_bps=edge_b,
                              edge_net_bps=edge_n, couts_bps=couts, slippage_bps=slip, jambe=j,
                              signalements=tuple(signalements), preuve=preuve)
            slip_spot += sortie_perp.slippage_bps

        preuve["spot"]["slippage_total_bps"] = round(slip_spot, 3)
        edge_apres_spot = edge_n - slip_spot
        preuve["spot"]["edge_net_apres_slippage_spot_bps"] = round(edge_apres_spot, 3)
        if edge_apres_spot < float(ctx.plancher_edge_net_bps):
            preuve["spot"]["motif"] = (
                "LE_SLIPPAGE_SPOT_MANGE_L_EDGE : %.2f bps de glissement -> edge net %.2f bps "
                "< plancher %.2f bps." % (slip_spot, edge_apres_spot,
                                          float(ctx.plancher_edge_net_bps))
            )
            return _refus(REFUS_EDGE_NET_INSUFFISANT, famille=fam, edge_brut_bps=edge_b,
                          edge_net_bps=edge_apres_spot, couts_bps=couts + slip_spot,
                          slippage_bps=slip + slip_spot, jambe=j,
                          signalements=tuple(signalements), preuve=preuve)

        # l'edge PUBLIE est celui d'APRES le slippage spot. **Jamais le chiffre d'avant.**
        edge_n = edge_apres_spot
        couts += slip_spot
        slip += slip_spot

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
    "REFUS_ORDRE_IMPOSSIBLE", "REFUS_FLUX_TOXIQUE", "REFUS_COTE_VERROUILLEE",
    "REFUS_SESSION_EN_HALTE", "REFUS_JAMBE_SPOT_IMPOSSIBLE",
    "ETAT_SESSION_NON_FOURNI",
    "EDGE_FOURNI_CONTREDIT_LA_MESURE", "EDGE_FOURNI_IGNORE",
    "FAMILLE_PAR_STRATEGIE", "FRAIS_ALLER_RETOUR_TAKER_BPS", "PLANCHER_NET_BPS",
    "Contexte", "Decision", "decider", "famille_de_la_strategie",
]
