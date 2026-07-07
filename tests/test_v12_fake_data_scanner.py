import pytest

from hl_observer.security.fake_data_scanner import (
    assert_no_fake_data,
    scan_for_fake_data,
)


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_active_runtime_is_clean():
    """The active runtime must contain no fabricated-data generators (rule #1)."""
    findings = scan_for_fake_data()  # default root = hl_observer package
    assert findings == [], "\n".join(str(f) for f in findings)


def test_detects_random_market_value(tmp_path):
    f = _write(tmp_path, "bad.py", "def q():\n    mid_price = random.uniform(100, 200)\n    return mid_price\n")
    findings = scan_for_fake_data([f])
    assert any(x.rule == "RANDOM_MARKET_VALUE" for x in findings)


def test_random_without_market_term_not_flagged(tmp_path):
    f = _write(
        tmp_path, "ok.py",
        "import random\n"
        "delay = random.uniform(0.1, 0.5)\n"        # jitter, no market term
        "proxy = random.choice(proxy_pool)\n",      # rotation, no market term
    )
    assert scan_for_fake_data([f]) == []


def test_detects_faker(tmp_path):
    f = _write(tmp_path, "fk.py", "from faker import Faker\nf = Faker()\n")
    findings = scan_for_fake_data([f])
    assert any(x.rule == "FAKER_LIBRARY" for x in findings)


def test_detects_named_fabricator(tmp_path):
    f = _write(tmp_path, "nm.py", "def fake_fill(coin):\n    return {}\n")
    findings = scan_for_fake_data([f])
    assert any(x.rule == "NAMED_FABRICATOR" for x in findings)


def test_synthetic_rows_bridge_not_flagged(tmp_path):
    """The legitimate real->model bridge `synthetic_rows` must NOT be flagged."""
    f = _write(
        tmp_path, "bridge.py",
        "synthetic_rows = build_position_deltas_from_real_clusters(clusters)\n"
        "for row in synthetic_rows:\n    handle(row)\n",
    )
    assert scan_for_fake_data([f]) == []


def test_inline_allow_suppresses(tmp_path):
    f = _write(
        tmp_path, "allowed.py",
        "px = random.uniform(1, 2)  # fake-data-scan: allow unit-test fixture only\n",
    )
    assert scan_for_fake_data([f]) == []


def test_assert_raises_on_fake(tmp_path):
    f = _write(tmp_path, "boom.py", "fill_price = random.gauss(10, 1)\n")
    with pytest.raises(AssertionError):
        assert_no_fake_data([f])
