from __future__ import annotations

from typing import Any


_FLAG = "_decision_v2_notional_usdc"
_INSTALLED = "_decision_v2_notional_bridge_installed"


def install_notional_bridge(observer_cls: Any) -> None:
    if getattr(observer_cls, _INSTALLED, False):
        return
    original = observer_cls._dynamic_notional

    def wrapped(self, edge_bps, market_ctx, cluster):
        forced = getattr(self, _FLAG, None)
        if forced is not None:
            try:
                value = float(forced)
            except (TypeError, ValueError):
                value = 0.0
            finally:
                try:
                    delattr(self, _FLAG)
                except AttributeError:
                    pass
            if value > 0:
                return value, f"decision_v2_notional={value:.2f}"
        return original(self, edge_bps, market_ctx, cluster)

    observer_cls._dynamic_notional = wrapped
    setattr(observer_cls, _INSTALLED, True)


def set_next_notional(observer: Any, value: float) -> None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return
    if v > 0:
        setattr(observer, _FLAG, v)


__all__ = ["install_notional_bridge", "set_next_notional"]
