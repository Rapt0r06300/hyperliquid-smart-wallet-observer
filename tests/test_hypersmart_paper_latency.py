from datetime import datetime, timedelta
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc

import pytest

from hyper_smart_observer.paper_trading.latency import simulate_latency_timestamp


def test_hypersmart_simulate_latency_timestamp_adds_latency():
    base = datetime(2026, 1, 1, tzinfo=UTC)

    assert simulate_latency_timestamp(base, 500) == base + timedelta(milliseconds=500)


def test_hypersmart_simulate_latency_timestamp_refuses_negative_latency():
    with pytest.raises(ValueError):
        simulate_latency_timestamp(datetime.now(UTC), -1)
