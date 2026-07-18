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

from hl_observer.funding.delta_neutral_carry import evaluer_carry_neutre
from hl_observer.paper_trading.delta_neutral_position import build_delta_neutral_position
from hl_observer.paper_trading.funding_payment_tracker import compute_funding_payment
from hl_observer.paper_trading.journal import PaperTradeJournal

MARGE_USD = 50.0                       # notre marge fixe par position (perp). notional = marge × levier.
COUT_SORTIE_2_JAMBES_BPS = 11.0        # sortie maker 2 jambes (miroir exact de l'entrée maker)
AGE_MAX_H_DEFAUT = 24.0 * 14.0         # 14 j : au-delà on ferme pour revalider (pas de zombie)

MODE_LIVE = "LIVE"
MODES_VALIDES = {"LIVE", "BACKTEST", "REPLAY", "TEST_FIXTURE"}

SORTIE_FUNDING = "FUNDING_NON_RENTABLE"
SORTIE_LIQUIDATION = "LA_JAMBE_PERP_AURAIT_ETE_LIQUIDEE"
SORTIE_AGE = "AGE_MAX_ATTEINT_REVALIDATION"


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
        "cout_entree_bps": _f(decision, "cout_entree_bps"),
        "base_bps_entree": _f(decision, "base_bps"),
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
                     hausse_depuis_entree: float = 0.0, age_max_h: float = AGE_MAX_H_DEFAUT) -> str | None:
    """None = on garde. Sinon le motif de fermeture. La liquidation ré-utilise le MÊME modèle de
    risque (`evaluer_carry_neutre`) avec la hausse RÉELLE observée -> aucune constante re-dérivée."""
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
    if (int(now_ms) - int(position["entry_ts_ms"])) / 3.6e6 >= float(age_max_h):
        return SORTIE_AGE
    return None


def pnl_realise(position: dict[str, Any]) -> float:
    """PnL réalisé à la fermeture = funding accru − coût d'entrée − coût de sortie. Frais NON doublés."""
    notional = float(position["notional_usdt"])
    cout_entree = notional * float(position["cout_entree_bps"]) / 1e4
    cout_sortie = notional * COUT_SORTIE_2_JAMBES_BPS / 1e4
    return round(float(position["funding_accrued_usdt"]) - cout_entree - cout_sortie, 6)


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
             age_max_h: float = AGE_MAX_H_DEFAUT) -> dict[str, Any]:
        """Une passe : accrue+sort les positions ouvertes, puis ouvre si viable et coin libre.
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
            motif = raison_de_sortie(pos, now_ms=now_ms, funding_bps_h_courant=fnow,
                                     hausse_depuis_entree=hausse_depuis_entree, age_max_h=age_max_h)
            if motif is not None:
                realized = pnl_realise(pos)
                self.journal.record(kind="CLOSE", coin=coin, side="CARRY",
                                    notional_usdt=pos["notional_usdt"], realized_net_pnl_usdc=realized,
                                    reason=motif, now_ms=int(now_ms))
                self.ouvertes.pop(coin, None)
                evt["ferme"] = motif
                evt["pnl_realise_usdt"] = realized
                return evt
            self.ouvertes[coin] = pos
            return evt

        # 2) pas de position ouverte pour ce coin -> ouvrir si viable
        pos = ouvrir_position(decision, inputs, now_ms=now_ms, mode=self.mode)
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
