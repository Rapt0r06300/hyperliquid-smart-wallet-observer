"""Read-only World Monitor ingestion and normalization for Alina Event Intelligence.

The hosted API adapter is intentionally narrow: only documented GET endpoints are
allowed, credentials are never persisted, and no mutation/trading endpoint can be
called. Normalizers retain structured/derived facts needed by replay research while
excluding article headline/snippet/body text from archive records.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from hl_observer.event_intelligence.external_event import (
    ExternalEvent,
    ExternalEventType,
    SourceTier,
)

HOSTED_BASE_URL = "https://api.worldmonitor.app"
CROSS_SOURCE_PATH = "/api/intelligence/v1/list-cross-source-signals"
NEWS_DIGEST_PATH = "/api/news/v1/list-feed-digest"
PREDICTION_PATH = "/api/prediction/v1/list-prediction-markets"
_ALLOWED_PATHS = frozenset({CROSS_SOURCE_PATH, NEWS_DIGEST_PATH, PREDICTION_PATH})
SCHEMA_VERSION = "alina.worldmonitor_event.v1"


@dataclass(frozen=True, slots=True)
class WorldMonitorVariantContract:
    """One locally auditable World Monitor variant, not an economic result."""

    variant_id: str
    surface: str
    client_method: str
    normalizer: str
    read_only: bool = True


WORLD_MONITOR_VARIANTS = (
    WorldMonitorVariantContract(
        "cross_source_signals",
        CROSS_SOURCE_PATH,
        "list_cross_source_signals",
        "normalize_cross_source_signals",
    ),
    WorldMonitorVariantContract(
        "news_digest",
        NEWS_DIGEST_PATH,
        "list_feed_digest",
        "normalize_news_digest",
    ),
    WorldMonitorVariantContract(
        "prediction_markets",
        PREDICTION_PATH,
        "list_prediction_markets",
        "PredictionShiftTracker.observe",
    ),
    WorldMonitorVariantContract(
        "news_flow_features",
        "derived:news_digest",
        "compute_news_flow_features",
        "compute_news_flow_features",
    ),
    WorldMonitorVariantContract(
        "news_velocity_zscore",
        "derived:news_digest",
        "compute_news_velocity_zscore",
        "compute_news_velocity_zscore",
    ),
    WorldMonitorVariantContract(
        "prediction_shift_features",
        "derived:prediction_markets",
        "PredictionShiftTracker.observe",
        "PredictionShiftTracker.observe",
    ),
)


def validate_worldmonitor_variant_contracts() -> tuple[WorldMonitorVariantContract, ...]:
    """Return the six bounded variants or fail closed on catalog drift."""

    variants = tuple(WORLD_MONITOR_VARIANTS)
    ids = [variant.variant_id for variant in variants]
    if len(variants) != 6 or len(set(ids)) != len(ids):
        raise ValueError("World Monitor variant catalog must contain six unique variants")
    if any(not variant.read_only for variant in variants):
        raise ValueError("World Monitor variants must remain read-only")
    if any(
        variant.surface.startswith("/") and variant.surface not in _ALLOWED_PATHS
        for variant in variants
    ):
        raise ValueError("World Monitor variant surface is outside the GET allowlist")
    return variants


def worldmonitor_safety_receipt(result: object) -> dict[str, object]:
    """Validate the bounded World Monitor read-only surface.

    This receipt covers adapter safety only.  It does not assert that an
    external event is true, causal, or economically useful for Copy-Vault.
    """
    variants = None
    if isinstance(result, Mapping):
        variants = result.get("variants")
        valid = (
            result.get("read_only") is True
            and result.get("real_execution") is False
            and result.get("mutation") is False
            and isinstance(variants, (list, tuple))
            and len(variants) == 6
            and all(
                isinstance(item, Mapping)
                and item.get("read_only") is True
                and (
                    str(item.get("surface") or "") in _ALLOWED_PATHS
                    or str(item.get("surface") or "")
                    in {"derived:news_digest", "derived:prediction_markets"}
                )
                for item in variants
            )
        )
    else:
        valid = False
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "verdict": "WORLDMONITOR_READ_ONLY" if valid else "WORLDMONITOR_UNSAFE",
        "read_only": True,
        "real_execution": False,
        "mutation": False,
        "economic_verdict": "UNMEASURABLE",
        "fail_closed": not valid,
    }


class WorldMonitorError(RuntimeError):
    """Base adapter error."""


class WorldMonitorAuthRequired(WorldMonitorError):
    """Raised before a hosted server-to-server call without an API key."""


class WorldMonitorHTTPError(WorldMonitorError):
    """Fail-closed HTTP error with no credential material."""


@dataclass(frozen=True, slots=True)
class WorldMonitorEvent:
    """ExternalEvent plus World Monitor derived facts safe for quantitative replay."""

    event: ExternalEvent
    kind: str
    publisher: str = ""
    feed_category: str = ""
    story_phase: str = ""
    story_first_seen_ms: int | None = None
    mention_count: int = 0
    source_count: int = 0
    importance_score: float | None = None
    credibility_score: float | None = None
    is_alert: bool = False
    coverage_state: str = "current"
    probability: float | None = None
    probability_delta_pp: float | None = None
    volume_usd: float | None = None
    prediction_source: str = ""
    severity_score_raw: float | None = None
    signal_count: int = 0

    @property
    def usable_for_signal(self) -> bool:
        return self.coverage_state.casefold() in {"current", "complete"}

    def to_archive_record(self) -> dict[str, object]:
        """Return structured R1/R2-style facts, never source article expression."""

        record = self.event.to_r2_record()
        record.update(
            {
                "worldmonitor_schema": SCHEMA_VERSION,
                "worldmonitor_kind": self.kind,
                "publisher": self.publisher,
                "feed_category": self.feed_category,
                "story_phase": self.story_phase,
                "story_first_seen_ms": self.story_first_seen_ms,
                "mention_count": self.mention_count,
                "source_count": self.source_count,
                "importance_score": self.importance_score,
                "credibility_score": self.credibility_score,
                "is_alert": self.is_alert,
                "coverage_state": self.coverage_state,
                "probability": self.probability,
                "probability_delta_pp": self.probability_delta_pp,
                "volume_usd": self.volume_usd,
                "prediction_source": self.prediction_source,
                "severity_score_raw": self.severity_score_raw,
                "signal_count": self.signal_count,
            }
        )
        return record


class WorldMonitorReadOnlyClient:
    """Minimal GET-only client for three documented intelligence surfaces."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = HOSTED_BASE_URL,
        timeout_s: float = 10.0,
        http_client: Any | None = None,
        require_api_key: bool | None = None,
    ) -> None:
        base = str(base_url or "").strip().rstrip("/")
        if not base.startswith(("https://", "http://")):
            raise ValueError("base_url must be http(s)")
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(float(timeout_s))
            or float(timeout_s) <= 0.0
        ):
            raise ValueError("timeout_s must be a finite positive number")
        self.base_url = base
        self._api_key = str(api_key or "").strip()
        self.timeout_s = float(timeout_s)
        self._http_client = http_client
        hosted = self.base_url.casefold() == HOSTED_BASE_URL.casefold()
        self.require_api_key = hosted if require_api_key is None else bool(require_api_key)

    @property
    def real_execution(self) -> bool:
        return False

    def list_cross_source_signals(self) -> dict[str, Any]:
        return self._get(CROSS_SOURCE_PATH)

    def list_feed_digest(
        self,
        *,
        variant: str = "full",
        lang: str = "en",
    ) -> dict[str, Any]:
        return self._get(
            NEWS_DIGEST_PATH,
            params={"variant": str(variant), "lang": str(lang)},
        )

    def list_prediction_markets(
        self,
        *,
        page_size: int = 100,
        category: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        if type(page_size) is not int or page_size <= 0:
            raise ValueError("page_size must be a positive integer")
        params: dict[str, object] = {"page_size": min(100, page_size)}
        if category:
            params["category"] = str(category)
        if query:
            params["query"] = str(query)
        return self._get(PREDICTION_PATH, params=params)

    def _get(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        if path not in _ALLOWED_PATHS:
            raise ValueError("World Monitor path is not in read-only allowlist")
        if self.require_api_key and not self._api_key:
            raise WorldMonitorAuthRequired("WORLDMONITOR_API_KEY_REQUIRED")

        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["X-WorldMonitor-Key"] = self._api_key
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        owns_client = self._http_client is None
        client = self._http_client or httpx.Client(timeout=self.timeout_s)
        try:
            response = client.get(url, params=dict(params or {}), headers=headers)
            status = int(response.status_code)
            if status != 200:
                retry_after = str(response.headers.get("Retry-After") or "")
                suffix = f":retry_after={retry_after}" if retry_after else ""
                raise WorldMonitorHTTPError(f"WORLDMONITOR_HTTP_{status}{suffix}")
            payload = response.json()
        except WorldMonitorError:
            raise
        except Exception as exc:
            raise WorldMonitorHTTPError(
                f"WORLDMONITOR_REQUEST_FAILED:{exc.__class__.__name__}"
            ) from exc
        finally:
            if owns_client:
                client.close()
        if not isinstance(payload, dict):
            raise WorldMonitorHTTPError("WORLDMONITOR_PAYLOAD_NOT_OBJECT")
        return payload


def normalize_cross_source_signals(
    payload: Mapping[str, Any],
    *,
    received_ts_ms: int,
    methodology_version: str = "worldmonitor-cross-source-v1",
) -> list[WorldMonitorEvent]:
    received = _require_received_ts_ms(received_ts_ms)
    rows = payload.get("signals")
    if not isinstance(rows, list):
        return []
    output: list[WorldMonitorEvent] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        signal_id = str(row.get("id") or "").strip()
        detected_at = _positive_int(row.get("detectedAt"))
        if not signal_id or detected_at is None or detected_at > received:
            continue
        raw_type = str(row.get("type") or "").strip()
        theater = str(row.get("theater") or "").strip()
        severity_name = str(row.get("severity") or "").strip()
        if "signalCount" in row and _strict_non_negative_int(row.get("signalCount")) is None:
            continue
        signal_count = max(1, _non_negative_int(row.get("signalCount"), default=1))
        severity_raw = _finite_or_none(row.get("severityScore"))
        event = ExternalEvent(
            event_id=f"wm:cross:{signal_id}",
            source="worldmonitor.cross_source",
            event_type=_cross_source_event_type(raw_type),
            source_tier=SourceTier.AGGREGATOR,
            retrieval_ts_ms=received,
            ingest_ts_ms=received,
            event_ts_ms=detected_at,
            methodology_version=methodology_version,
            raw_evidence_ref=f"{CROSS_SOURCE_PATH}#signal/{signal_id}",
            regions=(theater,) if theater else (),
            entities=tuple(
                str(value)
                for value in (row.get("contributingTypes") or [])
                if str(value).strip()
            ),
            severity=_severity_from_enum(severity_name),
            classification_confidence=1.0,
            corroboration_count=signal_count,
        )
        output.append(
            WorldMonitorEvent(
                event=event,
                kind="cross_source",
                publisher="World Monitor",
                coverage_state="current",
                severity_score_raw=severity_raw,
                signal_count=signal_count,
            )
        )
    return output


def normalize_news_digest(
    payload: Mapping[str, Any],
    *,
    received_ts_ms: int,
    methodology_version: str = "worldmonitor-news-digest-v1",
) -> list[WorldMonitorEvent]:
    received = _require_received_ts_ms(received_ts_ms)
    categories = payload.get("categories")
    if not isinstance(categories, Mapping):
        return []
    coverage = payload.get("coverage")
    coverage_state = (
        str(coverage.get("state") or "current").casefold()
        if isinstance(coverage, Mapping)
        else "current"
    )
    if coverage_state == "unavailable":
        return []

    output: list[WorldMonitorEvent] = []
    for category, bucket in categories.items():
        if not isinstance(bucket, Mapping):
            continue
        items = bucket.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            publisher = str(item.get("source") or "").strip()
            title = str(item.get("title") or "").strip()
            link = str(item.get("link") or "").strip()
            if not publisher or not title:
                continue
            if "isAlert" in item and not isinstance(item.get("isAlert"), bool):
                continue
            if "corroborationCount" in item and _strict_non_negative_int(
                item.get("corroborationCount")
            ) is None:
                continue
            published = _causal_optional_ts(item.get("publishedAt"), received)
            story_meta = item.get("storyMeta")
            story_meta = story_meta if isinstance(story_meta, Mapping) else {}
            first_seen = _causal_optional_ts(
                story_meta.get("firstSeen"),
                received,
            )
            threat = item.get("threat")
            threat = threat if isinstance(threat, Mapping) else {}
            threat_category = str(threat.get("category") or "").strip()
            threat_confidence = _bounded_probability(threat.get("confidence"), default=0.0)
            severity = _severity_from_enum(str(threat.get("level") or ""))
            source_count = max(
                1,
                _non_negative_int(story_meta.get("sourceCount"), default=1),
            )
            if (
                "sourceCount" in story_meta
                and _strict_non_negative_int(story_meta.get("sourceCount")) is None
            ):
                continue
            corroboration = max(
                source_count,
                _non_negative_int(item.get("corroborationCount"), default=1),
            )
            tickers = tuple(
                str(value).strip().upper()
                for value in (item.get("tickers") or [])
                if str(value).strip()
            )
            location_name = str(item.get("locationName") or "").strip()
            event_id = _news_event_id(
                publisher=publisher,
                title=title,
                link=link,
                published_ts_ms=published,
            )
            event = ExternalEvent(
                event_id=event_id,
                source="worldmonitor.news",
                event_type=_news_event_type(
                    threat_category=threat_category,
                    feed_category=str(category),
                ),
                source_tier=SourceTier.AGGREGATOR,
                publication_ts_ms=published,
                retrieval_ts_ms=received,
                ingest_ts_ms=received,
                event_ts_ms=first_seen,
                source_link=link,
                regions=(location_name,) if location_name else (),
                entities=tickers,
                severity=severity,
                classification_confidence=threat_confidence,
                corroboration_count=corroboration,
                methodology_version=methodology_version,
                raw_evidence_ref=f"{NEWS_DIGEST_PATH}#event/{event_id}",
            )
            output.append(
                WorldMonitorEvent(
                    event=event,
                    kind="news",
                    publisher=publisher,
                    feed_category=str(category),
                    story_phase=str(story_meta.get("phase") or ""),
                    story_first_seen_ms=first_seen,
                    mention_count=_non_negative_int(
                        story_meta.get("mentionCount"),
                        default=0,
                    ),
                    source_count=source_count,
                    importance_score=_finite_or_none(item.get("importanceScore")),
                    credibility_score=_finite_or_none(item.get("credibilityScore")),
                    is_alert=item.get("isAlert") is True,
                    coverage_state=coverage_state,
                )
            )
    return output


class PredictionShiftTracker:
    """Convert read-only prediction snapshots into causal probability-shift events."""

    def __init__(
        self,
        *,
        min_abs_delta_pp: float = 5.0,
        min_volume_usd: float = 0.0,
    ) -> None:
        delta = _finite_or_none(min_abs_delta_pp)
        volume = _finite_or_none(min_volume_usd)
        if delta is None or delta <= 0.0:
            raise ValueError("min_abs_delta_pp must be > 0")
        if volume is None or volume < 0.0:
            raise ValueError("min_volume_usd must be non-negative")
        self.min_abs_delta_pp = delta
        self.min_volume_usd = volume
        self._last: dict[tuple[str, str], tuple[int, float]] = {}

    def observe(
        self,
        payload: Mapping[str, Any],
        *,
        received_ts_ms: int,
        methodology_version: str = "worldmonitor-prediction-shift-v1",
    ) -> list[WorldMonitorEvent]:
        received = _require_received_ts_ms(received_ts_ms)
        if payload.get("dataAvailable") is not True:
            return []
        fetched_at = _positive_int(payload.get("fetchedAt"))
        if fetched_at is None or fetched_at > received:
            return []
        markets = payload.get("markets")
        if not isinstance(markets, list):
            return []

        output: list[WorldMonitorEvent] = []
        for row in markets:
            if not isinstance(row, Mapping):
                continue
            market_id = str(row.get("id") or "").strip()
            source = str(row.get("source") or "MARKET_SOURCE_UNSPECIFIED").strip()
            yes_price = _bounded_probability(row.get("yesPrice"), default=None)
            volume = _finite_non_negative_or_none(row.get("volume"))
            if (
                not market_id
                or yes_price is None
                or (volume is not None and volume < self.min_volume_usd)
            ):
                continue
            key = (source, market_id)
            previous = self._last.get(key)
            if previous is not None and fetched_at <= previous[0]:
                continue
            self._last[key] = (fetched_at, yes_price)
            if previous is None:
                continue
            delta_pp = (yes_price - previous[1]) * 100.0
            if abs(delta_pp) < self.min_abs_delta_pp:
                continue

            category = str(row.get("category") or "").strip()
            link = str(row.get("url") or "").strip()
            event_id = _prediction_event_id(
                source=source,
                market_id=market_id,
                fetched_at=fetched_at,
                yes_price=yes_price,
            )
            event = ExternalEvent(
                event_id=event_id,
                source="worldmonitor.prediction",
                event_type=ExternalEventType.PREDICTION,
                source_tier=SourceTier.AGGREGATOR,
                retrieval_ts_ms=received,
                ingest_ts_ms=received,
                event_ts_ms=fetched_at,
                source_link=link,
                entities=tuple(value for value in (market_id, category) if value),
                severity=None,
                classification_confidence=1.0,
                corroboration_count=1,
                methodology_version=methodology_version,
                raw_evidence_ref=f"{PREDICTION_PATH}#market/{market_id}/{fetched_at}",
            )
            output.append(
                WorldMonitorEvent(
                    event=event,
                    kind="prediction",
                    publisher=source,
                    feed_category=category,
                    coverage_state="current",
                    probability=yes_price,
                    probability_delta_pp=delta_pp,
                    volume_usd=volume,
                    prediction_source=source,
                )
            )
        return output


def _cross_source_event_type(raw_type: str) -> ExternalEventType:
    value = str(raw_type or "").upper()
    mapping = {
        "GPS_JAMMING": ExternalEventType.MILITARY,
        "MILITARY_FLIGHT_SURGE": ExternalEventType.MILITARY,
        "UNREST_SURGE": ExternalEventType.GEOPOLITICAL,
        "OREF_ALERT_CLUSTER": ExternalEventType.CONFLICT,
        "CYBER_ESCALATION": ExternalEventType.CYBER,
        "SHIPPING_DISRUPTION": ExternalEventType.SUPPLY_CHAIN,
        "SANCTIONS_SURGE": ExternalEventType.SANCTION,
        "EARTHQUAKE_SIGNIFICANT": ExternalEventType.NATURAL,
        "RADIATION_ANOMALY": ExternalEventType.NATURAL,
        "INFRASTRUCTURE_OUTAGE": ExternalEventType.INFRASTRUCTURE,
        "WILDFIRE_ESCALATION": ExternalEventType.NATURAL,
        "WEATHER_EXTREME": ExternalEventType.WEATHER,
        "COMMODITY_SHOCK": ExternalEventType.MACRO,
        "VIX_SPIKE": ExternalEventType.MACRO,
        "MARKET_STRESS": ExternalEventType.MACRO,
        "MEDIA_TONE_DETERIORATION": ExternalEventType.NEWS,
        "RISK_SCORE_SPIKE": ExternalEventType.GEOPOLITICAL,
        "COMPOSITE_ESCALATION": ExternalEventType.GEOPOLITICAL,
        "THERMAL_SPIKE": ExternalEventType.INFRASTRUCTURE,
        "DISPLACEMENT_SURGE": ExternalEventType.GEOPOLITICAL,
        "FORECAST_DETERIORATION": ExternalEventType.GEOPOLITICAL,
    }
    for token, event_type in mapping.items():
        if token in value:
            return event_type
    return ExternalEventType.OTHER


def _news_event_type(*, threat_category: str, feed_category: str) -> ExternalEventType:
    value = f"{threat_category} {feed_category}".casefold()
    if any(token in value for token in ("military", "defense", "war")):
        return ExternalEventType.MILITARY
    if any(token in value for token in ("cyber", "hack")):
        return ExternalEventType.CYBER
    if any(token in value for token in ("sanction",)):
        return ExternalEventType.SANCTION
    if any(token in value for token in ("economic", "finance", "commodity", "energy", "fed")):
        return ExternalEventType.MACRO
    if any(token in value for token in ("disaster", "earthquake", "wildfire", "flood")):
        return ExternalEventType.NATURAL
    if any(token in value for token in ("weather", "storm", "hurricane")):
        return ExternalEventType.WEATHER
    if any(token in value for token in ("diplomatic", "conflict", "crisis", "geopolit")):
        return ExternalEventType.GEOPOLITICAL
    return ExternalEventType.NEWS


def _severity_from_enum(value: str) -> float | None:
    upper = str(value or "").upper()
    if upper.endswith("_LOW"):
        return 0.25
    if upper.endswith("_MEDIUM"):
        return 0.50
    if upper.endswith("_HIGH"):
        return 0.75
    if upper.endswith("_CRITICAL"):
        return 1.0
    return None


def _news_event_id(
    *,
    publisher: str,
    title: str,
    link: str,
    published_ts_ms: int | None,
) -> str:
    material = "\x1f".join(
        (
            publisher.casefold(),
            link.strip(),
            str(published_ts_ms or 0),
            title.casefold(),
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return f"wm:news:{digest}"


def _prediction_event_id(
    *,
    source: str,
    market_id: str,
    fetched_at: int,
    yes_price: float,
) -> str:
    material = f"{source}\x1f{market_id}\x1f{fetched_at}\x1f{yes_price:.12f}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"wm:prediction:{digest}"


def _strict_non_negative_int(value: Any) -> int | None:
    if type(value) is int:
        return value if value >= 0 else None
    return None


def _require_received_ts_ms(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("received_ts_ms must be a non-negative integer")
    return value


def _positive_int(value: Any) -> int | None:
    parsed = _strict_non_negative_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _non_negative_int(value: Any, *, default: int = 0) -> int:
    parsed = _strict_non_negative_int(value)
    return parsed if parsed is not None else default


def _causal_optional_ts(value: Any, received_ts_ms: int) -> int | None:
    parsed = _positive_int(value)
    if parsed is None or parsed > received_ts_ms:
        return None
    return parsed


def _finite_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _finite_non_negative_or_none(value: Any) -> float | None:
    parsed = _finite_or_none(value)
    return parsed if parsed is not None and parsed >= 0.0 else None


def _bounded_probability(value: Any, *, default: float | None) -> float | None:
    parsed = _finite_or_none(value)
    if parsed is None or not 0.0 <= parsed <= 1.0:
        return default
    return parsed


__all__ = [
    "CROSS_SOURCE_PATH",
    "HOSTED_BASE_URL",
    "NEWS_DIGEST_PATH",
    "PREDICTION_PATH",
    "PredictionShiftTracker",
    "SCHEMA_VERSION",
    "WorldMonitorAuthRequired",
    "WorldMonitorError",
    "WorldMonitorEvent",
    "WorldMonitorHTTPError",
    "WorldMonitorReadOnlyClient",
    "worldmonitor_safety_receipt",
    "normalize_cross_source_signals",
    "normalize_news_digest",
]
