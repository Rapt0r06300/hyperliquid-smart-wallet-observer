"""
Safety gates dYdX v4 — DENY_BY_DEFAULT.

Chaque appel risqué doit passer par ces gates.
Aucune exception n'est silencieuse.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from hyper_smart_observer.dydx_v4.config import DydxV4Config

logger = logging.getLogger(__name__)

# Mots-clés interdits dans toute URL ou payload
_FORBIDDEN_KEYWORDS = frozenset(
    {
        "private_key",
        "privatekey",
        "mnemonic",
        "seed",
        "secret",
        "place_order",
        "cancel_order",
        "transfer",
        "deposit",
        "withdraw",
        "sign",
        "broadcast",
        "/orders",
        "/transfers",
        "/withdrawals",
        "/deposits",
    }
)


@dataclass(frozen=True)
class SafetyResult:
    allowed: bool
    reason: str
    detail: str = ""


def assert_paper_only(config: DydxV4Config) -> None:
    """Lever une exception si paper_only n'est pas activé."""
    if not config.paper_only:
        raise RuntimeError(
            "SAFETY GATE FAILED: paper_only=False — opération bloquée."
        )
    if config.allow_trading:
        raise RuntimeError(
            "SAFETY GATE FAILED: allow_trading=True — opération bloquée."
        )


def assert_no_private_key(config: DydxV4Config) -> None:
    """Lever une exception si allow_private_key est activé."""
    if config.allow_private_key:
        raise RuntimeError(
            "SAFETY GATE FAILED: allow_private_key=True — opération bloquée. "
            "Aucune clé privée, seed ou mnemonic n'est autorisé."
        )


def check_url_safety(url: str) -> SafetyResult:
    """Vérifier qu'une URL ne contient pas de keyword interdit."""
    url_lower = url.lower()
    for kw in _FORBIDDEN_KEYWORDS:
        if kw in url_lower:
            logger.error("SAFETY: URL bloquée — keyword interdit '%s' dans '%s'", kw, url)
            return SafetyResult(
                allowed=False,
                reason="FORBIDDEN_KEYWORD_IN_URL",
                detail=f"keyword='{kw}' url='{url}'",
            )
    return SafetyResult(allowed=True, reason="URL_SAFE")


def check_payload_safety(payload: dict) -> SafetyResult:
    """Vérifier qu'un payload ne contient pas de champs interdits."""
    payload_str = str(payload).lower()
    for kw in _FORBIDDEN_KEYWORDS:
        if kw in payload_str:
            logger.error("SAFETY: Payload bloqué — keyword interdit '%s'", kw)
            return SafetyResult(
                allowed=False,
                reason="FORBIDDEN_KEYWORD_IN_PAYLOAD",
                detail=f"keyword='{kw}'",
            )
    return SafetyResult(allowed=True, reason="PAYLOAD_SAFE")


def is_test_fixture_account(account_address: str | None) -> bool:
    """Vérifier si un compte est un fixture de test (ne jamais compter dans le PnL live)."""
    if not account_address:
        return True
    _TEST_ACCOUNTS = {
        "0x1111111111111111111111111111111111111111",
        "0x2222222222222222222222222222222222222222",
        "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "0x0000000000000000000000000000000000000000",
        "dydx_test_account_1",
        "dydx_test_account_2",
    }
    return account_address.lower() in {a.lower() for a in _TEST_ACCOUNTS}


def gate_signal_for_live(
    config: DydxV4Config,
    signal_age_ms: int,
    account_address: str | None,
    market: str | None,
    edge_remaining_bps: float,
    total_cost_bps: float,
) -> SafetyResult:
    """
    Gate principale pour valider un signal avant paper trade.

    Retourne SafetyResult(allowed=False) avec la raison de refus.
    """
    # 1. Paper-only check
    if not config.paper_only:
        return SafetyResult(False, "PAPER_ONLY_DISABLED")

    # 2. Fixture account check
    if is_test_fixture_account(account_address):
        return SafetyResult(False, "TEST_FIXTURE_ACCOUNT_EXCLUDED_FROM_LIVE")

    # 3. Signal freshness
    if signal_age_ms > config.hard_max_signal_age_ms:
        return SafetyResult(
            False,
            "STALE_SIGNAL",
            f"age={signal_age_ms}ms > hard_max={config.hard_max_signal_age_ms}ms",
        )

    # 4. Market whitelist
    if market and market not in config.market_whitelist:
        return SafetyResult(
            False,
            "MARKET_NOT_WHITELISTED",
            f"market='{market}' not in whitelist={config.market_whitelist}",
        )

    # 5. Market blacklist
    if market and market in config.market_blacklist:
        return SafetyResult(
            False,
            "MARKET_BLACKLISTED",
            f"market='{market}'",
        )

    # 6. Edge check
    if edge_remaining_bps <= 0:
        return SafetyResult(
            False,
            "EDGE_REMAINING_NEGATIVE_OR_ZERO",
            f"edge_remaining={edge_remaining_bps:.2f}bps",
        )

    if edge_remaining_bps < config.min_edge_bps:
        return SafetyResult(
            False,
            "EDGE_REMAINING_TOO_LOW",
            f"edge_remaining={edge_remaining_bps:.2f}bps < min={config.min_edge_bps}bps",
        )

    # 7. Cost multiplier safety (3x rule)
    min_required = max(config.min_edge_bps, config.edge_safety_multiplier * total_cost_bps)
    if edge_remaining_bps < min_required:
        return SafetyResult(
            False,
            "EDGE_BELOW_COST_MULTIPLIER_THRESHOLD",
            (
                f"edge_remaining={edge_remaining_bps:.2f}bps < "
                f"{config.edge_safety_multiplier}x total_cost={total_cost_bps:.2f}bps "
                f"(required={min_required:.2f}bps)"
            ),
        )

    return SafetyResult(True, "SAFETY_GATES_PASSED")


def audit_config(config: DydxV4Config) -> list[str]:
    """
    Audit complet de la configuration.
    Retourne une liste de problèmes trouvés (vide = config sûre).
    """
    issues: list[str] = []

    if config.allow_trading:
        issues.append("CRITICAL: allow_trading=True — INTERDIT")
    if config.allow_private_key:
        issues.append("CRITICAL: allow_private_key=True — INTERDIT")
    if not config.paper_only:
        issues.append("CRITICAL: paper_only=False — INTERDIT")
    if not config.read_only:
        issues.append("CRITICAL: read_only=False — INTERDIT")
    if config.allow_node_private_api:
        issues.append("HIGH: allow_node_private_api=True — dangereux")
    if config.max_signal_age_ms > 35000:
        issues.append(
            f"MEDIUM: max_signal_age_ms={config.max_signal_age_ms} > 35000ms — signaux trop vieux"
        )
    if config.min_edge_bps < 1:
        issues.append(
            f"MEDIUM: min_edge_bps={config.min_edge_bps} < 1bps — edge trop faible"
        )
    if config.max_open_paper_trades > 50:
        issues.append(
            f"LOW: max_open_paper_trades={config.max_open_paper_trades} > 50"
        )

    return issues
