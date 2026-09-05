"""Coverage of pure market-symbol normalization branches, with no network/runtime imports."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SOURCE = Path(__file__).resolve().parents[1] / "src" / "hl_observer" / "market_data" / "market_matcher.py"
_SPEC = importlib.util.spec_from_file_location("_market_matcher_gap_target", _SOURCE)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
match_market_symbol = _MODULE.match_market_symbol


def test_alias_table_and_custom_alias_are_normalized() -> None:
    assert match_market_symbol(" btc-perp ") == "BTC"
    assert match_market_symbol("sol-usdc", {"SOL-USDC": "sol"}) == "SOL"


def test_separator_fallbacks_plain_symbol_and_empty_input() -> None:
    assert match_market_symbol("arb/usdc") == "ARB"
    assert match_market_symbol("op_usdc") == "OP"
    assert match_market_symbol("avax") == "AVAX"
    assert match_market_symbol("") == ""
