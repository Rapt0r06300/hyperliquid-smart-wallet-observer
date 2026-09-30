"""The read-only dashboard must not fabricate chart series or positions."""

import re
from pathlib import Path

FAKE = re.compile(
    r"(math\.random|fakeposition|fake_position|dummyequity|dummy_equity"
    r"|mock_chart|fabricated_pnl|hardcoded_pnl|fake_data\s*=\s*true)",
    re.I,
)


def _static_frontend_files():
    for base in (Path("src"), Path("hyper_smart_observer")):
        if base.exists():
            for p in base.rglob("*"):
                if "static" in p.parts and p.suffix.lower() in {".html", ".js"}:
                    yield p


def test_dashboard_has_no_fake_chart_or_position_data():
    hits = []
    for p in _static_frontend_files():
        for m in FAKE.finditer(p.read_text(encoding="utf-8", errors="ignore")):
            hits.append((str(p), m.group(0)))
    assert hits == [], f"fake chart/position markers: {hits[:5]}"
