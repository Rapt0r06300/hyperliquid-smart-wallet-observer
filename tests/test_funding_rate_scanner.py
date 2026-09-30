from hl_observer.funding.funding_rate_scanner import scan_funding_rates
from hl_observer.funding.funding_times import next_funding_time_ms


def test_funding_rate_scanner_and_next_time():
    rows = scan_funding_rates([{"coin": "HYPE", "rates": [0, 0, 0, 0, 0.1]}], sigma=2.0)
    assert rows[0].decision == "FUNDING_SPIKE"
    assert next_funding_time_ms(0) == 8 * 60 * 60 * 1000
