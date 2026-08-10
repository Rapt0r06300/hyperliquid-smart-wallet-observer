"""Porte de décision unique HyperSmart — paper-only, deny-by-default.

Le noyau possède l'edge : un appelant ne peut jamais s'auto-autoriser avec son propre chiffre.
Pour une stratégie directionnelle, l'ordre logique reste edge mesuré -> prix exécutable -> edge net.
Pour un carry delta-neutre, la sûreté physique prime : perp d'entrée, deux côtés spot et perp de
sortie sont prouvés AVANT de demander l'edge funding. Une jambe impossible ne doit jamais être
masquée derrière « edge non mesuré ».
"""
from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.arbitrage.executable_legs import Jambe, jambe_executable
from hl_observer.edge.carry_edge_source import edge_de_carry_bps
from hl_observer.edge.edge_source import SOURCE_FORMULE, EdgeBrut, edge_brut, source_configuree
from hl_observer.fees.hyperliquid_fees import nos_frais
from hl_observer.market.execution_constraints import NOTIONNEL_MIN_USD, valider_ordre
from hl_observer.market.flow_toxicity import faut_il_s_abstenir
from hl_observer.market.spot_depth import marcher_dans_le_carnet
from hl_observer.risk.session_gate import EtatSession, evaluer_session
from hl_observer.risk.side_lock import only_per_side
from hl_observer.signals.signal_taxonomy import (
    CARRY_STRUCTUREL,
    DISCRETIONNAIRE_PUBLIC,
    FLUX_FORCE,
    PRE_EXECUTION,
    verdict_du_signal,
)

_PERP = nos_frais("perp")
FRAIS_ALLER_RETOUR_TAKER_BPS = 2 * _PERP.taker_bps
PLANCHER_NET_BPS = 30.0

ENTREE = "ENTREE"
NO_TRADE = "NO_TRADE"
REFUS_ZONE_MORTE = "NOYAU_SIGNAL_DANS_UNE_ZONE_MORTE_PROUVEE"
REFUS_FAMILLE_INCONNUE = "NOYAU_FAMILLE_DE_SIGNAL_INCONNUE"
REFUS_EDGE_NON_MESURE = "NOYAU_EDGE_NON_MESURE"
REFUS_EDGE_FABRIQUE = "NOYAU_EDGE_FABRIQUE_PAR_UNE_FORMULE"
REFUS_PRIX_NON_EXECUTABLE = "NOYAU_PRIX_NON_EXECUTABLE"
REFUS_EDGE_NET_INSUFFISANT = "NOYAU_EDGE_NET_INSUFFISANT_APRES_COUTS"
REFUS_NOTIONAL_INVALIDE = "NOYAU_NOTIONAL_INVALIDE"
REFUS_QUALITE_FLUX = "NOYAU_QUALITE_FLUX_INSUFFISANTE"
REFUS_ORDRE_IMPOSSIBLE = "NOYAU_ORDRE_REFUSE_PAR_L_EXCHANGE"
REFUS_FLUX_TOXIQUE = "NOYAU_FLUX_TOXIQUE_ON_S_ABSTIENT"
REFUS_COTE_VERROUILLEE = "NOYAU_COTE_REFUSEE_PAR_only_per_side"
REFUS_SESSION_EN_HALTE = "NOYAU_SESSION_EN_HALTE_GATES_V19"
REFUS_JAMBE_SPOT_IMPOSSIBLE = "NOYAU_JAMBE_SPOT_IMPOSSIBLE_CARNET_TROP_MINCE"
ETAT_SESSION_NON_FOURNI = "ETAT_SESSION_NON_FOURNI"
QUALITE_FLUX_NON_FOURNIE = "QUALITE_FLUX_NON_FOURNIE"
EDGE_FOURNI_CONTREDIT_LA_MESURE = "EDGE_FOURNI_PAR_L_APPELANT_CONTREDIT_LA_MESURE"
EDGE_FOURNI_IGNORE = "EDGE_FOURNI_PAR_L_APPELANT_IGNORE"

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
    "ARBITRAGE": FLUX_FORCE,
}


@dataclass(frozen=True, slots=True)
class Contexte:
    strategie: str
    coin: str
    direction: str
    notional_usd: float
    signal_ms: float | None = None
    signal_age_ms: float | None = None
    leader_score: float | None = None
    consensus_wallets: float | None = None
    niveaux_achat: list[tuple[float, float]] | None = None
    niveaux_vente: list[tuple[float, float]] | None = None
    frais_bps: float = FRAIS_ALLER_RETOUR_TAKER_BPS
    degradation_copie_bps: float = 0.0
    plancher_edge_net_bps: float = PLANCHER_NET_BPS
    edge_fourni_bps: float | None = None
    ouvertures_en_cours: tuple[str, ...] = ()
    cote_autorisee: str | None = None
    vpin: float | None = None
    exiger_vpin: bool = False
    sz_decimals: int | None = None
    etat_session: EtatSession | None = None
    feed_quality_ready: bool | None = None
    feed_quality_score: float | None = None
    feed_quality_reasons: tuple[str, ...] = ()
    min_feed_quality_score: float = 75.0
    niveaux_spot_achat: list[tuple[float, float]] | None = None
    niveaux_spot_vente: list[tuple[float, float]] | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: str
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
    return FAMILLE_PAR_STRATEGIE.get(str(strategie or "").strip().upper(), "")


def _jambe_principale(ctx: Contexte) -> tuple[Jambe, str]:
    direction = str(ctx.direction).upper()
    niveaux = ctx.niveaux_achat if direction == "LONG" else ctx.niveaux_vente
    sens = "ACHAT" if direction == "LONG" else "VENTE"
    return jambe_executable(niveaux, sens=sens, notional_usd=ctx.notional_usd), sens


def _edge_mesure(ctx: Contexte, fam: str, *, table=None, racine=None) -> tuple[EdgeBrut | None, dict]:
    if fam == CARRY_STRUCTUREL:
        valeur, motif, details = edge_de_carry_bps(ctx.coin, ctx.strategie)
        preuve = dict(details or {}) | {"motif": motif}
        if valeur is None:
            return None, preuve
        return EdgeBrut(valeur_bps=float(valeur), fabrique=False, raison=motif), preuve
    e = edge_brut(
        coin=ctx.coin,
        direction=ctx.direction,
        signal_age_ms=ctx.signal_age_ms,
        leader_score=ctx.leader_score,
        consensus_wallets=ctx.consensus_wallets,
        signal_ms=ctx.signal_ms,
        strategie=ctx.strategie,
        formule_de_secours=None,
        table=table,
        racine=racine,
    )
    return e, e.as_dict() if hasattr(e, "as_dict") else {"raison": e.raison}


def _verifier_carry_executable(ctx: Contexte, preuve: dict, signalements: list[str]) -> tuple[Decision | None, Jambe, float]:
    """Prouve les quatre traversées d'un carry avant toute conclusion économique."""
    preuve["side_lock"] = (
        "NON_APPLICABLE_CARRY_DELTA_NEUTRE : short perp + long spot = exposition nette ZERO. "
        "La jambe perp n'est pas un pari directionnel."
    )
    j, _sens = _jambe_principale(ctx)
    preuve["jambe"] = j.as_dict()
    if not j.executable:
        return (
            _refus(
                REFUS_PRIX_NON_EXECUTABLE,
                famille=CARRY_STRUCTUREL,
                jambe=j,
                signalements=tuple(signalements),
                preuve=preuve,
            ),
            j,
            0.0,
        )

    a_spot = ctx.niveaux_spot_achat
    v_spot = ctx.niveaux_spot_vente
    if not a_spot or not v_spot:
        preuve["spot"] = (
            "CARNET_SPOT_NON_FOURNI : un carry a deux jambes ; une jambe non verifiee n'est pas sure."
        )
        return (
            _refus(
                REFUS_JAMBE_SPOT_IMPOSSIBLE,
                famille=CARRY_STRUCTUREL,
                jambe=j,
                slippage_bps=float(j.slippage_bps or 0.0),
                signalements=tuple(signalements),
                preuve=preuve,
            ),
            j,
            0.0,
        )

    achat = marcher_dans_le_carnet(list(a_spot), float(ctx.notional_usd))
    vente = marcher_dans_le_carnet(list(v_spot), float(ctx.notional_usd))
    spot: dict = {"achat": achat.as_dict(), "vente": vente.as_dict()}
    preuve["spot"] = spot
    if not achat.rempli or not vente.rempli:
        spot["motif"] = "CARNET_SPOT_TROP_MINCE : la couverture spot ne se remplit pas."
        return (
            _refus(
                REFUS_JAMBE_SPOT_IMPOSSIBLE,
                famille=CARRY_STRUCTUREL,
                jambe=j,
                slippage_bps=float(j.slippage_bps or 0.0),
                signalements=tuple(signalements),
                preuve=preuve,
            ),
            j,
            0.0,
        )

    # Pour fermer un carry SHORT perp, il faut pouvoir racheter dans les asks.
    sortie_perp = marcher_dans_le_carnet(list(ctx.niveaux_achat or []), float(ctx.notional_usd))
    spot["sortie_perp"] = sortie_perp.as_dict()
    if not sortie_perp.rempli:
        spot["motif"] = "CARNET_PERP_TROP_MINCE_POUR_SORTIR"
        return (
            _refus(
                REFUS_JAMBE_SPOT_IMPOSSIBLE,
                famille=CARRY_STRUCTUREL,
                jambe=j,
                slippage_bps=float(j.slippage_bps or 0.0),
                signalements=tuple(signalements),
                preuve=preuve,
            ),
            j,
            0.0,
        )

    extra = float(achat.slippage_bps or 0.0) + float(vente.slippage_bps or 0.0) + float(sortie_perp.slippage_bps or 0.0)
    spot["slippage_total_bps"] = round(extra, 6)
    return None, j, extra


def decider(ctx: Contexte, *, table=None, racine=None) -> Decision:
    signalements: list[str] = []
    preuve: dict = {
        "strategie": ctx.strategie,
        "coin": ctx.coin,
        "direction": ctx.direction,
        "notional_usd": ctx.notional_usd,
    }

    if not (float(ctx.notional_usd) > 0.0):
        return _refus(REFUS_NOTIONAL_INVALIDE, preuve=preuve)

    preuve["feed_quality"] = {
        "ready": ctx.feed_quality_ready,
        "score": ctx.feed_quality_score,
        "minimum": float(ctx.min_feed_quality_score),
        "reasons": list(ctx.feed_quality_reasons),
    }
    if ctx.feed_quality_ready is None:
        signalements.append(QUALITE_FLUX_NON_FOURNIE)
    if ctx.feed_quality_ready is False:
        return _refus(REFUS_QUALITE_FLUX, signalements=tuple(signalements), preuve=preuve)
    if ctx.feed_quality_score is not None and float(ctx.feed_quality_score) < float(ctx.min_feed_quality_score):
        return _refus(REFUS_QUALITE_FLUX, signalements=tuple(signalements), preuve=preuve)
    if ctx.feed_quality_ready is True and ctx.feed_quality_score is None:
        return _refus(REFUS_QUALITE_FLUX, signalements=tuple(signalements), preuve=preuve)

    session = evaluer_session(ctx.etat_session)
    preuve["session"] = session.as_dict()
    if session.motif == ETAT_SESSION_NON_FOURNI:
        signalements.append(ETAT_SESSION_NON_FOURNI)
    if session.bloque:
        return _refus(REFUS_SESSION_EN_HALTE, signalements=tuple(signalements), preuve=preuve)

    fam = famille_de_la_strategie(ctx.strategie)
    preuve["famille"] = fam or "INCONNUE"
    if not fam:
        return _refus(REFUS_FAMILLE_INCONNUE, signalements=tuple(signalements), preuve=preuve)
    autorise_famille, verdict_famille = verdict_du_signal(fam)
    preuve["verdict_famille"] = verdict_famille
    if not autorise_famille:
        return _refus(REFUS_ZONE_MORTE, famille=fam, signalements=tuple(signalements), preuve=preuve)

    # Une formule de secours ne franchit jamais la porte, même si les carnets sont beaux.
    if source_configuree() == SOURCE_FORMULE:
        return _refus(REFUS_EDGE_FABRIQUE, famille=fam, edge_fabrique=True,
                      signalements=tuple(signalements), preuve=preuve)

    carry_extra_slip = 0.0
    if fam == CARRY_STRUCTUREL:
        refus_carry, j, carry_extra_slip = _verifier_carry_executable(ctx, preuve, signalements)
        if refus_carry is not None:
            return refus_carry
        e, edge_preuve = _edge_mesure(ctx, fam, table=table, racine=racine)
    else:
        e, edge_preuve = _edge_mesure(ctx, fam, table=table, racine=racine)
        j = None
    preuve["edge_source"] = edge_preuve

    if ctx.edge_fourni_bps is not None:
        signalements.append(EDGE_FOURNI_IGNORE)
        preuve["edge_fourni_bps"] = float(ctx.edge_fourni_bps)
        if e is not None and e.valeur_bps is not None and abs(float(ctx.edge_fourni_bps) - float(e.valeur_bps)) > 1.0:
            signalements.append(EDGE_FOURNI_CONTREDIT_LA_MESURE)

    if e is None:
        return _refus(REFUS_EDGE_NON_MESURE, famille=fam, jambe=j,
                      signalements=tuple(signalements), preuve=preuve)
    if e.fabrique:
        return _refus(REFUS_EDGE_FABRIQUE, famille=fam, edge_fabrique=True,
                      edge_brut_bps=e.valeur_bps, jambe=j,
                      signalements=tuple(signalements), preuve=preuve)
    if not e.utilisable:
        return _refus(REFUS_EDGE_NON_MESURE, famille=fam, jambe=j,
                      signalements=tuple(signalements), preuve=preuve)
    edge_b = float(e.valeur_bps or 0.0)

    if fam != CARRY_STRUCTUREL:
        j, _sens = _jambe_principale(ctx)
        preuve["jambe"] = j.as_dict()
        if not j.executable:
            return _refus(REFUS_PRIX_NON_EXECUTABLE, famille=fam, edge_brut_bps=edge_b, jambe=j,
                          signalements=tuple(signalements), preuve=preuve)

    assert j is not None
    slip = float(j.slippage_bps or 0.0) + carry_extra_slip
    couts = max(0.0, float(ctx.frais_bps)) + slip + max(0.0, float(ctx.degradation_copie_bps))
    edge_n = edge_b - couts
    preuve["couts_bps"] = couts
    preuve["edge_net_bps"] = edge_n
    if fam == CARRY_STRUCTUREL and isinstance(preuve.get("spot"), dict):
        preuve["spot"]["edge_net_apres_slippage_spot_bps"] = round(edge_n, 6)

    if edge_n < float(ctx.plancher_edge_net_bps):
        return _refus(REFUS_EDGE_NET_INSUFFISANT, famille=fam, edge_brut_bps=edge_b,
                      edge_net_bps=edge_n, couts_bps=couts, slippage_bps=slip, jambe=j,
                      signalements=tuple(signalements), preuve=preuve)

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

    if ctx.exiger_vpin or ctx.vpin is not None:
        abstention, motif_vpin = faut_il_s_abstenir(ctx.vpin)
        preuve["vpin"] = motif_vpin
        if abstention:
            return _refus(REFUS_FLUX_TOXIQUE, famille=fam, edge_brut_bps=edge_b,
                          edge_net_bps=edge_n, couts_bps=couts, slippage_bps=slip, jambe=j,
                          signalements=tuple(signalements), preuve=preuve)

    if ctx.sz_decimals is not None and j.prix and j.prix > 0:
        ordre = valider_ordre(
            prix=float(j.prix),
            taille=float(ctx.notional_usd) / float(j.prix),
            sz_decimals=int(ctx.sz_decimals),
            post_only=False,
        )
        preuve["exchange"] = ordre.as_dict()
        if not ordre.valide:
            return _refus(REFUS_ORDRE_IMPOSSIBLE, famille=fam, edge_brut_bps=edge_b,
                          edge_net_bps=edge_n, couts_bps=couts, slippage_bps=slip, jambe=j,
                          signalements=tuple(signalements), preuve=preuve)
    elif float(ctx.notional_usd) < NOTIONNEL_MIN_USD:
        preuve["exchange"] = {"motif": "MinTradeNtl", "notionnel": float(ctx.notional_usd)}
        return _refus(REFUS_ORDRE_IMPOSSIBLE, famille=fam, edge_brut_bps=edge_b,
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
    "REFUS_NOTIONAL_INVALIDE", "REFUS_QUALITE_FLUX",
    "REFUS_ORDRE_IMPOSSIBLE", "REFUS_FLUX_TOXIQUE", "REFUS_COTE_VERROUILLEE",
    "REFUS_SESSION_EN_HALTE", "REFUS_JAMBE_SPOT_IMPOSSIBLE",
    "ETAT_SESSION_NON_FOURNI", "QUALITE_FLUX_NON_FOURNIE",
    "EDGE_FOURNI_CONTREDIT_LA_MESURE", "EDGE_FOURNI_IGNORE",
    "FAMILLE_PAR_STRATEGIE", "FRAIS_ALLER_RETOUR_TAKER_BPS", "PLANCHER_NET_BPS",
    "Contexte", "Decision", "decider", "famille_de_la_strategie",
]
