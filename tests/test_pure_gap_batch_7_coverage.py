from __future__ import annotations

from hl_observer.accounting.fixed_point_core import UNMEASURABLE, vers_unites


def test_fixed_point_rejects_decimal_parse_failure() -> None:
    assert vers_unites("not-a-decimal", scale=2) == UNMEASURABLE
