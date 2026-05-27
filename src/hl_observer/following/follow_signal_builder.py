from __future__ import annotations

from pydantic import BaseModel, Field

from hl_observer.utils.time import now_ms


class FollowSignalDraft(BaseModel):
    signal_id: str
    wallet_address: str
    coin: str
    side: str | None = None
    opening_type: str | None = None
    created_at_ms: int = Field(default_factory=now_ms)
    signal_age_ms: int = 0
    raw: dict = Field(default_factory=dict)


def build_follow_signal_from_opening(opening: object) -> FollowSignalDraft:
    created = getattr(opening, "detected_at_ms", None) or now_ms()
    wallet = str(getattr(opening, "wallet_address", ""))
    coin = str(getattr(opening, "coin", "UNKNOWN")).upper()
    opening_type = str(getattr(opening, "opening_type", "UNKNOWN"))
    return FollowSignalDraft(
        signal_id=f"follow:{wallet}:{coin}:{created}",
        wallet_address=wallet,
        coin=coin,
        side=getattr(opening, "side", None),
        opening_type=opening_type,
        created_at_ms=created,
        signal_age_ms=max(0, now_ms() - created),
        raw={"source": "opening"},
    )
