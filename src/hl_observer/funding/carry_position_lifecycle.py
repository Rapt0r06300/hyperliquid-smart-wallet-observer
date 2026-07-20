"""ÉTAPE 2 du carry : OUVRIR / TENIR / FERMER une position PAPER delta-neutre + PnL RÉALISÉ au ledger.

`carry_paper_runtime` (étape 1) DÉCIDE et journalise, mais n'ouvre RIEN -> 8 coins viables = 0 PnL.
Ce module est le chaînon manquant : quand la décision est viable, il OUVRE la position paper,
ACCRUE le funding MESURÉ chaque heure (le SHORT perp encaisse quand funding>0), SORT (funding non
rentable / la jambe perp aurait été liquidée / âge max), et écrit le PnL RÉALISÉ dans le ledger.

Vérités respectées (CLAUDE.md) :
  * réutilise `evaluer_carry_neutre` (décision + verrou liquidation), `compute_funding_payment`
    (signe short/long), `PaperTradeJournal` (le ledger OPEN/CLOSE) — AUCUNE duplication ;
  * le funding accru vient du funding MESURÉ passé à chaque tick — on ne l'invente pas ;
  * frais NON doublés : entrée = `cout_entree_bps` (déjà 2 jambes maker + base subie),
    sortie = 11 bps (2 jambes maker, miroir de l'entrée) ;
  * la sortie liquidation ré-utilise `evaluer_carry_neutre` avec la hausse RÉELLE observée
    depuis l'entrée (même modèle de risque -> aucun double standard, aucune constante re-dérivée) ;
  * LIVE / BACKTEST / REPLAY / TEST_FIXTURE ne se mélangent JAMAIS (tag `mode`) ;
  * PAPER only : aucun ordre réel, aucune clé, aucune signature. Un paper trade n'est pas un ordre.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hl_observer.funding.base_convergence import base_convergee, correction_sortie_bps
from hl_observer.funding.carry_anti_churn import filtrer_sortie, heures_pour_amortir
from hl_observer.funding.carry_ouverture_gates import porte_risque_ouverture
from hl_observer.funding.delta_neutral_carry import evaluer_carry_neutre
from hl_observer.paper_trading.delta_neutral_position import build_delta_neutral_position
from hl_observer.paper_trading.funding_payment_tracker import compute_funding_payment
from hl_observer.paper_trading.journal import PaperTradeJournal

def _nombre_ou_none(d: dict[str, Any] | None, cle: str) -> float | None:
    """Un nombre exploitable dans `d[cle]`, sinon None. `None` = ABSENT -> le garde s'abstient
    (il ne refuse pas). Un garde nourri de `None` ne protège de rien : il rassure."""
    v = (d or {}).get(cle)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return None if f != f else f


MARGE_USD = 50.0                       # notre marge fixe par position (perp). notional = marge × levier.
COUT_SORTIE_2_JAMBES_BPS = 11.0        # sortie maker 2 jambes (miroir exact de l'entrée maker)
AGE_MAX_H_DEFAUT = 24.0 * 14.0         # 14 j : au-delà on ferme pour revalider (pas de zombie)

MODE_LIVE = "LIVE"
MODES_VALIDES = {"LIVE", "BACKTEST", "REPLAY", "TEST_FIXTURE"}

SORTIE_FUNDING = "FUNDING_NON_RENTABLE"
SORTIE_LIQUIDATION = "LA_JAMBE_PERP_AURAIT_ETE_LIQUIDEE"
SORTIE_AGE = "AGE_MAX_ATTEINT_REVALIDATION"
SORTIE_BASE_CONVERGEE = "BASE_CONVERGEE_PREMIUM_CAPTURE"   # A5 : le 2e PnL est capture, on verrouille


def _f(d: dict, k: str, defaut: float = 0.0) -> float:
    v = d.get(k)
    return float(v) if isinstance(v, (int, float)) else defaut


def ouvrir_position(decision: dict[str, Any], inputs: dict[str, Any], *,
                    now_ms: int, mode: str = MODE_LIVE, marge_usd: float = MARGE_USD) -> dict[str, Any] | None:
    """Matérialise une position paper delta-neutre À PARTIR d'une décision viable. None sinon.
    notional = marge × levier (notre sizing). Long spot = short perp (le prix s'annule)."""
    if mode not in MODES_VALIDES:
        raise ValueError("mode inconnu: %r (attendu %s)" % (mode, sorted(MODES_VALIDES)))
    if not decision.get("viable"):
        return None
    levier = _f(inputs, "levier_utilise") or _f(inputs, "levier_max")
    marge_ratio = _f(inputs, "marge_ratio")
    if levier <= 0 and marge_ratio > 0:
        levier = 1.0 / marge_ratio
    if levier <= 0:
        return None
    # Y4/Y15/Y16 — SIZING INTELLIGENT : la marge est scalée par le facteur de taille (z-score de
    # funding / Kelly / vol-target), borné [0.25, 2.0]. Absent -> 1.0 (rétro-compatible). On grossit
    # les carrys à funding fort/sûr, on réduit les incertains. Aucune amplification fabriquée.
    facteur = _f(inputs, "facteur_taille")
    facteur = 1.0 if facteur <= 0 else max(0.25, min(2.0, float(facteur)))
    marge_usd = float(marge_usd) * facteur
    notional = round(float(marge_usd) * levier, 6)
    dn = build_delta_neutral_position(coin=str(decision.get("coin") or ""),
                                      long_notional_usdt=notional, short_notional_usdt=notional)
    if not dn.balanced or notional <= 0:
        return None
    return {
        "coin": str(decision.get("coin") or "").upper(),
        "mode": mode,
        "notional_usdt": notional,
        "marge_usdt": round(float(marge_usd), 6),
        "levier": round(levier, 6),
        "marge_ratio": marge_ratio or round(1.0 / levier, 6),
        "levier_max": _f(inputs, "levier_max"),
        "entry_ts_ms": int(now_ms),
        "last_accrual_ts_ms": int(now_ms),
        "funding_bps_h_entree": _f(decision, "funding_bps_h"),
        "gain_net_24h_bps": _f(decision, "gain_net_24h_bps"),   # A7 : pour la rotation vers le meilleur net
        "cout_entree_bps": _f(decision, "cout_entree_bps"),
        "base_bps_entree": _f(decision, "base_bps"),
        "entry_perp_px": _f(inputs, "perp_px"),          # prix perp a l'entree -> hausse live = (cours-entree)/entree
        "liquidite_spot_usd": _f(decision, "liquidite_spot_usd") or _f(inputs, "liquidite_spot_usd"),
        "pire_hausse_entree": _f(inputs, "pire_hausse_observee"),
        "funding_accrued_usdt": 0.0,
        "real_execution": False,
        "not_an_order": True,
        "simulation_only": True,
    }


def accruer(position: dict[str, Any], *, now_ms: int, funding_bps_h_courant: float) -> tuple[dict[str, Any], float]:
    """Accrue le funding MESURÉ depuis le dernier tick. Le SHORT perp encaisse quand funding>0."""
    dt_h = max(0.0, (int(now_ms) - int(position["last_accrual_ts_ms"])) / 3.6e6)
    if dt_h <= 0.0:
        return position, 0.0
    fp = compute_funding_payment(coin=position["coin"], side="SHORT",
                                 notional_usdt=float(position["notional_usdt"]),
                                 funding_rate=float(funding_bps_h_courant) / 1e4, intervals=dt_h)
    p = dict(position)
    p["last_accrual_ts_ms"] = int(now_ms)
    p["funding_accrued_usdt"] = round(float(position["funding_accrued_usdt"]) + fp.pnl_usdt, 6)
    return p, fp.pnl_usdt


def raison_de_sortie(position: dict[str, Any], *, now_ms: int, funding_bps_h_courant: float,
                     hausse_depuis_entree: float = 0.0, base_bps_courant: float | None = None,
                     age_max_h: float = AGE_MAX_H_DEFAUT) -> str | None:
    """None = on garde. Sinon le motif de fermeture. La liquidation ré-utilise le MÊME modèle de
    risque (`evaluer_carry_neutre`) avec la hausse RÉELLE observée -> aucune constante re-dérivée.
    A5 : si la base d'entree etait un premium et qu'il a converge, on verrouille (SORTIE_BASE_CONVERGEE)."""
    if float(funding_bps_h_courant) <= 0.0:
        return SORTIE_FUNDING
    hausse = max(float(position.get("pire_hausse_entree") or 0.0), float(hausse_depuis_entree or 0.0))
    v = evaluer_carry_neutre(
        coin=position["coin"], funding_bps_h=float(funding_bps_h_courant),
        base_bps=float(position["base_bps_entree"]),
        liquidite_spot_usd=float(position["liquidite_spot_usd"]),
        maker=True, levier_max=float(position["levier_max"]) or None,
        marge_ratio=float(position["marge_ratio"]), pire_hausse_observee=hausse)
    if not v.viable and "LIQUID" in (v.motif or "").upper():
        return SORTIE_LIQUIDATION
    if base_bps_courant is not None and base_convergee(
            float(position.get("base_bps_entree") or 0.0), float(base_bps_courant)):
        # 🔴 A5 x A4 (nuit du 19-20/07) : la base avait converge mais la fermeture etait PERDANTE
        # (-0,08 $ puis -0,07 $ realises, motif 'CAPTURE' !) parce qu'on 'verrouillait' un gain
        # plus petit que les frais de sortie -- puis on ROUVRAIT une minute apres. Une capture
        # qui ne paie pas sa propre sortie est un churn deguise sous un joli nom. A4 existait
        # (`sortir doit rapporter`) mais n'etait pas consulte ICI : mention != porte, encore.
        # Desormais on ne verrouille que si le PnL REALISE serait > 0 ; sinon on GARDE (le
        # funding continue de courir, la base peut re-diverger, et une vraie urgence a ses
        # propres sorties : liquidation, hemorragie de funding, age).
        if pnl_realise(position, base_bps_courant=float(base_bps_courant)) > 0.0:
            return SORTIE_BASE_CONVERGEE                   # A5 : 2e PnL capture -> on verrouille
    if (int(now_ms) - int(position["entry_ts_ms"])) / 3.6e6 >= float(age_max_h):
        return SORTIE_AGE
    return None


def pnl_realise(position: dict[str, Any], *, base_bps_courant: float = 0.0) -> float:
    """PnL réalisé = funding accru − coût d'entrée − coût de sortie + correction de base (A5).
    Le modèle crédite toute la base à l'entrée ; on RETIRE la base résiduelle non capturée
    (`base_bps_courant`) -> net base = vrai P&L de convergence. Frais NON doublés."""
    notional = float(position["notional_usdt"])
    cout_entree = notional * float(position["cout_entree_bps"]) / 1e4
    cout_sortie = notional * COUT_SORTIE_2_JAMBES_BPS / 1e4
    correction_base = correction_sortie_bps(base_bps_courant) * notional / 1e4   # A5
    return round(float(position["funding_accrued_usdt"]) - cout_entree - cout_sortie
                 + correction_base, 6)


@dataclass(slots=True)
class GestionnaireCarry:
    """Tient les positions carry OUVERTES et écrit OPEN/CLOSE dans un ledger. Un coin = une position.
    Toutes les positions d'un gestionnaire partagent le même `mode` (jamais de mélange LIVE/TEST)."""
    mode: str = MODE_LIVE
    journal: PaperTradeJournal = field(default_factory=PaperTradeJournal)
    ouvertes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in MODES_VALIDES:
            raise ValueError("mode inconnu: %r" % (self.mode,))

    def tick(self, decision: dict[str, Any], inputs: dict[str, Any], *, now_ms: int,
             funding_bps_h_courant: float | None = None, hausse_depuis_entree: float = 0.0,
             prix_courant: float | None = None, base_bps_courant: float | None = None,
             age_max_h: float = AGE_MAX_H_DEFAUT,
             risque_contexte: dict[str, Any] | None = None,
             marge_usd: float = MARGE_USD) -> dict[str, Any]:
        """Une passe : accrue+sort les positions ouvertes, puis ouvre si viable et coin libre.
        `prix_courant` (perp) permet la sortie liquidation TEMPS REEL : hausse = (cours-entree)/entree.
        Retourne un petit résumé de ce qui s'est passé (pour le journal d'exécution)."""
        coin = str(decision.get("coin") or "").upper()
        fnow = float(funding_bps_h_courant if funding_bps_h_courant is not None
                     else _f(decision, "funding_bps_h"))
        evt: dict[str, Any] = {"coin": coin, "mode": self.mode, "ouvert": False,
                               "ferme": None, "pnl_realise_usdt": None, "funding_add_usdt": 0.0}

        # 1) gérer la position déjà ouverte pour ce coin (accruer puis, si besoin, fermer)
        pos = self.ouvertes.get(coin)
        if pos is not None:
            pos, add = accruer(pos, now_ms=now_ms, funding_bps_h_courant=fnow)
            evt["funding_add_usdt"] = round(add, 6)
            # hausse REELLE depuis l'entree (prix live) -> attrape un pic avant funding<=0/age
            hausse = float(hausse_depuis_entree or 0.0)
            entree = float(pos.get("entry_perp_px") or 0.0)
            if prix_courant and entree > 0:
                hausse = max(hausse, (float(prix_courant) - entree) / entree)
            motif = raison_de_sortie(pos, now_ms=now_ms, funding_bps_h_courant=fnow,
                                     hausse_depuis_entree=hausse, base_bps_courant=base_bps_courant,
                                     age_max_h=age_max_h)
            # A3/A4 — AMORTIR AVANT DE SORTIR. Fermer coûte ~11 bps ; à 0,125 bps/h de funding,
            # une sortie prématurée acte la perte de l'entrée pour rien. `filtrer_sortie` annule
            # donc les sorties non urgentes tant que l'entrée n'est pas amortie — MAIS laisse
            # TOUJOURS passer un DANGER (liquidation) et un funding devenu nul. Le capital
            # d'abord, l'économie de frais ensuite.
            motif_brut = motif
            motif = filtrer_sortie(motif, pos, now_ms=now_ms, funding_bps_h=fnow)
            if motif is None and motif_brut is not None:
                evt["sortie_differee"] = {
                    "motif_brut": motif_brut,
                    "heures_pour_amortir": round(heures_pour_amortir(
                        cout_entree_bps=float(pos.get("cout_entree_bps") or 0.0),
                        funding_bps_h=fnow), 1),
                    "age_h": round((int(now_ms) - int(pos["entry_ts_ms"])) / 3.6e6, 2)}
            if motif is not None:
                base_sortie = (base_bps_courant if base_bps_courant is not None
                               else float(pos.get("base_bps_entree") or 0.0))   # inconnu -> conservateur
                realized = pnl_realise(pos, base_bps_courant=base_sortie)
                self.journal.record(kind="CLOSE", coin=coin, side="CARRY",
                                    notional_usdt=pos["notional_usdt"], realized_net_pnl_usdc=realized,
                                    reason=motif, now_ms=int(now_ms))
                self.ouvertes.pop(coin, None)
                evt["ferme"] = motif
                evt["pnl_realise_usdt"] = realized
                return evt
            self.ouvertes[coin] = pos
            return evt

        # 2) pas de position ouverte pour ce coin -> PORTE DE RISQUE, puis ouvrir si viable.
        #    Les gardes de `risk/` étaient en LIMBE (testés, appelés par personne) parce que je
        #    les avais posés sur `v12_decision_pipeline`, que l'audit de câblage a mesuré MORT.
        #    Ils sont ici, sur le seul chemin qui ouvre vraiment une position. Une entrée absente
        #    fait ABSTENIR le garde concerné (jamais refuser) : un garde affamé ne protège de rien.
        porte = porte_risque_ouverture(
            marge_demandee_usd=marge_usd,
            marge_utilisee_usd=sum(float(p.get("marge_usdt") or MARGE_USD)
                                   for p in self.ouvertes.values()),
            capital_usd=_nombre_ou_none(risque_contexte, "capital_usd"),
            distance_tampon_frac=_nombre_ou_none(risque_contexte, "distance_tampon_frac"),
            funding_paye_cumule_bps=_nombre_ou_none(risque_contexte, "funding_paye_cumule_bps"),
            budget_funding_bps=_nombre_ou_none(risque_contexte, "budget_funding_bps"),
            marks_multi_sources=(risque_contexte or {}).get("marks_multi_sources"),
            pnls_realises_recents=(risque_contexte or {}).get("pnls_realises_recents"),
            drawdown_frac=_nombre_ou_none(risque_contexte, "drawdown_frac"),
            levier_demande=_f(decision, "levier") or _nombre_ou_none(inputs, "levier_max"),
            regime=(risque_contexte or {}).get("regime"),
            edge_attendu=_nombre_ou_none(risque_contexte, "edge_attendu"),
            variance_attendue=_nombre_ou_none(risque_contexte, "variance_attendue"))
        evt["porte_risque"] = {"autorise": porte["autorise"], "motif": porte["motif"],
                               "facteur_taille": porte["facteur_taille"], "gardes": porte["gardes"]}
        if not porte["autorise"]:
            evt["refus_risque"] = porte["motif"]
            return evt

        pos = ouvrir_position(decision, inputs, now_ms=now_ms, mode=self.mode, marge_usd=marge_usd)
        if pos is not None:
            self.ouvertes[coin] = pos
            self.journal.record(kind="OPEN", coin=coin, side="CARRY",
                                notional_usdt=pos["notional_usdt"], reason="CARRY_NEUTRE_OUVERTURE",
                                now_ms=int(now_ms))
            evt["ouvert"] = True
        return evt

    def resume(self) -> dict[str, Any]:
        s = self.journal.summary()
        s["positions_ouvertes"] = len(self.ouvertes)
        s["funding_accru_ouvert_usdt"] = round(
            sum(float(p["funding_accrued_usdt"]) for p in self.ouvertes.values()), 6)
        s["mode"] = self.mode
        return s


__all__ = [
    "MARGE_USD", "COUT_SORTIE_2_JAMBES_BPS", "AGE_MAX_H_DEFAUT",
    "MODE_LIVE", "MODES_VALIDES", "SORTIE_FUNDING", "SORTIE_LIQUIDATION", "SORTIE_AGE",
    "ouvrir_position", "accruer", "raison_de_sortie", "pnl_realise", "GestionnaireCarry",
]
