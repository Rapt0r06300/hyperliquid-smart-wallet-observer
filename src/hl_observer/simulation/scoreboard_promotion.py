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
from typing import Any, Iterable, Mapping, Sequence

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
    if value is None or not isinstance(value, bool):
        return MISSING
    return PASS if value else FAIL


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


def absolute_net_progress_gate(
    challenger_net_pnl: object,
    baseline_net_pnl: object | None = None,
) -> dict[str, Any]:
    """Require an absolute positive challenger result, not relative loss reduction."""
    challenger = _fini(challenger_net_pnl)
    baseline = _fini(baseline_net_pnl) if baseline_net_pnl is not None else None
    loss_reduction_only = bool(
        baseline is not None and baseline < 0 and challenger is not None and baseline < challenger <= 0
    )
    if challenger is None:
        status = "UNMEASURABLE"
        reason = "CHALLENGER_NET_PNL_MISSING_OR_NONFINITE"
    elif challenger <= 0:
        status = "REJECTED"
        reason = "CHALLENGER_NET_PNL_NOT_POSITIVE"
    else:
        status = "PROVEN"
        reason = None
    return {
        "status": status,
        "challenger_net_pnl": challenger,
        "baseline_net_pnl": baseline,
        "relative_only": False,
        "loss_reduction_without_positive_pnl": loss_reduction_only,
        "reason": reason,
        "paper_only": True,
        "real_execution": False,
    }


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
    "absolute_net_progress_gate",
    "evaluer_promotion_scoreboard", "promotion_finale",
]


def _score_base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _score_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _score_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def scoreboard_promotion_safety_receipt(result: Any) -> dict[str, Any]:
    valid = isinstance(result, Mapping) and result.get("paper_only") is True and result.get("real_execution") is False and result.get("promue") is False
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCOREBOARD_PROMOTION_SAFE" if valid else "SCOREBOARD_PROMOTION_UNSAFE", fail_closed=not valid)


def score_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_FIELD_PRESENT" if valid else "SCORE_FIELD_MISSING", field=field, fail_closed=not valid)


def score_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_FIELD_NON_NULL" if valid else "SCORE_FIELD_NULL", field=field, fail_closed=not valid)


def score_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_FIELD_TYPE_VALID" if valid else "SCORE_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def score_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _score_finite(value)
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_VALUE_FINITE" if valid else "SCORE_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def score_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _score_integer(event_ts_ms) and _score_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_EVENT_WITHIN_CUTOFF" if valid else "SCORE_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def score_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _score_integer(event_ts_ms) and _score_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_EVENT_AGE_VALID" if valid else "SCORE_EVENT_TOO_OLD", fail_closed=not valid)


def score_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(str(value).strip() for value in values) and len(values) == len(set(values))
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_EVENTS_UNIQUE" if valid else "SCORE_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def score_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _score_integer(attempts) and _score_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_RETRY_BOUNDED" if valid else "SCORE_RETRY_UNSAFE", fail_closed=not valid)


def score_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_REPLAY_DETERMINISTIC" if valid else "SCORE_REPLAY_DIVERGED", fail_closed=not valid)


def score_fill_duplicate_receipt(*, fill_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(fill_ids) and all(str(value).strip() for value in fill_ids) and len(fill_ids) == len(set(fill_ids))
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_FILLS_UNIQUE" if valid else "SCORE_FILL_DUPLICATED", fail_closed=not valid)


def score_partition_receipt(*, train_ids: Sequence[Any], oos_ids: Sequence[Any], forward_ids: Sequence[Any]) -> dict[str, Any]:
    train, oos, forward = set(train_ids), set(oos_ids), set(forward_ids)
    valid = bool(train) and bool(oos) and bool(forward) and not (train & oos or train & forward or oos & forward)
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_PARTITIONS_DISJOINT" if valid else "SCORE_PARTITIONS_OVERLAP", fail_closed=not valid)


def score_holdout_receipt(*, tuned_on_holdout: bool, holdout_locked: bool) -> dict[str, Any]:
    valid = tuned_on_holdout is False and holdout_locked is True
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_HOLDOUT_LOCKED" if valid else "SCORE_HOLDOUT_CONTAMINATED", fail_closed=not valid)


def score_embargo_receipt(*, gap_ms: Any, required_gap_ms: Any) -> dict[str, Any]:
    valid = _score_integer(gap_ms) and _score_integer(required_gap_ms) and gap_ms >= 0 and gap_ms >= required_gap_ms
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_EMBARGO_SUFFICIENT" if valid else "SCORE_EMBARGO_INSUFFICIENT", fail_closed=not valid)


def score_trials_receipt(*, trials: Any, recorded_trials: Any) -> dict[str, Any]:
    valid = _score_integer(trials) and _score_integer(recorded_trials) and trials > 0 and recorded_trials == trials
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_TRIALS_RECORDED" if valid else "SCORE_TRIALS_MISSING", fail_closed=not valid)


def score_effect_size_receipt(*, trade_count: Any, gain: Any, minimum_trades: Any = 2) -> dict[str, Any]:
    valid = _score_integer(trade_count) and _score_integer(minimum_trades) and _score_finite(gain) and trade_count >= minimum_trades
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_EFFECT_NOT_SINGLE_TRADE" if valid else "SCORE_EFFECT_UNDERPOWERED", fail_closed=not valid)


def score_wallet_independence_receipt(*, wallet_ids: Sequence[Any], max_correlation: Any) -> dict[str, Any]:
    valid = bool(wallet_ids) and len(wallet_ids) == len(set(wallet_ids)) and _score_finite(max_correlation) and 0 <= float(max_correlation) < 1
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_WALLETS_INDEPENDENT" if valid else "SCORE_WALLETS_CORRELATED", fail_closed=not valid)


def score_hash_receipt(*, code_sha_before: Any, code_sha_after: Any, data_sha_before: Any, data_sha_after: Any) -> dict[str, Any]:
    valid = all(isinstance(value, str) and bool(value.strip()) for value in (code_sha_before, code_sha_after, data_sha_before, data_sha_after)) and code_sha_before == code_sha_after and data_sha_before == data_sha_after
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_HASHES_UNCHANGED" if valid else "SCORE_HASHES_CHANGED", fail_closed=not valid)


def score_forward_cutoff_receipt(*, forward_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _score_integer(forward_ts_ms) and _score_integer(cutoff_ts_ms) and forward_ts_ms > cutoff_ts_ms
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_FORWARD_AFTER_CUTOFF" if valid else "SCORE_FORWARD_BEFORE_CUTOFF", fail_closed=not valid)


def score_pessimistic_edge_receipt(*, gross_edge: Any, slippage: Any, fees: Any) -> dict[str, Any]:
    gross = float(gross_edge) if _score_finite(gross_edge) else None
    slip = float(slippage) if _score_finite(slippage) else None
    fee = float(fees) if _score_finite(fees) else None
    valid = gross is not None and slip is not None and fee is not None and gross - slip - fee > 0
    return _score_base("PROVEN" if valid else "REJECTED", verdict="SCORE_EDGE_SURVIVES_COSTS" if valid else "SCORE_EDGE_ERASED_BY_COSTS", fail_closed=not valid)


__all__ += [
    "scoreboard_promotion_safety_receipt", "score_required_field_receipt", "score_null_field_receipt",
    "score_field_type_receipt", "score_finite_receipt", "score_cutoff_receipt", "score_age_receipt",
    "score_duplicate_receipt", "score_retry_receipt", "score_replay_receipt", "score_fill_duplicate_receipt",
    "score_partition_receipt", "score_holdout_receipt", "score_embargo_receipt", "score_trials_receipt",
    "score_effect_size_receipt", "score_wallet_independence_receipt", "score_hash_receipt",
    "score_forward_cutoff_receipt", "score_pessimistic_edge_receipt",
]
