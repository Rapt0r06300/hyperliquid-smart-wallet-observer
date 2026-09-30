"""Read the collector's feed-quality snapshot without inventing readiness.

The collector owns ``runtime/data/feed_quality.json``.  Decision code consumes
that file through this small adapter instead of parsing an evolving runtime
payload in several places.

Missing, malformed or stale state is explicit.  It never becomes a healthy
zero-value default.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "hypersmart.feed_quality.v1"
DEFAULT_MAX_FILE_AGE_MS = 5_000.0
DEFAULT_MIN_SCORE = 75.0
REQUIRED_CHANNELS = ("bbo", "l2Book")


@dataclass(frozen=True, slots=True)
class CoinFeedQuality:
    coin: str
    ready: bool
    feed_quality_score: float | None
    reasons: tuple[str, ...]
    generated_at_ms: int | None
    file_age_ms: float | None
    required_channels: tuple[str, ...]
    ready_channels: tuple[str, ...]
    feed_keys: tuple[str, ...]
    source_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin,
            "ready": self.ready,
            "feed_quality_score": self.feed_quality_score,
            "reasons": list(self.reasons),
            "generated_at_ms": self.generated_at_ms,
            "file_age_ms": self.file_age_ms,
            "required_channels": list(self.required_channels),
            "ready_channels": list(self.ready_channels),
            "feed_keys": list(self.feed_keys),
            "source_path": self.source_path,
        }


def read_coin_feed_quality(
    path: Path,
    *,
    coin: str,
    now_ms: int | None = None,
    max_file_age_ms: float = DEFAULT_MAX_FILE_AGE_MS,
    min_score: float = DEFAULT_MIN_SCORE,
    required_channels: tuple[str, ...] = REQUIRED_CHANNELS,
) -> CoinFeedQuality:
    """Return one conservative quality decision for ``coin``.

    BBO and L2 are mandatory for executable-price decisions.  Public trades
    remain useful context, but a quiet trade stream must not invalidate a
    coherent book.  The aggregate score is the minimum score of mandatory
    feeds, not an average that could hide one broken channel.
    """
    source_path = str(Path(path))
    normalized_coin = str(coin or "").strip().upper()
    reasons: list[str] = []
    blocking_reasons: list[str] = []
    generated_at_ms: int | None = None
    file_age_ms: float | None = None

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return _missing(
            normalized_coin,
            source_path,
            required_channels,
            "FEED_QUALITY_FILE_MISSING",
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return _missing(
            normalized_coin,
            source_path,
            required_channels,
            "FEED_QUALITY_FILE_INVALID",
        )

    if not isinstance(payload, Mapping):
        return _missing(
            normalized_coin,
            source_path,
            required_channels,
            "FEED_QUALITY_PAYLOAD_INVALID",
        )
    if payload.get("schema_version") != SCHEMA_VERSION:
        reasons.append("FEED_QUALITY_SCHEMA_UNSUPPORTED")
        blocking_reasons.append("FEED_QUALITY_SCHEMA_UNSUPPORTED")

    generated_at_ms = _optional_int(payload.get("generated_at_ms"))
    current_ms = int(time.time() * 1_000) if now_ms is None else int(now_ms)
    if generated_at_ms is None:
        reasons.append("FEED_QUALITY_GENERATED_AT_MISSING")
        blocking_reasons.append("FEED_QUALITY_GENERATED_AT_MISSING")
    else:
        file_age_ms = max(0.0, float(current_ms - generated_at_ms))
        if generated_at_ms > current_ms + 1_000:
            reasons.append("FEED_QUALITY_FILE_FROM_FUTURE")
            blocking_reasons.append("FEED_QUALITY_FILE_FROM_FUTURE")
        if file_age_ms > float(max_file_age_ms):
            reasons.append("FEED_QUALITY_FILE_STALE")
            blocking_reasons.append("FEED_QUALITY_FILE_STALE")

    feeds = payload.get("feeds")
    if not isinstance(feeds, Mapping):
        reasons.append("FEED_QUALITY_FEEDS_MISSING")
        blocking_reasons.append("FEED_QUALITY_FEEDS_MISSING")
        feeds = {}

    selected: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for key, value in feeds.items():
        if not isinstance(value, Mapping):
            continue
        channel = str(value.get("channel") or "").strip()
        instrument = str(value.get("instrument") or "").strip().upper()
        if instrument != normalized_coin or channel not in required_channels:
            continue
        selected[channel] = (str(key), value)

    scores: list[float] = []
    ready_channels: list[str] = []
    feed_keys: list[str] = []
    for channel in required_channels:
        selected_feed = selected.get(channel)
        if selected_feed is None:
            reasons.append(f"REQUIRED_FEED_MISSING:{channel}")
            blocking_reasons.append(f"REQUIRED_FEED_MISSING:{channel}")
            continue
        feed_key, feed = selected_feed
        feed_keys.append(feed_key)
        score = _optional_float(feed.get("feed_quality_score"))
        if score is None:
            reasons.append(f"FEED_SCORE_UNMEASURABLE:{channel}")
            blocking_reasons.append(f"FEED_SCORE_UNMEASURABLE:{channel}")
        else:
            scores.append(score)
            if score < float(min_score):
                reasons.append(f"FEED_SCORE_TOO_LOW:{channel}")
                blocking_reasons.append(f"FEED_SCORE_TOO_LOW:{channel}")
        if bool(feed.get("ready")):
            ready_channels.append(channel)
        else:
            reasons.append(f"FEED_NOT_READY:{channel}")
            blocking_reasons.append(f"FEED_NOT_READY:{channel}")
        child_reasons = feed.get("reasons")
        if isinstance(child_reasons, list):
            for reason in child_reasons:
                text = str(reason or "").strip()
                if text:
                    reasons.append(f"{channel}:{text}")

    aggregate_score = min(scores) if len(scores) == len(required_channels) else None
    ready = (
        not blocking_reasons
        and len(ready_channels) == len(required_channels)
        and aggregate_score is not None
        and aggregate_score >= float(min_score)
    )
    return CoinFeedQuality(
        coin=normalized_coin,
        ready=ready,
        feed_quality_score=aggregate_score,
        reasons=tuple(dict.fromkeys(reasons)),
        generated_at_ms=generated_at_ms,
        file_age_ms=file_age_ms,
        required_channels=required_channels,
        ready_channels=tuple(ready_channels),
        feed_keys=tuple(feed_keys),
        source_path=source_path,
    )


def _missing(
    coin: str,
    source_path: str,
    required_channels: tuple[str, ...],
    reason: str,
) -> CoinFeedQuality:
    return CoinFeedQuality(
        coin=coin,
        ready=False,
        feed_quality_score=None,
        reasons=(reason,),
        generated_at_ms=None,
        file_age_ms=None,
        required_channels=required_channels,
        ready_channels=(),
        feed_keys=(),
        source_path=source_path,
    )


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "CoinFeedQuality",
    "DEFAULT_MAX_FILE_AGE_MS",
    "DEFAULT_MIN_SCORE",
    "REQUIRED_CHANNELS",
    "SCHEMA_VERSION",
    "read_coin_feed_quality",
]
