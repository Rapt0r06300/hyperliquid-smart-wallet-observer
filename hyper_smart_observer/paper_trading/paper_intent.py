from __future__ import annotations

from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc
from uuid import uuid4

from hyper_smart_observer.hyperliquid_client.models import PaperIntent, PaperIntentStatus
from hyper_smart_observer.hyperliquid_client.validation import normalize_wallet_address


def build_paper_intent(
    *,
    wallet_address: str,
    coin: str,
    side: str,
    reference_price: float,
    requested_notional: float,
    source: str = "local_cli",
    reason: str = "local paper simulation",
) -> PaperIntent:
    warnings: list[str] = []
    status = PaperIntentStatus.CREATED
    refusal_reason = None
    try:
        wallet = normalize_wallet_address(wallet_address)
    except ValueError:
        wallet = wallet_address
        status = PaperIntentStatus.INVALID_DATA
        refusal_reason = "INVALID_WALLET_ADDRESS"
        warnings.append("Wallet must be a full 42-character 0x hex address.")
    return PaperIntent(
        intent_id=str(uuid4()),
        wallet_address=wallet,
        coin=coin.upper(),
        side=side.upper(),
        reference_price=reference_price,
        requested_notional=requested_notional,
        created_at=datetime.now(UTC),
        source=source,
        reason=reason,
        status=status,
        refusal_reason=refusal_reason,
        warnings=warnings,
    )


def build_intent_from_observed_action(action, *, requested_notional: float) -> PaperIntent:
    return build_paper_intent(
        wallet_address=action.wallet_address,
        coin=action.coin,
        side="BUY" if "LONG" in action.action_type.value else "SELL",
        reference_price=action.price or 0.0,
        requested_notional=requested_notional,
        source="observed_position_action",
        reason=f"local paper simulation replay from {action.action_type.value}",
    )
