"""No signature call and no real-trading toggle ENABLED in source.

Refusal/guard contexts (lines that forbid a flag, e.g.
'raise ValueError("allow_trading=True est interdit")') are allowed: they prove
the flag is blocked, not enabled.
"""

import re
from pathlib import Path

from hyper_smart_observer.audit.source_scanner import scan_source_forbidden_terms

TOGGLE = re.compile(
    r"(tradingenabled\s*=\s*true|enable_trading\s*=\s*true|live_?toggle\s*=\s*true"
    r"|allow_trading\s*=\s*true|allow_private_key\s*=\s*true)",
    re.I,
)
# Lines that merely DESCRIBE/BLOCK the flag (not enable it).
SAFE_CONTEXT = re.compile(
    r"(interdit|safety|viol|bloqu|failed|critical|raise|forbid|refus|assert|"
    r"is not|!=|==|append\(|warn|#)",
    re.I,
)


def _py_files():
    for root in ("hyper_smart_observer", "src"):
        base = Path(root)
        if base.exists():
            for p in base.rglob("*.py"):
                if "__pycache__" not in p.parts:
                    yield p


def test_no_signature_calls_in_source():
    assert scan_source_forbidden_terms(Path("hyper_smart_observer"))["sign_call"] == []


def test_no_real_trading_toggle_enabled():
    hits = []
    for p in _py_files():
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if TOGGLE.search(line) and not SAFE_CONTEXT.search(line):
                hits.append((str(p), line.strip()[:90]))
    assert hits == [], f"real-trading toggle ENABLED: {hits[:5]}"
