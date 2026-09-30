"""P0-110: fail-closed inventory of scope-relevant environment flags and entrypoints."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from hl_observer.ops.entrypoint_topology import ENTRYPOINT_ROLES, EntrypointRole, audit_entrypoint_topology


class FlagDisposition(StrEnum):
    ACTIVE = "ACTIVE"
    LEGACY_COMPAT = "LEGACY_COMPAT"
    DEAD = "DEAD"
    HISTORICAL_COMMENT_ONLY = "HISTORICAL_COMMENT_ONLY"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class ScopeFlagRecord:
    name: str
    disposition: FlagDisposition
    required_safe_default: str
    may_expand_execution: bool = False
    authoritative_for_strategy_scope: bool = False
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ScopeInventoryIssue:
    code: str
    subject: str
    detail: str


def _r(name: str, default: str, disposition: FlagDisposition = FlagDisposition.ACTIVE, *, expands: bool = False, reason: str = "") -> ScopeFlagRecord:
    return ScopeFlagRecord(name, disposition, default, expands, False, reason)


# Every current capability/scope switch advertised by .env.example. Numeric tuning knobs are
# normally excluded; thresholds whose names contain scope-like tokens are classified explicitly
# so the fail-closed discovery audit cannot mistake them for unreviewed authority. No environment
# flag is authoritative for strategy scope.
_SCOPE_FLAG_RECORD_LIST = (
    _r("HL_ENV", "paper", reason="official environment"),
    _r("HL_ENABLE_MAINNET_EXECUTION", "false", expands=True, reason="mainnet execution tripwire"),
    _r("HL_ENABLE_TESTNET_EXECUTION", "false", FlagDisposition.LEGACY_COMPAT, expands=True, reason="dormant testnet tripwire"),
    _r("HL_REQUIRE_TESTNET_SCHEDULE_CANCEL", "true", FlagDisposition.LEGACY_COMPAT, reason="testnet safety scaffold"),
    _r("REAL_MAINNET_TRADING", "false", expands=True, reason="real-trading tripwire"),
    _r("TESTNET_ONLY", "true", FlagDisposition.LEGACY_COMPAT, reason="testnet compatibility lock"),
    _r("TESTNET_MODE", "false", FlagDisposition.LEGACY_COMPAT, expands=True, reason="dormant testnet mode"),
    _r("TESTNET_EXECUTION_ENABLED", "false", FlagDisposition.LEGACY_COMPAT, expands=True, reason="dormant testnet execution"),
    _r("REQUIRE_EXPLICIT_TESTNET_CONFIRMATION", "true", FlagDisposition.LEGACY_COMPAT, reason="testnet safety scaffold"),
    _r("CONFIRM_TESTNET_EXECUTION", "false", FlagDisposition.LEGACY_COMPAT, expands=True, reason="testnet confirmation tripwire"),
    _r("ALLOW_MAINNET_ORDER_SUBMISSION", "false", expands=True, reason="mainnet submission tripwire"),
    _r("HYPERSMART_MODE", "RESEARCH_ONLY", reason="research-only observer mode"),
    _r("HYPERSMART_ENABLE_EXECUTION", "false", expands=True, reason="execution tripwire"),
    _r("HYPERSMART_ENABLE_TESTNET_EXECUTION", "false", FlagDisposition.LEGACY_COMPAT, expands=True, reason="dormant testnet execution"),
    _r("HYPERSMART_CONFIRM_TESTNET_ONLY", "false", FlagDisposition.LEGACY_COMPAT, reason="dormant testnet confirmation"),
    _r("HYPERSMART_ALLOW_MAINNET", "false", expands=True, reason="mainnet permission tripwire"),
    _r("HYPERSMART_ENABLE_NETWORK_READS", "false", reason="public network-read capability"),
    _r("HYPERSMART_SCORE_REQUIRE_NET_PNL", "true", reason="net-PnL scoring invariant"),
    _r("HYPERSMART_SCORE_STORE_REJECTED", "true", reason="negative-evidence retention"),
    _r("HYPERSMART_ENABLE_PAPER_TRADING", "true", reason="paper-only economic materialization"),
    _r("HYPERSMART_PAPER_MAX_DRAWDOWN_ALLOWED", "0.25", reason="paper drawdown threshold; not scope authority"),
    _r("HYPERSMART_PAPER_REQUIRE_SCORED_WALLET", "true", reason="copy-vault paper gate"),
    _r("HYPERSMART_PAPER_STORE_REFUSALS", "true", reason="refusal evidence retention"),
    _r("HYPERSMART_COPY_MIN_EDGE_REQUIRED_BPS", "8", reason="paper copy edge threshold; not scope authority"),
    _r("HYPERSMART_RUNTIME_MODE", "paper", reason="official runtime mode"),
    _r("HYPERSMART_REAL_ORDERS_ENABLED", "false", expands=True, reason="real-order tripwire"),
    _r("HYPERSMART_EXCHANGE_ENDPOINT_ENABLED", "false", expands=True, reason="exchange endpoint tripwire"),
    _r("HYPERSMART_SIGNATURES_ENABLED", "false", expands=True, reason="signature tripwire"),
    _r("HYPERSMART_WALLET_CONNECT_ENABLED", "false", expands=True, reason="wallet-connect tripwire"),
    _r("HYPERSMART_EXPLORER_OBSERVER_ENABLED", "false", reason="optional public observer"),
    _r("HYPERSMART_WS_MONITOR_ENABLED", "false", reason="optional public websocket monitor"),
    _r("HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE", "0", reason="paper veto authority opt-in"),
    _r("HYPERSMART_V26_FUNDING_VETO", "1", reason="paper risk veto"),
    _r("HYPERSMART_V26_EDGE_TREND_VETO", "1", reason="paper risk veto"),
    _r("HYPERSMART_V26_FUNDING_POLLER", "0", reason="public info poller"),
    _r("HYPERSMART_V26_VOL_BARRIERS", "0", reason="paper volatility barrier"),
    _r("HYPERSMART_V26_AUTO_UNSTUCK", "0", reason="paper position-management experiment"),
    _r("HYPERSMART_V26_UNSTUCK_BUDGET_USD", "10", reason="paper unstuck budget; not scope authority"),
    _r("HYPERSMART_V26_GRADED_HALT", "0", reason="paper halt experiment"),
    _r("HYPERSMART_V26_HALT_AMBER_LOSS_USD", "12", reason="paper amber halt threshold; not scope authority"),
    _r("HYPERSMART_V26_HALT_RED_LOSS_USD", "25", reason="paper red halt threshold; not scope authority"),
    _r("HYPERSMART_V26_PROTECTIONS", "0", reason="paper protection experiment"),
    _r("HYPERSMART_V26_KELLY_LEADER", "0", reason="paper sizing experiment"),
    _r("HYPERSMART_V26_TIER_COST_BUDGET", "0", reason="paper cost-budget experiment"),
    _r("HYPERSMART_V26_MARKET_QUALITY", "0", reason="paper universe filter"),
    _r("HYPERSMART_V26_RECORD_CANDIDATES", "0", reason="read-only replay recorder"),
    _r("HYPERSMART_V26_BOOK_POLLER", "0", reason="public l2Book poller"),
    _r("HYPERSMART_V26_LIVE_BOOK_COSTS", "0", reason="paper live-book cost model"),
)
SCOPE_FLAG_RECORDS = {record.name: record for record in _SCOPE_FLAG_RECORD_LIST}

_SCOPE_TOKENS = (
    "ENABLE", "ENABLED", "ALLOW", "CONFIRM", "MODE", "ONLY", "REQUIRE",
    "AUTHORITATIVE", "VETO", "POLLER", "BARRIER", "UNSTUCK", "HALT",
    "PROTECTION", "KELLY", "RECORD_CANDIDATES", "LIVE_BOOK_COSTS", "STORE_REJECTED",
    "STORE_REFUSALS",
)


def _parse_env_defaults(path: Path) -> dict[str, str]:
    defaults: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        defaults[key.strip()] = value.strip()
    return defaults


def _scope_like(name: str) -> bool:
    upper = name.upper()
    return any(token in upper for token in _SCOPE_TOKENS) or upper in {"HL_ENV", "REAL_MAINNET_TRADING", "TESTNET_ONLY"}


def discover_scope_relevant_defaults(path: Path) -> dict[str, str]:
    defaults = _parse_env_defaults(path)
    return {
        key: value
        for key, value in defaults.items()
        if key in SCOPE_FLAG_RECORDS or _scope_like(key)
    }


def classified_entrypoints() -> dict[str, FlagDisposition]:
    mapping: dict[str, FlagDisposition] = {}
    for name, role in ENTRYPOINT_ROLES.items():
        if role in {EntrypointRole.OFFICIAL_RUNTIME, EntrypointRole.OFFICIAL_ANALYSIS, EntrypointRole.OFFICIAL_RESEARCH}:
            disposition = FlagDisposition.ACTIVE
        elif role in {EntrypointRole.MAINTENANCE, EntrypointRole.COMPAT}:
            disposition = FlagDisposition.LEGACY_COMPAT
        elif role is EntrypointRole.LEGACY:
            disposition = FlagDisposition.DEAD
        elif role is EntrypointRole.ARCHIVE:
            disposition = FlagDisposition.HISTORICAL_COMMENT_ONLY
        else:
            disposition = FlagDisposition.AMBIGUOUS
        mapping[name] = disposition
    return mapping


def audit_scope_flag_inventory(repo_root: str | Path) -> list[ScopeInventoryIssue]:
    root = Path(repo_root)
    issues: list[ScopeInventoryIssue] = []
    env_path = root / ".env.example"
    if not env_path.is_file():
        return [ScopeInventoryIssue("ENV_EXAMPLE_MISSING", ".env.example", "canonical defaults missing")]

    discovered = discover_scope_relevant_defaults(env_path)
    for name in sorted(set(discovered) - set(SCOPE_FLAG_RECORDS)):
        issues.append(ScopeInventoryIssue("AMBIGUOUS_SCOPE_FLAG", name, "scope-like flag has no V5 disposition"))
    for name in sorted(set(SCOPE_FLAG_RECORDS) - set(discovered)):
        issues.append(ScopeInventoryIssue("STALE_SCOPE_FLAG_RECORD", name, "registered flag missing from .env.example"))
    for name in sorted(set(discovered) & set(SCOPE_FLAG_RECORDS)):
        record = SCOPE_FLAG_RECORDS[name]
        actual = discovered[name].lower()
        expected = record.required_safe_default.lower()
        if actual != expected:
            issues.append(ScopeInventoryIssue("UNSAFE_SCOPE_FLAG_DEFAULT", name, f"expected {expected!r}; got {actual!r}"))
        if record.disposition is FlagDisposition.AMBIGUOUS:
            issues.append(ScopeInventoryIssue("AMBIGUOUS_SCOPE_FLAG", name, "explicit AMBIGUOUS disposition is fail-closed"))
        if record.authoritative_for_strategy_scope:
            issues.append(ScopeInventoryIssue("ENV_SCOPE_AUTHORITY_FORBIDDEN", name, "environment flags cannot authorize strategy scope"))

    for issue in audit_entrypoint_topology(root):
        issues.append(ScopeInventoryIssue(f"ENTRYPOINT_{issue.code}", issue.path, issue.detail))
    for name, disposition in classified_entrypoints().items():
        if disposition is FlagDisposition.AMBIGUOUS:
            issues.append(ScopeInventoryIssue("AMBIGUOUS_ENTRYPOINT", name, "entrypoint has no V5 disposition"))
    return issues


__all__ = [
    "FlagDisposition", "ScopeFlagRecord", "ScopeInventoryIssue", "SCOPE_FLAG_RECORDS",
    "discover_scope_relevant_defaults", "classified_entrypoints", "audit_scope_flag_inventory",
]
