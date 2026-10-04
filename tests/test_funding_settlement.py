"""Funding certification tests: actual settlement evidence beats accrual inference."""
from __future__ import annotations

import pytest

from hl_observer.paper_trading.funding_settlement import (
    PERIODE_REGLEMENT_MS, agreger, decouper, pnl_stable, reglements_franchis,
)

H = PERIODE_REGLEMENT_MS
T_PILE = (1_760_000_000_000 // H) * H


def _pos(accru=1.0, entree=T_PILE, **kw):
    p = {"coin": "BTC", "funding_accrued_usdt": accru, "entry_ts_ms": entree, "notional_usdt": 500.0}
    p.update(kw)
    return p


def test_aucun_sommet_franchi_meme_apres_59_minutes():
    assert reglements_franchis(T_PILE + 30_000, T_PILE + H - 1_000) == 0
    assert reglements_franchis(T_PILE + 30_000, T_PILE + H + 1) == 1


def test_boundary_count_never_creates_settled_cash():
    d = decouper(_pos(accru=1.0), now_ms=int(T_PILE + 10.5 * H))
    assert d["heures_reglees"] == 10.0
    assert d["net_funding_settled"] == 0.0
    assert d["funding_accrual_estimate"] == pytest.approx(1.0)
    assert d["funding_certified"] is False


def test_before_first_boundary_zero_settlement_is_certified():
    d = decouper(_pos(accru=0.05), now_ms=T_PILE + 20 * 60_000)
    assert d["net_funding_settled"] == 0.0
    assert d["funding_accrual_estimate"] == pytest.approx(0.05)
    assert d["funding_certified"] is True
    assert d["funding_certification_reason"] == "NO_SETTLEMENT_BOUNDARY_CROSSED"


def test_complete_user_funding_events_are_certified_and_deduped():
    events = [
        {"time": T_PILE + H, "hash": "a", "delta": {"type": "funding", "coin": "BTC", "usdc": "0.12"}},
        {"time": T_PILE + H, "hash": "a", "delta": {"type": "funding", "coin": "BTC", "usdc": "0.12"}},
        {"time": T_PILE + 2 * H, "hash": "b", "delta": {"type": "funding", "coin": "BTC", "usdc": "-0.02"}},
    ]
    d = decouper(
        _pos(accru=0.15, user_funding_events=events, funding_settlement_evidence_complete=True),
        now_ms=T_PILE + 2 * H + 1,
    )
    assert d["net_funding_settled"] == pytest.approx(0.10)
    assert d["funding_accrual_estimate"] == pytest.approx(0.05)
    assert d["settlement_evidence_count"] == 2
    assert d["funding_certified"] is True


def test_incomplete_event_list_is_diagnostic_only():
    d = decouper(
        _pos(accru=0.4, user_funding_events=[
            {"time": T_PILE + H, "hash": "a", "delta": {"type": "funding", "usdc": "0.2"}}
        ]),
        now_ms=T_PILE + 2 * H,
    )
    assert d["settlement_evidence_count"] == 1
    assert d["net_funding_settled"] == 0.0
    assert d["funding_accrual_estimate"] == pytest.approx(0.4)
    assert d["funding_certified"] is False


def test_trusted_exact_reconstruction_is_accepted():
    d = decouper(
        _pos(accru=0.6, net_funding_settled=0.45,
             funding_settlement_source="EXACT_SETTLEMENT_RECONSTRUCTION",
             funding_settlement_evidence_count=3),
        now_ms=T_PILE + 3 * H,
    )
    assert d["net_funding_settled"] == pytest.approx(0.45)
    assert d["funding_accrual_estimate"] == pytest.approx(0.15)
    assert d["funding_certified"] is True


def test_untrusted_scalar_cannot_certify_funding():
    d = decouper(_pos(accru=0.6, net_funding_settled=0.45), now_ms=T_PILE + 3 * H)
    assert d["net_funding_settled"] == 0.0
    assert d["funding_certified"] is False


def test_missing_entry_timestamp_is_unmeasurable_not_invented():
    d = decouper({"funding_accrued_usdt": 1.0}, now_ms=T_PILE + H)
    assert d["net_funding_settled"] == 0.0
    assert d["funding_accrual_estimate"] == 1.0
    assert d["funding_certified"] is False


def test_agreger_propagates_unmeasurable_funding():
    a = agreger({"BTC": _pos(accru=0.1), "ETH": _pos(accru=0.2, entree=T_PILE - 3 * H)},
                now_ms=T_PILE + 2 * H)
    assert a["funding_certification_status"] == "UNMEASURABLE"
    assert a["funding_certified"] is False
    assert a["net_funding_settled"] == 0.0


def test_empty_portfolio_is_certified_zero():
    a = agreger({}, now_ms=T_PILE)
    assert a["funding_total_couru"] == 0.0
    assert a["positions"] == 0
    assert a["funding_certified"] is True


def test_pnl_stable_only_accepts_already_certified_amount():
    assert pnl_stable(-6.05, 0.20) == pytest.approx(-5.85)


def test_decoupage_est_branche_dans_etat_carry():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src" / "hl_observer" / "funding"
           / "carry_positions_store.py").read_text(encoding="utf-8")
    assert "funding_certification_status" in src
    assert 'stable_net_pnl"] = None' in src
