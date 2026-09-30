from __future__ import annotations

from typing import Any

from hyper_smart_observer.hyperliquid_client.validation import normalize_wallet_address


def info_payload(request_type: str, **kwargs: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": request_type}
    payload.update({key: value for key, value in kwargs.items() if value is not None})
    return payload


def user_payload(request_type: str, address: str, **kwargs: Any) -> dict[str, Any]:
    return info_payload(request_type, user=normalize_wallet_address(address), **kwargs)
