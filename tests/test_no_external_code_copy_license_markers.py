"""External GitHub repos are idea sources only. No copied-code license markers
should appear in HyperSmart source files."""

import re
from pathlib import Path

MARKERS = re.compile(
    r"(copyright \(c\)|spdx-license-identifier|all rights reserved"
    r"|licensed under the (mit|apache|gpl|bsd))",
    re.I,
)


def test_no_foreign_license_or_copyright_markers_in_source():
    hits = []
    for root in ("hyper_smart_observer", "src"):
        base = Path(root)
        if base.exists():
            for p in base.rglob("*.py"):
                if "__pycache__" in p.parts:
                    continue
                if MARKERS.search(p.read_text(encoding="utf-8", errors="ignore")):
                    hits.append(str(p))
    assert hits == [], f"foreign license/copyright markers: {hits[:5]}"
