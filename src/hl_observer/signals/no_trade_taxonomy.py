"""NO_TRADE taxonomy (V12 §17 — V10.6 + V11.11 enrichie).

Canonical registry of every NO_TRADE reason. Deny-by-default doctrine: any reason
present means we do NOT trade — but a NO_TRADE must always be *useful*: a clear
code, a severity, whether it is retriable, what data is missing, the next action,
evidence refs and a human dashboard message (the 7 attributes mandated by §V11.11).

This module is the single source of truth for reason codes. It is additive: the
runtime keeps emitting its existing string literals, and ``resolve()`` maps those
literals (aliases) onto canonical codes so nothing is orphaned. Pure / read-only:
no I/O, no order, no fabricated data — it only *describes* why a trade is refused.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - py<3.11 fallback
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class Severity(StrEnum):
    INFO = "INFO"      # contextual / expected
    WARN = "WARN"      # soft block, often retriable when fresh data arrives
    BLOCK = "BLOCK"    # hard block, must not trade


# (code, category, severity, is_retriable, dashboard_message_fr, next_action_fr)
_SPEC = (
    ("INSUFFICIENT_DATA", "DATA", Severity.BLOCK, True, "Donnees insuffisantes pour decider.", "Attendre plus de donnees reelles."),
    ("SOURCE_STALE", "SOURCE", Severity.BLOCK, True, "Source trop ancienne (dernier OK depasse).", "Re-fetch / attendre rafraichissement."),
    ("SOURCE_DEGRADED", "SOURCE", Severity.WARN, True, "Source degradee (qualite/taux de succes bas).", "Verifier la sante de la source."),
    ("SOURCE_CONFLICT", "SOURCE", Severity.BLOCK, True, "Conflit REST vs WS au-dela du seuil.", "Reconcilier avant de decider."),
    ("RATE_LIMITED", "SOURCE", Severity.WARN, True, "Limite de debit atteinte.", "Backoff puis reessayer."),
    ("WALLET_NOT_SCORED", "WALLET", Severity.BLOCK, True, "Wallet pas encore score.", "Scorer le wallet d'abord."),
    ("WALLET_SCORE_TOO_LOW", "WALLET", Severity.BLOCK, False, "Score smart-money trop bas.", "Ignorer ce wallet."),
    ("COPYABILITY_TOO_LOW", "WALLET", Severity.BLOCK, False, "Copyabilite trop faible.", "Ne pas copier ce wallet."),
    ("ONE_BIG_WIN_RISK", "WALLET", Severity.WARN, False, "PnL domine par un seul gros gain.", "Exiger une histoire plus reguliere."),
    ("PNL_CONCENTRATION_RISK", "WALLET", Severity.WARN, False, "PnL trop concentre.", "Diversifier / ecarter."),
    ("HIGH_DRAWDOWN_RISK", "WALLET", Severity.WARN, False, "Drawdown historique trop eleve.", "Ecarter ou reduire le poids."),
    ("INACTIVE_WALLET", "WALLET", Severity.BLOCK, True, "Wallet inactif recemment.", "Attendre une activite fraiche."),
    ("SUSPICIOUS_WALLET", "WALLET", Severity.BLOCK, False, "Wallet suspect (red flags).", "Mettre en liste noire."),
    ("LIFECYCLE_UNKNOWN", "LIFECYCLE", Severity.BLOCK, True, "Type de delta inconnu (UNKNOWN).", "Refuser tant que le lifecycle n'est pas resolu."),
    ("ORPHAN_CLOSE", "LIFECYCLE", Severity.BLOCK, False, "Close orphelin (aucune position connue).", "Refuser le close orphelin."),
    ("AMBIGUOUS_FLIP", "LIFECYCLE", Severity.BLOCK, True, "Flip de direction ambigu.", "Attendre la confirmation du flip."),
    ("DUPLICATE_SIGNAL", "SIGNAL", Severity.INFO, False, "Signal deja vu (doublon).", "Ignorer le doublon."),
    ("SIGNAL_TOO_OLD", "SIGNAL", Severity.BLOCK, False, "Signal trop ancien pour etre copie sans degrader l'edge.", "Ne pas entrer en retard."),
    ("OPEN_ORDERS_CONTEXT_ONLY", "SIGNAL", Severity.INFO, False, "Les ordres ouverts sont du contexte, pas un signal.", "Utiliser seulement comme contexte."),
    ("MID_MISSING", "MARKET", Severity.BLOCK, True, "Prix mid indisponible.", "Attendre un mid reel."),
    ("L2BOOK_MISSING", "MARKET", Severity.BLOCK, True, "Carnet L2 indisponible.", "Attendre le carnet."),
    ("SPREAD_TOO_WIDE", "MARKET", Severity.BLOCK, True, "Spread trop large.", "Attendre un spread plus serre."),
    ("LIQUIDITY_TOO_LOW", "MARKET", Severity.BLOCK, True, "Liquidite insuffisante.", "Attendre plus de liquidite."),
    ("DEPTH_TOO_LOW", "MARKET", Severity.BLOCK, True, "Profondeur de carnet trop faible.", "Attendre plus de profondeur."),
    ("VOLATILITY_TOO_HIGH", "MARKET", Severity.WARN, True, "Volatilite trop elevee.", "Attendre que la volatilite retombe."),
    ("EDGE_UNMEASURABLE", "EDGE", Severity.BLOCK, True, "Edge net non mesurable.", "Attendre des features completes."),
    ("EDGE_REMAINING_TOO_LOW", "EDGE", Severity.BLOCK, False, "Edge net restant trop faible apres couts.", "Ne pas entrer (edge insuffisant)."),
    ("COPY_DEGRADATION_TOO_HIGH", "EDGE", Severity.BLOCK, True, "Degradation de copie trop elevee.", "Refuser (copie trop tardive/degradee)."),
    ("COOLDOWN_ACTIVE", "RISK", Severity.INFO, True, "Cooldown actif.", "Attendre la fin du cooldown."),
    ("PORTFOLIO_EXPOSURE_TOO_HIGH", "PORTFOLIO", Severity.BLOCK, True, "Exposition portefeuille trop elevee.", "Attendre une reduction d'exposition."),
    ("MAX_OPEN_POSITIONS", "PORTFOLIO", Severity.BLOCK, True, "Nombre max de positions ouvertes atteint.", "Attendre une fermeture."),
    ("BLOCKED_ASSET", "RISK", Severity.BLOCK, False, "Actif bloque (exotique / liste noire).", "Ne pas trader cet actif."),
    ("LOSS_HALT_ACTIVE", "RISK", Severity.BLOCK, True, "Arret sur pertes actif.", "Attendre la levee du halt."),
    ("CIRCUIT_BREAKER_ACTIVE", "RISK", Severity.BLOCK, True, "Disjoncteur actif.", "Attendre le reset du disjoncteur."),
    ("PAPER_ENGINE_CANNOT_MODEL", "PAPER", Severity.BLOCK, False, "Le PaperEngine ne peut pas modeliser ce cas.", "Refuser (pas modelisable proprement)."),
    ("NO_MATCHING_PAPER_POSITION", "PAPER", Severity.INFO, False, "Aucune position paper correspondante.", "Pas de reduce/close sans position."),
    ("BACKTEST_CONTEXT_ONLY", "CONTEXT", Severity.INFO, False, "Contexte backtest uniquement.", "Ne pas melanger au live."),
    ("DASHBOARD_EMPTY_STATE", "CONTEXT", Severity.INFO, False, "Etat vide honnete (rien a afficher).", "Afficher l'etat vide, ne rien inventer."),
    ("DATA_NOT_PAGINATED_ENOUGH", "DATA", Severity.WARN, True, "Pagination insuffisante (donnees partielles).", "Paginer davantage avant de decider."),
    ("BACKFILL_INCOMPLETE", "DATA", Severity.BLOCK, True, "Backfill incomplet.", "Terminer le backfill d'abord."),
    ("SOURCE_NOT_AUTHENTICATED_PUBLIC_ONLY", "SOURCE", Severity.INFO, False, "Source publique uniquement (non authentifiee).", "Rester en lecture publique."),
    ("PROXY_POOL_DEGRADED", "SOURCE", Severity.WARN, True, "Pool de proxies degrade.", "Restaurer le pool de proxies."),
    ("FETCH_PROVENANCE_MISSING", "EVIDENCE", Severity.BLOCK, True, "Provenance de fetch manquante.", "Exiger une provenance tracable."),
    ("RAW_HASH_MISSING", "EVIDENCE", Severity.BLOCK, True, "raw_hash manquant.", "Exiger le hash brut."),
    ("FEATURE_HASH_MISSING", "EVIDENCE", Severity.BLOCK, True, "feature_hash manquant.", "Exiger le hash de features."),
    ("WALLET_EVIDENCE_TOO_LOW", "WALLET", Severity.BLOCK, False, "Preuves wallet insuffisantes.", "Exiger plus d'evidence."),
    ("COPY_DELAY_TOO_HIGH", "EDGE", Severity.BLOCK, True, "Delai de copie trop eleve.", "Refuser (latence de copie excessive)."),
    ("EXIT_NOT_FOLLOWABLE", "LIFECYCLE", Severity.WARN, False, "Sortie du leader non suivable proprement.", "Ne pas suivre cette sortie."),
    ("QUEUE_PROBABILITY_TOO_LOW", "PAPER", Severity.WARN, True, "Probabilite de fill (queue) trop faible.", "Refuser le fill peu probable."),
    ("MAKER_REBATE_UNAVAILABLE", "PAPER", Severity.INFO, True, "Rebate maker indisponible.", "Recalculer l'edge sans rebate."),
    ("FUNDING_UNKNOWN", "MARKET", Severity.WARN, True, "Funding inconnu.", "Attendre la donnee de funding."),
    ("LEVERAGE_RISK_TOO_HIGH", "RISK", Severity.BLOCK, False, "Risque de levier trop eleve.", "Reduire le levier simule."),
    ("MARGIN_RISK_TOO_HIGH", "RISK", Severity.BLOCK, False, "Risque de marge trop eleve.", "Refuser (marge insuffisante)."),
    ("CLUSTER_TOO_CROWDED", "PORTFOLIO", Severity.WARN, True, "Cluster trop encombre.", "Diversifier hors du cluster."),
    ("CLUSTER_TOO_FEW_WALLETS", "SIGNAL", Severity.BLOCK, True, "Cluster trop faible (pas assez de wallets independants).", "Attendre une confirmation multi-wallet."),
    ("CLUSTER_STALE", "SIGNAL", Severity.BLOCK, True, "Cluster trop ancien pour etre copie.", "Attendre un cluster frais."),
    ("CLUSTER_CONFIDENCE_TOO_LOW", "SIGNAL", Severity.BLOCK, True, "Confiance moyenne du cluster trop faible.", "Attendre des deltas plus fiables."),
    ("CORRELATION_TOO_HIGH", "PORTFOLIO", Severity.WARN, True, "Correlation trop elevee avec le portefeuille.", "Eviter la sur-correlation."),
    ("STRATEGY_SHADOW_ONLY", "CONTEXT", Severity.INFO, False, "Strategie en mode shadow uniquement.", "Observer sans agir (shadow)."),
    ("MODEL_NOT_CALIBRATED", "MODEL", Severity.BLOCK, True, "Modele non calibre.", "Calibrer avant d'utiliser le modele."),
)

_CODES = tuple(row[0] for row in _SPEC)

NoTradeCode = StrEnum("NoTradeCode", {name: name for name in _CODES})


@dataclass(frozen=True, slots=True)
class NoTradeReason:
    """A complete NO_TRADE reason (the 7 attributes mandated by §V11.11)."""

    reason_code: str
    severity: str
    is_retriable: bool
    category: str
    missing_data: tuple = ()
    next_action: str = ""
    dashboard_message: str = ""
    evidence_refs: tuple = ()

    @property
    def blocks_trade(self) -> bool:
        return True  # deny-by-default: any reason means NO_TRADE

    def to_dict(self) -> dict:
        return {
            "reason_code": self.reason_code,
            "severity": self.severity,
            "is_retriable": self.is_retriable,
            "missing_data": list(self.missing_data),
            "next_action": self.next_action,
            "evidence_refs": list(self.evidence_refs),
            "dashboard_message": self.dashboard_message,
        }


TAXONOMY = {
    name: NoTradeReason(
        reason_code=name,
        category=category,
        severity=str(severity.value),
        is_retriable=retriable,
        dashboard_message=message,
        next_action=next_action,
    )
    for (name, category, severity, retriable, message, next_action) in _SPEC
}

ALIASES = {
    "REJECT_TOO_LATE": "SIGNAL_TOO_OLD",
    "REJECT_TOO_LATE_TO_COPY": "SIGNAL_TOO_OLD",
    "STALE_SIGNAL": "SIGNAL_TOO_OLD",
    "TOO_LATE": "SIGNAL_TOO_OLD",
    "PRICE_MISSING": "MID_MISSING",
    "PRICE_MISSING_EXIT": "MID_MISSING",
    "MID_PRICE_MISSING": "MID_MISSING",
    "MAX_EXPOSURE_REACHED": "PORTFOLIO_EXPOSURE_TOO_HIGH",
    "MAX_OPEN_POSITIONS_REACHED": "MAX_OPEN_POSITIONS",
    "EXOTIC_MARKET_SKIPPED": "BLOCKED_ASSET",
    "MARKET_NOT_LIQUID": "LIQUIDITY_TOO_LOW",
    "LIQUIDITY_TOO_LOW_TO_COPY": "LIQUIDITY_TOO_LOW",
    "REJECT_KELLY_NO_EDGE": "EDGE_REMAINING_TOO_LOW",
    "KELLY_NEGATIVE_NO_EDGE": "EDGE_REMAINING_TOO_LOW",
    "NO_EDGE": "EDGE_REMAINING_TOO_LOW",
    "UNKNOWN_DELTA": "LIFECYCLE_UNKNOWN",
    "REDUCE_OR_CLOSE_NOT_ENTRY": "NO_MATCHING_PAPER_POSITION",
}


def resolve(code):
    """Map a code or known runtime-literal alias to its canonical NoTradeCode.
    Raises ValueError for an unknown code (deny-by-default: never silently swallow)."""
    key = str(code or "").strip().upper()
    if key in _CODES:
        return NoTradeCode(key)
    if key in ALIASES:
        return NoTradeCode(ALIASES[key])
    raise ValueError("unknown NO_TRADE code: " + repr(code))


def reason(code, *, missing_data=(), evidence_refs=(), next_action=None, dashboard_message=None):
    """Build a complete NoTradeReason from a code/alias, with optional overrides."""
    canonical = resolve(code)
    base = TAXONOMY[canonical.value]
    return NoTradeReason(
        reason_code=base.reason_code,
        severity=base.severity,
        is_retriable=base.is_retriable,
        category=base.category,
        missing_data=tuple(missing_data),
        next_action=base.next_action if next_action is None else next_action,
        dashboard_message=base.dashboard_message if dashboard_message is None else dashboard_message,
        evidence_refs=tuple(evidence_refs),
    )


def all_codes():
    return list(_CODES)


def by_category():
    out = {}
    for name, r in TAXONOMY.items():
        out.setdefault(r.category, []).append(name)
    return out


def is_retriable(code):
    return TAXONOMY[resolve(code).value].is_retriable


__all__ = [
    "Severity", "NoTradeCode", "NoTradeReason", "TAXONOMY", "ALIASES",
    "resolve", "reason", "all_codes", "by_category", "is_retriable",
]
