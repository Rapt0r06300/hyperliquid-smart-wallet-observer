"""No Polymarket CLOB client, no @polymarket, no ethers-for-trading, no hardcoded
EVM private key in source."""

import re
from pathlib import Path

BANNED = re.compile(
    r"(clob-client|@polymarket|buy_polymarket|from\s+ethers|import\s+ethers"
    r"|require\(['\"]ethers['\"]\)|private_key\s*=\s*['\"]0x[0-9a-fA-F])",
    re.I,
)


def _files():
    for root in ("hyper_smart_observer", "src"):
        base = Path(root)
        if base.exists():
            for p in base.rglob("*"):
                if p.suffix.lower() in {".py", ".js", ".ts", ".json"} and "__pycache__" not in p.parts:
                    yield p


def test_no_polymarket_clob_or_eth_private_key():
    hits = []
    for p in _files():
        for m in BANNED.finditer(p.read_text(encoding="utf-8", errors="ignore")):
            hits.append((str(p), m.group(0)))
    assert hits == [], f"banned import/usage: {hits[:5]}"
