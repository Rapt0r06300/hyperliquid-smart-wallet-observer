"""Event regime taxonomy and deterministic market-relevance routing.

These helpers never predict trade direction. They classify context and narrow the
market universe that deserves microstructure inspection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from hl_observer.event_intelligence.external_event import (
    ExternalEvent,
    ExternalEventType,
)
from hl_observer.event_intelligence.worldmonitor import WorldMonitorEvent


class EventRegime(StrEnum):
    NEWS_LED = "NEWS_LED"
    PREDICTION_LED = "PREDICTION_LED"
    MACRO_LED = "MACRO_LED"
    GEOPOLITICAL_LED = "GEOPOLITICAL_LED"
    MICROSTRUCTURE_LED = "MICROSTRUCTURE_LED"
    LIQUIDATION_LED = "LIQUIDATION_LED"
    UNEXPLAINED = "UNEXPLAINED"


@dataclass(frozen=True, slots=True)
class EventRegimeLabel:
    regime: EventRegime
    reason: str
    event_id: str | None
    causal_ts_ms: int | None
    confidence: float


@dataclass(frozen=True, slots=True)
class AssetRelevance:
    assets: tuple[str, ...]
    categories: tuple[str, ...]
    confidence: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SurpriseContext:
    expected_value: float | None = None
    observed_value: float | None = None
    expected_probability: float | None = None
    prior_probability: float | None = None

    @property
    def surprise_score(self) -> float | None:
        if (
            self.expected_value is not None
            and self.observed_value is not None
        ):
            scale = max(abs(float(self.expected_value)), 1e-9)
            return (float(self.observed_value) - float(self.expected_value)) / scale
        if (
            self.expected_probability is not None
            and self.prior_probability is not None
        ):
            return float(self.expected_probability) - float(self.prior_probability)
        return None


def classify_event_regime(
    event: WorldMonitorEvent | ExternalEvent | None,
    *,
    market_moved: bool,
    liquidation_spike: bool = False,
    event_available_before_move: bool = True,
) -> EventRegimeLabel:
    if liquidation_spike and market_moved:
        return EventRegimeLabel(
            EventRegime.LIQUIDATION_LED,
            "LIQUIDATION_SPIKE_WITH_MARKET_MOVE",
            _event_id(event),
            _event_ts(event),
            1.0,
        )
    if event is None:
        return EventRegimeLabel(
            EventRegime.MICROSTRUCTURE_LED if market_moved else EventRegime.UNEXPLAINED,
            "NO_EXTERNAL_EVENT",
            None,
            None,
            1.0,
        )
    ext = event.event if isinstance(event, WorldMonitorEvent) else event
    if market_moved and not event_available_before_move:
        return EventRegimeLabel(
            EventRegime.MICROSTRUCTURE_LED,
            "EXTERNAL_EVENT_NOT_CAUSALLY_AVAILABLE_BEFORE_MOVE",
            ext.event_id,
            ext.available_ts_ms,
            1.0,
        )
    if not market_moved:
        return EventRegimeLabel(
            EventRegime.UNEXPLAINED,
            "EVENT_WITHOUT_MARKET_REACTION",
            ext.event_id,
            ext.available_ts_ms,
            float(ext.classification_confidence),
        )
    if ext.event_type == ExternalEventType.PREDICTION:
        regime = EventRegime.PREDICTION_LED
    elif ext.event_type == ExternalEventType.MACRO:
        regime = EventRegime.MACRO_LED
    elif ext.event_type in {
        ExternalEventType.GEOPOLITICAL,
        ExternalEventType.CONFLICT,
        ExternalEventType.MILITARY,
        ExternalEventType.SANCTION,
        ExternalEventType.INFRASTRUCTURE,
        ExternalEventType.SUPPLY_CHAIN,
        ExternalEventType.CYBER,
        ExternalEventType.NATURAL,
        ExternalEventType.WEATHER,
        ExternalEventType.OUTAGE,
    }:
        regime = EventRegime.GEOPOLITICAL_LED
    elif ext.event_type == ExternalEventType.NEWS:
        regime = EventRegime.NEWS_LED
    else:
        regime = EventRegime.UNEXPLAINED
    return EventRegimeLabel(
        regime=regime,
        reason=f"EVENT_TYPE_{ext.event_type.value}",
        event_id=ext.event_id,
        causal_ts_ms=ext.available_ts_ms,
        confidence=float(ext.classification_confidence),
    )


def map_event_to_assets(
    event: WorldMonitorEvent | ExternalEvent,
    *,
    available_assets: Iterable[str] = (),
) -> AssetRelevance:
    ext = event.event if isinstance(event, WorldMonitorEvent) else event
    available = {
        str(asset).strip().upper()
        for asset in available_assets
        if str(asset).strip()
    }
    entities = {str(value).strip().upper() for value in ext.entities if str(value).strip()}
    selected: set[str] = set()
    reasons: list[str] = []
    categories: set[str] = set()

    direct = entities & available if available else {
        value for value in entities if _looks_like_ticker(value)
    }
    if direct:
        selected.update(direct)
        reasons.append("DIRECT_ENTITY_TICKER")
        categories.add("direct")

    default_crypto = {"BTC", "ETH"}
    risk_assets = {"BTC", "ETH", "SOL"}
    defensive_crypto = {"BTC", "PAXG"}
    stablecoins = {"USDC", "USDT"}

    if ext.event_type in {
        ExternalEventType.MACRO,
        ExternalEventType.GEOPOLITICAL,
        ExternalEventType.CONFLICT,
        ExternalEventType.MILITARY,
        ExternalEventType.SANCTION,
    }:
        selected.update(risk_assets)
        categories.add("global_risk")
        reasons.append("GLOBAL_RISK_EVENT")

    if ext.event_type in {
        ExternalEventType.CONFLICT,
        ExternalEventType.MILITARY,
        ExternalEventType.SUPPLY_CHAIN,
        ExternalEventType.INFRASTRUCTURE,
        ExternalEventType.WEATHER,
        ExternalEventType.NATURAL,
    }:
        selected.update(defensive_crypto)
        categories.add("risk_off")
        reasons.append("RISK_OFF_WATCH")

    if ext.event_type in {
        ExternalEventType.CYBER,
        ExternalEventType.OUTAGE,
        ExternalEventType.INFRASTRUCTURE,
    }:
        selected.update(default_crypto | stablecoins)
        categories.add("infrastructure")
        reasons.append("CRYPTO_INFRASTRUCTURE_WATCH")

    if ext.event_type == ExternalEventType.PREDICTION:
        selected.update(default_crypto)
        categories.add("prediction")
        reasons.append("PREDICTION_MARKET_CONTEXT")

    if ext.event_type == ExternalEventType.NEWS and not selected:
        selected.update(default_crypto)
        categories.add("generic_news")
        reasons.append("GENERIC_NEWS_DEFAULT")

    if available:
        selected &= available

    confidence = min(
        1.0,
        0.35
        + (0.35 if direct else 0.0)
        + 0.15 * min(2, len(categories))
        + 0.15 * min(1.0, float(ext.classification_confidence)),
    )
    return AssetRelevance(
        assets=tuple(sorted(selected)),
        categories=tuple(sorted(categories)),
        confidence=round(confidence, 6),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _event_id(event: WorldMonitorEvent | ExternalEvent | None) -> str | None:
    if event is None:
        return None
    return event.event.event_id if isinstance(event, WorldMonitorEvent) else event.event_id


def _event_ts(event: WorldMonitorEvent | ExternalEvent | None) -> int | None:
    if event is None:
        return None
    return (
        event.event.available_ts_ms
        if isinstance(event, WorldMonitorEvent)
        else event.available_ts_ms
    )


def _looks_like_ticker(value: str) -> bool:
    return value.isalnum() and 2 <= len(value) <= 10


__all__ = [
    "AssetRelevance",
    "EventRegime",
    "EventRegimeLabel",
    "SurpriseContext",
    "classify_event_regime",
    "map_event_to_assets",
]
