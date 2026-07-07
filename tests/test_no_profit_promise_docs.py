"""Docs must not make affirmative profit promises.

Anti-hype policy / research / audit docs legitimately ENUMERATE banned hype
phrases; they are excluded by name. All other docs must not promise profit.
"""

import re
from pathlib import Path

PROMISE = re.compile(
    r"(profitable tonight|make money tonight|garantie de gains|profit garanti ce soir"
    r"|100%\s*win\s*rate|risk[- ]free profit|no[- ]risk profit|guaranteed to (win|profit))",
    re.I,
)
# Docs whose purpose is to LIST/forbid hype (so they contain banned phrases).
EXCLUDE_DOC = re.compile(r"(POLICY|PROTOCOL|NO_FAKE|NO_HYPE|AUDIT|OSINT|CLAIMS|MATRIX)", re.I)


def test_docs_contain_no_affirmative_profit_promise():
    hits = []
    for p in Path("docs").rglob("*.md"):
        if EXCLUDE_DOC.search(p.name):
            continue
        for m in PROMISE.finditer(p.read_text(encoding="utf-8", errors="ignore")):
            hits.append((str(p), m.group(0)))
    assert hits == [], f"affirmative profit promise: {hits[:5]}"
