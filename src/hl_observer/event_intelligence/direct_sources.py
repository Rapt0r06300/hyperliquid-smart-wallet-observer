"""Read-only direct upstream event sources for Event Intelligence.

The adapters here exist to compare primary-source timing with World Monitor timing.
They are deliberately GET-only and normalization-only: no order path, no mutation,
no secret persistence, and no network access is needed by tests.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlencode

import httpx

from hl_observer.event_intelligence.external_event import (
    ExternalEvent,
    ExternalEventType,
    SourceTier,
)


@dataclass(frozen=True, slots=True)
class DirectSourceSpec:
    source_id: str
    base_url: str
    event_type: ExternalEventType
    source_tier: SourceTier
    requires_api_key: bool = False
    refresh_hint_s: int | None = None
    attribution: str = ""
    enabled_by_default: bool = True


DIRECT_SOURCES: dict[str, DirectSourceSpec] = {
    "usgs_earthquakes": DirectSourceSpec(
        source_id="usgs_earthquakes",
        base_url=(
            "https://earthquake.usgs.gov/earthquakes/feed/v1.0/"
            "summary/all_hour.geojson"
        ),
        event_type=ExternalEventType.NATURAL,
        source_tier=SourceTier.PRIMARY_OFFICIAL,
        refresh_hint_s=60,
        attribution="USGS",
    ),
    "nasa_eonet": DirectSourceSpec(
        source_id="nasa_eonet",
        base_url="https://eonet.gsfc.nasa.gov/api/v3/events",
        event_type=ExternalEventType.NATURAL,
        source_tier=SourceTier.PRIMARY_OFFICIAL,
        refresh_hint_s=300,
        attribution="NASA EONET",
    ),
    "gdacs": DirectSourceSpec(
        source_id="gdacs",
        base_url=(
            "https://www.gdacs.org/gdacsapi/api/Events/"
            "geteventlist/SEARCH"
        ),
        event_type=ExternalEventType.NATURAL,
        source_tier=SourceTier.PRIMARY_OFFICIAL,
        refresh_hint_s=360,
        attribution="GDACS",
    ),
    "gdelt_doc": DirectSourceSpec(
        source_id="gdelt_doc",
        base_url="https://api.gdeltproject.org/api/v2/doc/doc",
        event_type=ExternalEventType.NEWS,
        source_tier=SourceTier.AGGREGATOR,
        refresh_hint_s=60,
        attribution="GDELT",
    ),
    "fred": DirectSourceSpec(
        source_id="fred",
        base_url=(
            "https://api.stlouisfed.org/fred/series/observations"
        ),
        event_type=ExternalEventType.MACRO,
        source_tier=SourceTier.PRIMARY_OFFICIAL,
        requires_api_key=True,
        refresh_hint_s=300,
        attribution="Federal Reserve Bank of St. Louis FRED",
        enabled_by_default=False,
    ),
}


class DirectSourceError(RuntimeError):
    pass


class DirectSourceReadOnlyClient:
    """Small GET-only client for allowlisted upstreams."""

    def __init__(
        self,
        *,
        http_client: Any | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self._http_client = http_client
        self.timeout_s = float(timeout_s)

    @property
    def real_execution(self) -> bool:
        return False

    def get_json(
        self,
        source_id: str,
        *,
        params: Mapping[str, object] | None = None,
        api_key: str = "",
    ) -> dict[str, Any]:
        spec = DIRECT_SOURCES.get(str(source_id))
        if spec is None:
            raise ValueError("DIRECT_SOURCE_NOT_ALLOWLISTED")
        if spec.requires_api_key and not str(api_key or "").strip():
            raise DirectSourceError(f"{spec.source_id.upper()}_API_KEY_REQUIRED")

        query = dict(params or {})
        if spec.source_id == "fred":
            query.setdefault("file_type", "json")
            query["api_key"] = str(api_key).strip()

        owns_client = self._http_client is None
        client = self._http_client or httpx.Client(timeout=self.timeout_s)
        try:
            response = client.get(spec.base_url, params=query)
            status = int(response.status_code)
            if status != 200:
                raise DirectSourceError(
                    f"DIRECT_SOURCE_HTTP_{spec.source_id.upper()}_{status}"
                )
            payload = response.json()
        except DirectSourceError:
            raise
        except Exception as exc:
            raise DirectSourceError(
                f"DIRECT_SOURCE_REQUEST_FAILED:{spec.source_id}:"
                f"{exc.__class__.__name__}"
            ) from exc
        finally:
            if owns_client:
                client.close()
        if not isinstance(payload, dict):
            raise DirectSourceError("DIRECT_SOURCE_PAYLOAD_NOT_OBJECT")
        return payload


def normalize_usgs(
    payload: Mapping[str, Any],
    *,
    received_ts_ms: int,
    min_magnitude: float = 4.5,
) -> list[ExternalEvent]:
    rows = payload.get("features")
    if not isinstance(rows, list):
        return []
    out: list[ExternalEvent] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        properties = row.get("properties")
        if not isinstance(properties, Mapping):
            continue
        event_id = str(row.get("id") or "").strip()
        mag = _finite(properties.get("mag"))
        event_ts = _int_or_none(properties.get("time"))
        updated = _int_or_none(properties.get("updated"))
        if (
            not event_id
            or mag is None
            or mag < float(min_magnitude)
            or event_ts is None
            or event_ts > int(received_ts_ms)
        ):
            continue
        place = str(properties.get("place") or "").strip()
        url = str(properties.get("url") or "").strip()
        severity = min(1.0, max(0.0, (mag - 4.0) / 4.0))
        out.append(
            ExternalEvent(
                event_id=f"usgs:{event_id}",
                source="usgs.earthquakes",
                event_type=ExternalEventType.NATURAL,
                source_tier=SourceTier.PRIMARY_OFFICIAL,
                retrieval_ts_ms=int(received_ts_ms),
                ingest_ts_ms=int(received_ts_ms),
                event_ts_ms=event_ts,
                publication_ts_ms=(
                    updated
                    if updated is not None and updated <= int(received_ts_ms)
                    else None
                ),
                source_link=url,
                regions=(place,) if place else (),
                severity=severity,
                classification_confidence=1.0,
                corroboration_count=1,
                methodology_version="usgs-geojson-v1",
                raw_evidence_ref=f"usgs:{event_id}:{received_ts_ms}",
            )
        )
    return out


def normalize_eonet(
    payload: Mapping[str, Any],
    *,
    received_ts_ms: int,
) -> list[ExternalEvent]:
    rows = payload.get("events")
    if not isinstance(rows, list):
        return []
    out: list[ExternalEvent] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        event_id = str(row.get("id") or "").strip()
        if not event_id:
            continue
        categories = row.get("categories")
        category_ids = tuple(
            str(item.get("id") or "").strip()
            for item in categories
            if isinstance(item, Mapping) and str(item.get("id") or "").strip()
        ) if isinstance(categories, list) else ()
        geometry = row.get("geometry")
        event_ts = None
        if isinstance(geometry, list) and geometry:
            last = geometry[-1]
            if isinstance(last, Mapping):
                event_ts = _iso_ms(last.get("date"))
        if event_ts is not None and event_ts > int(received_ts_ms):
            event_ts = None
        link = str(row.get("link") or "").strip()
        out.append(
            ExternalEvent(
                event_id=f"eonet:{event_id}",
                source="nasa.eonet",
                event_type=_natural_type(category_ids),
                source_tier=SourceTier.PRIMARY_OFFICIAL,
                retrieval_ts_ms=int(received_ts_ms),
                ingest_ts_ms=int(received_ts_ms),
                event_ts_ms=event_ts,
                source_link=link,
                entities=category_ids,
                classification_confidence=1.0,
                corroboration_count=1,
                methodology_version="nasa-eonet-v3",
                raw_evidence_ref=f"eonet:{event_id}:{received_ts_ms}",
            )
        )
    return out


def normalize_gdacs(
    payload: Mapping[str, Any],
    *,
    received_ts_ms: int,
) -> list[ExternalEvent]:
    rows = (
        payload.get("features")
        if isinstance(payload.get("features"), list)
        else payload.get("events")
    )
    if not isinstance(rows, list):
        return []
    out: list[ExternalEvent] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        props = row.get("properties")
        props = props if isinstance(props, Mapping) else row
        event_id = str(
            props.get("eventid")
            or props.get("eventId")
            or props.get("id")
            or ""
        ).strip()
        if not event_id:
            continue
        event_type = str(
            props.get("eventtype")
            or props.get("eventType")
            or ""
        ).upper()
        alert = str(
            props.get("alertlevel")
            or props.get("alertLevel")
            or ""
        ).casefold()
        event_ts = _iso_ms(
            props.get("fromdate")
            or props.get("fromDate")
            or props.get("date")
        )
        if event_ts is not None and event_ts > int(received_ts_ms):
            event_ts = None
        country = str(
            props.get("country")
            or props.get("countryname")
            or ""
        ).strip()
        source_link = str(
            props.get("url")
            or props.get("link")
            or ""
        ).strip()
        out.append(
            ExternalEvent(
                event_id=f"gdacs:{event_type}:{event_id}",
                source="gdacs",
                event_type=_gdacs_type(event_type),
                source_tier=SourceTier.PRIMARY_OFFICIAL,
                retrieval_ts_ms=int(received_ts_ms),
                ingest_ts_ms=int(received_ts_ms),
                event_ts_ms=event_ts,
                source_link=source_link,
                regions=(country,) if country else (),
                severity=_gdacs_severity(alert),
                classification_confidence=1.0,
                corroboration_count=1,
                methodology_version="gdacs-api-v1",
                raw_evidence_ref=f"gdacs:{event_type}:{event_id}:{received_ts_ms}",
            )
        )
    return out


def normalize_gdelt_articles(
    payload: Mapping[str, Any],
    *,
    received_ts_ms: int,
) -> list[ExternalEvent]:
    rows = payload.get("articles")
    if not isinstance(rows, list):
        return []
    out: list[ExternalEvent] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        url = str(row.get("url") or "").strip()
        seen = str(row.get("seendate") or "").strip()
        domain = str(row.get("domain") or "").strip()
        language = str(row.get("language") or "").strip()
        if not url:
            continue
        publication_ts = _gdelt_datetime_ms(seen)
        if (
            publication_ts is not None
            and publication_ts > int(received_ts_ms)
        ):
            publication_ts = None
        event_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:28]
        out.append(
            ExternalEvent(
                event_id=f"gdelt:{event_id}",
                source="gdelt.doc",
                event_type=ExternalEventType.NEWS,
                source_tier=SourceTier.AGGREGATOR,
                retrieval_ts_ms=int(received_ts_ms),
                ingest_ts_ms=int(received_ts_ms),
                publication_ts_ms=publication_ts,
                source_link=url,
                entities=tuple(
                    value for value in (domain, language) if value
                ),
                classification_confidence=1.0,
                corroboration_count=1,
                methodology_version="gdelt-doc-2",
                raw_evidence_ref=f"gdelt:{event_id}:{received_ts_ms}",
            )
        )
    return out


def normalize_fred_observations(
    payload: Mapping[str, Any],
    *,
    received_ts_ms: int,
    series_id: str,
) -> list[ExternalEvent]:
    rows = payload.get("observations")
    if not isinstance(rows, list):
        return []
    out: list[ExternalEvent] = []
    series = str(series_id or "").strip().upper()
    if not series:
        raise ValueError("series_id is required")
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        value = _finite(row.get("value"))
        date = str(row.get("date") or "").strip()
        if value is None or not date:
            continue
        event_id = f"fred:{series}:{date}"
        out.append(
            ExternalEvent(
                event_id=event_id,
                source="fred",
                event_type=ExternalEventType.MACRO,
                source_tier=SourceTier.PRIMARY_OFFICIAL,
                retrieval_ts_ms=int(received_ts_ms),
                ingest_ts_ms=int(received_ts_ms),
                entities=(series, date, f"value={value}"),
                classification_confidence=1.0,
                corroboration_count=1,
                methodology_version="fred-series-observations-v1",
                raw_evidence_ref=f"{event_id}:{received_ts_ms}",
            )
        )
    return out


def gdelt_query_params(
    query: str,
    *,
    max_records: int = 250,
    timespan: str = "15min",
) -> dict[str, object]:
    return {
        "query": str(query),
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max(1, min(250, int(max_records))),
        "timespan": str(timespan),
        "sort": "DateDesc",
    }


def gdacs_query_params(
    *,
    event_types: tuple[str, ...] = ("EQ", "TC", "FL", "VO", "WF"),
    alert_levels: tuple[str, ...] = ("red", "orange"),
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, object]:
    params: dict[str, object] = {
        "eventlist": ";".join(event_types),
        "alertlevel": ";".join(alert_levels),
    }
    if from_date:
        params["fromdate"] = str(from_date)
    if to_date:
        params["todate"] = str(to_date)
    return params


def _natural_type(categories: tuple[str, ...]) -> ExternalEventType:
    lowered = " ".join(categories).casefold()
    if "severestorm" in lowered:
        return ExternalEventType.WEATHER
    return ExternalEventType.NATURAL


def _gdacs_type(value: str) -> ExternalEventType:
    upper = str(value).upper()
    if upper in {"TC"}:
        return ExternalEventType.WEATHER
    return ExternalEventType.NATURAL


def _gdacs_severity(value: str) -> float | None:
    lowered = str(value).casefold()
    if "red" in lowered:
        return 1.0
    if "orange" in lowered:
        return 0.75
    if "green" in lowered:
        return 0.25
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _iso_ms(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def _gdelt_datetime_ms(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None


__all__ = [
    "DIRECT_SOURCES",
    "DirectSourceError",
    "DirectSourceReadOnlyClient",
    "DirectSourceSpec",
    "gdacs_query_params",
    "gdelt_query_params",
    "normalize_eonet",
    "normalize_fred_observations",
    "normalize_gdacs",
    "normalize_gdelt_articles",
    "normalize_usgs",
]
