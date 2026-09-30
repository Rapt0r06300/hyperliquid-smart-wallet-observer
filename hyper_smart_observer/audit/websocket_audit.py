from __future__ import annotations

from hyper_smart_observer.app.config import AppConfig


def audit_websocket_limits(config: AppConfig) -> tuple[bool, str]:
    ok = config.ws_max_user_subscriptions <= 10 and config.ws_max_subscriptions <= 1000
    return ok, f"user_subscriptions={config.ws_max_user_subscriptions}, subscriptions={config.ws_max_subscriptions}"
