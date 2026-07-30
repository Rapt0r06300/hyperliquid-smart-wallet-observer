"""P2.1 — porte ÉCONOMIQUE de promotion du scoreboard, deny-by-default : un scoreboard qui ne ment pas.

Le verdict `assembler_ligne` (net/OOS/forward/N) est un PRÉ-filtre trop permissif si capacité, fill ou
latence restent inconnus. Ce module est la porte ÉCONOMIQUE finale : `PROMOTE` seulement si **toutes**
les portes §4.1 sont mesurées ET franchies (ledger TRUSTED, net/OOS/forward > 0, N indépendant,
plusieurs jours/régimes/coins, concentration sous plafond, borne de confiance basse > 0, placebo battu,
DSR acceptable, PBO robuste, fees+spread+slippage+latence mesurés, fill ratio mesuré, capacité mesurée).
Un négatif décisif ⇒ `KILL` ; une seule donnée manquante ⇒ `MORE_DATA`. Aucun `PROMOTE` optimiste.

Elle **complète** (ne duplique pas) la porte de DÉPLOIEMENT `backtesting.promotion_gate.decision_promotion`
(paper → testnet, jamais mainnet) : `promotion_finale` n'accorde une promotion réelle que si les DEUX
disent oui. Ce module ne recalcule aucune statistique — il consomme les verdicts (PBO/robustesse,
placebo, DSR, concentration…) déjà produits. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "hypersmart.scoreboard_promotion.v1"

PROMOTE = "PROMOTE"
KILL = "KILL"
MORE_DATA = "MORE_DATA"

# Statuts de porte.
PASS = "PASS"
FAIL = "FAIL"        # négatif prouvé → tire vers KILL
MISSING = "MISSING"  # non mesuré / insuffisant → tire vers MORE_DATA

# Seuils (deny-by-default : conservateurs).
N_INDEP_MIN = 20
MIN_JOURS = 5
MIN_REGIMES = 2
MIN_COINS_DEFAUT = 1
CONCENTRATION_MAX = 0.35


def _fini(x: object) -> float | None:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _gate_gt0(value: object) -> str:
    v = _fini(value)
    if v is None:
        return MISSING
    return FAIL if v <= 0 else PASS


def _gate_bool(value: object) -> str:
    if value is None:
        return MISSING
    return PASS if bool(value) else FAIL


def _gate_min(value: object, mini: float) -> str:
    v = _fini(value)
    if v is None:
        return MISSING
    return PASS if v >= mini else MISSING   # insuffisant = pas encore assez de données


def _gate_max(value: object, maxi: float) -> str:
    v = _fini(value)
    if v is None:
        return MISSING
    return PASS if v <= maxi else FAIL      # au-dessus du plafond = négatif décisif


def _gate_present(value: object) -> str:
    return PASS if _fini(value) is not None else MISSING


def _gate_true_ou_missing(value: object) -> str:
    """PASS si vrai, sinon MISSING : un prérequis d'intégrité (ledger TRUSTED) bloque sans TUER l'hypothèse."""
    return PASS if value is True else MISSING


@dataclass(frozen=True, slots=True)
class ScoreboardPromotionEvidence:
    ledger_trusted: bool | None = None
    placebo_beaten: bool | None = None
    pbo_robuste: bool | None = None          # backtesting.robustesse_selection: verdict == ROBUSTE
    dsr_ok: bool | None = None
    lower_confidence_bound_bps: float | None = None
    concentration: float | None = None       # part du plus gros contributeur (0..1)
    n_days: int | None = None
    n_regimes: int | None = None
    n_coins: int | None = None
    min_coins: int = MIN_COINS_DEFAUT


@dataclass(frozen=True, slots=True)
class ScoreboardPromotionVerdict:
    verdict: str
    gates: tuple[dict[str, Any], ...]
    echecs: tuple[str, ...]      # portes FAIL (négatif décisif)
    manquants: tuple[str, ...]   # portes MISSING (non mesuré / insuffisant)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION, "verdict": self.verdict,
            "gates": list(self.gates), "echecs": list(self.echecs),
            "manquants": list(self.manquants), "paper_only": True, "real_execution": False,
        }


def _row_attr(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def evaluer_promotion_scoreboard(
    row: Any, evidence: ScoreboardPromotionEvidence | None = None
) -> ScoreboardPromotionVerdict:
    """Verdict ÉCONOMIQUE final deny-by-default. `row` = ScoreboardRow (ou dict) ; `evidence` = le reste."""
    ev = evidence or ScoreboardPromotionEvidence()
    unmeasured = tuple(_row_attr(row, "unmeasured") or ())

    def cout_mesure() -> str:
        cts = _row_attr(row, "costs_bps")
        if cts is None or "costs_bps" in unmeasured or "net_bps" in unmeasured:
            return MISSING
        return PASS

    gates: list[tuple[str, str, str]] = [
        ("ledger_trusted", _gate_true_ou_missing(ev.ledger_trusted), "le ledger doit être TRUSTED"),
        ("net_bps>0", _gate_gt0(_row_attr(row, "net_bps")), "edge net après coûts strictement positif"),
        ("oos_net_bps>0", _gate_gt0(_row_attr(row, "oos_net_bps")), "OOS net positif (hors échantillon)"),
        ("forward_net_bps>0", _gate_gt0(_row_attr(row, "forward_net_bps")), "forward post-freeze net positif"),
        ("n_independent>=min", _gate_min(_row_attr(row, "n_independent"), N_INDEP_MIN), f">= {N_INDEP_MIN} obs indépendantes"),
        ("n_days>=min", _gate_min(ev.n_days, MIN_JOURS), f">= {MIN_JOURS} jours"),
        ("n_regimes>=min", _gate_min(ev.n_regimes, MIN_REGIMES), f">= {MIN_REGIMES} régimes"),
        ("n_coins>=min", _gate_min(ev.n_coins, ev.min_coins), f">= {ev.min_coins} coin(s)"),
        ("concentration<=cap", _gate_max(ev.concentration, CONCENTRATION_MAX), f"concentration <= {CONCENTRATION_MAX}"),
        ("lower_confidence_bound>0", _gate_gt0(ev.lower_confidence_bound_bps), "borne de confiance basse positive"),
        ("placebo_beaten", _gate_bool(ev.placebo_beaten), "le placebo doit être battu"),
        ("dsr_ok", _gate_bool(ev.dsr_ok), "Deflated Sharpe acceptable"),
        ("pbo_robuste", _gate_bool(ev.pbo_robuste), "PBO acceptable (procédure ROBUSTE)"),
        ("costs_measured", cout_mesure(), "fees+spread+slippage+latence tous mesurés"),
        ("fill_ratio_measured", _gate_present(_row_attr(row, "fill_ratio")), "fill ratio mesuré"),
        ("capacity_measured", _gate_present(_row_attr(row, "capacity_usd")), "capacité mesurée"),
        ("latency_measured", _gate_present(_row_attr(row, "latency_p95_ms")), "latence p95 mesurée"),
    ]

    detail = tuple({"gate": n, "statut": s, "exigence": d} for n, s, d in gates)
    echecs = tuple(n for n, s, _ in gates if s == FAIL)
    manquants = tuple(n for n, s, _ in gates if s == MISSING)

    if echecs:
        verdict = KILL
    elif manquants:
        verdict = MORE_DATA
    else:
        verdict = PROMOTE
    return ScoreboardPromotionVerdict(verdict=verdict, gates=detail, echecs=echecs, manquants=manquants)


def promotion_finale(
    row: Any,
    evidence: ScoreboardPromotionEvidence | None = None,
    *,
    deployment_decision: str | None = None,
) -> dict[str, Any]:
    """Promotion RÉELLE = porte économique **ET** porte de déploiement (paper→testnet).

    `deployment_decision` = sortie de `backtesting.promotion_gate.decision_promotion` (`PROMOUVOIR_TESTNET`
    ou `RESTE_PAPER`). Deny-by-default : sans elle, ou si elle n'est pas `PROMOUVOIR_TESTNET`, pas de
    promotion réelle, même si l'économie est `PROMOTE`. Jamais mainnet."""
    from hl_observer.backtesting.promotion_gate import PROMOUVOIR_TESTNET

    eco = evaluer_promotion_scoreboard(row, evidence)
    deploiement_ok = deployment_decision == PROMOUVOIR_TESTNET
    promue = (eco.verdict == PROMOTE) and deploiement_ok
    if eco.verdict == KILL:
        bloc = "ECONOMIE_KILL"
    elif not deploiement_ok:
        bloc = "DEPLOIEMENT_NON_PROMU" if deployment_decision is not None else "DEPLOIEMENT_INCONNU"
    elif eco.verdict == MORE_DATA:
        bloc = "ECONOMIE_MORE_DATA"
    else:
        bloc = None
    return {
        "schema_version": SCHEMA_VERSION,
        "promue": promue,
        "verdict_economique": eco.verdict,
        "decision_deploiement": deployment_decision,
        "blocage": bloc,
        "echecs_economiques": list(eco.echecs),
        "manquants_economiques": list(eco.manquants),
        "paper_only": True, "real_execution": False,
    }


__all__ = [
    "SCHEMA_VERSION", "PROMOTE", "KILL", "MORE_DATA", "PASS", "FAIL", "MISSING",
    "N_INDEP_MIN", "MIN_JOURS", "MIN_REGIMES", "CONCENTRATION_MAX",
    "ScoreboardPromotionEvidence", "ScoreboardPromotionVerdict",
    "evaluer_promotion_scoreboard", "promotion_finale",
]
