"""Fake-data scanner (V12 capability U — anti-regression).

Static guard that fails if fabricated market/PnL data generators reappear in the
*active* runtime (``src/hl_observer``). Rule #1 of the project: NO FAKE / NO DEMO
— every number must come from real Hyperliquid data, never invented.

It flags three smells:
  * RANDOM_MARKET_VALUE — a ``random`` / ``numpy.random`` call on a line that also
    mentions a market or PnL term (price, mid, pnl, fill, equity, ...). Random used
    for jitter / backoff / proxy rotation / sampling is NOT flagged (no market term).
  * FAKER_LIBRARY      — any use of the ``faker`` package.
  * NAMED_FABRICATOR   — names like ``fake_price``, ``synthetic_fill``, ``demo_price``,
    ``fabricate_*``. The legitimate real->model bridge ``synthetic_rows`` is exempt.

A line may opt out with a trailing comment ``# fake-data-scan: allow <reason>``.
Pure static analysis: reads text, never imports or runs the scanned code.
"""

from __future__ import annotations

import os
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path

# Default = the active runtime package (this file lives in hl_observer/security/).
DEFAULT_SCAN_ROOT = Path(__file__).resolve().parents[1]

_EXCLUDED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "logs", "tmp_pytest"}
# Skip self to avoid matching our own pattern literals.
_EXCLUDED_FILENAMES = {"fake_data_scanner.py"}

_ALLOW_MARKER = "fake-data-scan: " + "allow"

# Letter-only boundaries so underscore-joined identifiers match too
# (e.g. "mid_price", "fill_price", "closed_pnl"), while "supricey" does not.
_MARKET_TERM = re.compile(
    r"(?<![A-Za-z])(price|prices|mid|mids|pnl|fill|fills|balance|equity|"
    r"notional|qty|size|roi|mark|avg_price|entry_price|funding)(?![A-Za-z])",
    re.IGNORECASE,
)
_RANDOM_CALL = re.compile(
    r"\b(random\.(uniform|random|gauss|normalvariate|randint|randrange|choice|choices)"
    r"|np\.random|numpy\.random)\b"
)
_FAKER = re.compile(r"\bfrom\s+faker\b|\bimport\s+faker\b|\bFaker\s*\(")
# Named fabricators — split literals so the scanner file itself stays clean.
_FAB = "fa" + "ke"
_SYN = "synth" + "etic"
_NAMED_FABRICATOR = re.compile(
    rf"\b({_FAB}_(price|fill|fills|pnl|wallet|trade|mid)"
    rf"|{_SYN}_(price|fill|pnl|mid)"
    r"|demo_(price|fill|pnl)"
    r"|dummy_(price|fill)"
    r"|mock_(price|fill|pnl)"
    r"|random_(price|pnl|fill)"
    rf"|fabricate_\w+|make_{_FAB}\w*|generate_{_FAB}\w*)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class FakeDataFinding:
    path: str
    lineno: int
    rule: str
    snippet: str

    def __str__(self) -> str:
        return f"{self.rule} {self.path}:{self.lineno}: {self.snippet}"


def _iter_py_files(root: Path):
    root = Path(root)
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        raise FileNotFoundError(f"fake-data scan root is unavailable: {root}")
    errors: list[OSError] = []
    for dirpath, dirnames, filenames in os.walk(
        root, topdown=True, followlinks=False, onerror=errors.append,
    ):
        # Prune excluded trees before descending, rather than discovering every
        # vendored/cache file and discarding it after traversal.
        dirnames[:] = sorted(name for name in dirnames if name not in _EXCLUDED_DIRS)
        for name in sorted(filenames):
            if not name.endswith(".py") or name in _EXCLUDED_FILENAMES:
                continue
            yield Path(dirpath) / name
    if errors:
        first = errors[0]
        raise OSError(f"fake-data inventory incomplete: {first}") from first


def _scan_text(path: str, text: str) -> list[FakeDataFinding]:
    findings: list[FakeDataFinding] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or _ALLOW_MARKER in raw:
            continue
        if _RANDOM_CALL.search(line) and _MARKET_TERM.search(line):
            findings.append(FakeDataFinding(path, i, "RANDOM_MARKET_VALUE", line[:160]))
            continue
        if _FAKER.search(line):
            findings.append(FakeDataFinding(path, i, "FAKER_LIBRARY", line[:160]))
            continue
        if _NAMED_FABRICATOR.search(line):
            findings.append(FakeDataFinding(path, i, "NAMED_FABRICATOR", line[:160]))
    return findings


def scan_for_fake_data(roots=None):
    targets = [Path(r) for r in roots] if roots else [DEFAULT_SCAN_ROOT]
    findings = []
    for root in targets:
        try:
            for path in _iter_py_files(root):
                try:
                    with tokenize.open(path) as stream:
                        text = stream.read()
                except (OSError, UnicodeError, LookupError, SyntaxError) as exc:
                    findings.append(FakeDataFinding(
                        str(path), 0, "SCAN_INCOMPLETE",
                        f"could not read source ({type(exc).__name__})",
                    ))
                    continue
                findings.extend(_scan_text(str(path), text))
        except OSError as exc:
            findings.append(FakeDataFinding(
                str(root), 0, "SCAN_INCOMPLETE",
                f"could not enumerate source ({type(exc).__name__})",
            ))
    return findings


def assert_no_fake_data(roots=None) -> None:
    findings = scan_for_fake_data(roots)
    if findings:
        report = chr(10).join(str(f) for f in findings)
        raise AssertionError(
            "fabricated-data generator(s) detected in runtime "
            + "(" + str(len(findings)) + "):" + chr(10) + report
        )


__all__ = ["FakeDataFinding", "scan_for_fake_data", "assert_no_fake_data", "DEFAULT_SCAN_ROOT"]
